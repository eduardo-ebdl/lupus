"""Retriever: pipeline de busca em 3 estágios para RAG.

Estágio 1 — Retrieval dual (bi-encoders, rápido):
    FAISS semântico: embedding da query vs embeddings dos chunks (cosine similarity)
    BM25 keyword:    correspondência exata de termos (obito_srag_flag, liquid clustering)

Estágio 2 — Fusão:
    Reciprocal Rank Fusion combina os dois rankings sem calibrar pesos manuais.

Estágio 3 — Reranking (cross-encoder, preciso):
    CrossEncoder processa (query, chunk) juntos num único forward pass.
    Diferente do bi-encoder, o cross-encoder vê a interação entre query e chunk →
    scores de relevância mais precisos ao custo de ser mais lento (só roda em ~15 chunks).

Padrão de uso:
    retriever = Retriever.load(index_dir)
    results = retriever.search("como a idade é normalizada?", k=5, layer="silver")
    print(results.formatted)
"""

import json
import os
from dataclasses import dataclass, field

import faiss
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder, SentenceTransformer

from rag.indexer import EMBEDDING_MODEL

# Cross-encoder para reranking — processa (query, chunk) juntos, mais preciso que bi-encoder
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


@dataclass
class SearchResult:
    """Resultado de busca com conteúdo, metadados e score de relevância."""
    content: str
    file_path: str
    file_type: str
    layer: str
    chunk_type: str
    chunk_index: int
    model_name: str | None
    rrf_score: float

    def format(self, rank: int) -> str:
        label = f"{self.file_path}"
        if self.chunk_type == "notebook_cell":
            label += f" (célula {self.chunk_index})"
        elif self.chunk_type == "markdown_section":
            label += f" (seção {self.chunk_index})"

        ext_label = {"sql": "sql", "yml": "yaml", "ipynb": "python", "md": "markdown"}.get(self.file_type, "")
        return f"[{rank}] {label} | camada: {self.layer}\n```{ext_label}\n{self.content}\n```"


@dataclass
class SearchResponse:
    """Resposta formatada com múltiplos resultados e source attribution."""
    results: list[SearchResult] = field(default_factory=list)
    query: str = ""

    @property
    def formatted(self) -> str:
        if not self.results:
            return "Nenhum trecho relevante encontrado no codebase."
        header = f"Encontrei {len(self.results)} trecho(s) relevante(s) para: \"{self.query}\"\n"
        body = "\n\n".join(r.format(i + 1) for i, r in enumerate(self.results))
        return f"{header}\n{body}"


def _tokenize(text: str) -> list[str]:
    """Tokenização simples para BM25 — mantém termos de código (snake_case, etc.)."""
    return text.lower().split()


def _rrf(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion: combina múltiplos rankings sem precisar de pesos.

    score(d) = Σ 1 / (k + rank(d))
    k=60 é o valor padrão da literatura (Cormack et al., 2009).
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


class Retriever:
    """Hybrid retriever: FAISS (semântico) + BM25 (keyword) + RRF + CrossEncoder reranker."""

    def __init__(
        self,
        index: faiss.Index,
        chunks: list[dict],
        model: SentenceTransformer,
        reranker: CrossEncoder,
    ):
        self._index = index
        self._chunks = chunks
        self._model = model
        self._reranker = reranker

        # BM25 construído sobre todos os chunks no carregamento
        corpus = [_tokenize(c["content"]) for c in chunks]
        self._bm25 = BM25Okapi(corpus)

    @classmethod
    def load(
        cls,
        index_dir: str,
        model_name: str = EMBEDDING_MODEL,
        reranker_name: str = RERANKER_MODEL,
    ) -> "Retriever":
        """Carrega o índice FAISS, metadados, bi-encoder e cross-encoder do disco."""
        index_path = os.path.join(index_dir, "srag.index")
        metadata_path = os.path.join(index_dir, "srag_metadata.json")

        if not os.path.exists(index_path):
            raise FileNotFoundError(
                f"Índice RAG não encontrado em '{index_dir}'. "
                "Execute: python scripts/build_rag_index.py"
            )

        index = faiss.read_index(index_path)
        with open(metadata_path, encoding="utf-8") as f:
            chunks = json.load(f)

        model = SentenceTransformer(model_name)
        reranker = CrossEncoder(reranker_name)
        return cls(index, chunks, model, reranker)

    def search(
        self,
        query: str,
        k: int = 5,
        layer: str = "",
        candidate_pool: int = 15,
    ) -> SearchResponse:
        """Busca híbrida em 3 estágios: FAISS + BM25 → RRF → CrossEncoder reranker.

        Estágio 1 — Retrieval (bi-encoder, rápido):
            FAISS semântico + BM25 keyword, cada um retorna `candidate_pool` candidatos.
        Estágio 2 — Fusão:
            RRF combina os dois rankings → top `candidate_pool` candidatos finais.
        Estágio 3 — Reranking (cross-encoder, preciso):
            CrossEncoder processa (query, chunk) juntos → score de relevância mais fino.
            Top-k do reranker são retornados.

        Args:
            query: Pergunta em linguagem natural.
            k: Número de resultados finais a retornar.
            layer: Filtro por camada ('bronze', 'silver', 'gold', 'ai_agent', 'pipeline').
                   Se vazio, busca em todo o codebase.
            candidate_pool: Candidatos que cada método retorna antes do RRF.
                            O reranker recebe min(candidate_pool, n_eligible) candidatos.
        """
        # Determina quais chunks são elegíveis (filtro por layer)
        if layer:
            eligible = [i for i, c in enumerate(self._chunks) if c["layer"] == layer]
        else:
            eligible = list(range(len(self._chunks)))

        if not eligible:
            return SearchResponse(query=query)

        pool = min(candidate_pool, len(eligible))

        # --- Estágio 1a: Busca semântica (FAISS) ---
        query_vec = self._model.encode([query], convert_to_numpy=True)
        faiss.normalize_L2(query_vec)

        search_k = min(len(self._chunks), candidate_pool * 3)
        scores, indices = self._index.search(query_vec, search_k)
        semantic_ranking = [int(i) for i in indices[0] if int(i) in set(eligible)][:pool]

        # --- Estágio 1b: Busca keyword (BM25) ---
        tokens = _tokenize(query)
        bm25_scores = self._bm25.get_scores(tokens)
        masked = np.full(len(self._chunks), -np.inf)
        for i in eligible:
            masked[i] = bm25_scores[i]
        bm25_ranking = list(np.argsort(masked)[::-1][:pool])

        # --- Estágio 2: Reciprocal Rank Fusion ---
        fused = _rrf([semantic_ranking, bm25_ranking])
        # Passa candidate_pool candidatos para o reranker (não apenas k)
        rrf_candidates = [doc_id for doc_id, _ in fused[:pool]]
        fused_dict = dict(fused)

        # --- Estágio 3: CrossEncoder Reranking ---
        # Cross-encoder avalia (query, chunk) juntos — mais preciso que bi-encoder
        pairs = [(query, self._chunks[i]["content"]) for i in rrf_candidates]
        rerank_scores = self._reranker.predict(pairs)

        # Ordena pelos scores do reranker e seleciona top-k
        reranked = sorted(
            zip(rrf_candidates, rerank_scores),
            key=lambda x: x[1],
            reverse=True,
        )
        top_ids = [doc_id for doc_id, _ in reranked[:k]]

        results = [
            SearchResult(
                content=self._chunks[i]["content"],
                file_path=self._chunks[i]["file_path"],
                file_type=self._chunks[i]["file_type"],
                layer=self._chunks[i]["layer"],
                chunk_type=self._chunks[i]["chunk_type"],
                chunk_index=self._chunks[i]["chunk_index"],
                model_name=self._chunks[i].get("model_name"),
                rrf_score=fused_dict[i],
            )
            for i in top_ids
        ]

        return SearchResponse(results=results, query=query)


# Singleton global — carregado uma vez na primeira chamada da tool
_retriever: Retriever | None = None


def get_retriever(index_dir: str | None = None) -> Retriever:
    """Retorna o retriever singleton, carregando do disco se necessário."""
    global _retriever
    if _retriever is None:
        if index_dir is None:
            # Caminho padrão relativo ao pacote rag/
            index_dir = os.path.join(os.path.dirname(__file__), "index")
        _retriever = Retriever.load(index_dir)
    return _retriever
