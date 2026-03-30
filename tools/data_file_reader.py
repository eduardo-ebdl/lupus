"""Tool utilitária: leitura e análise de arquivos de dados no repositório.

Suporta CSV e JSON com stdlib (sem dependências extras).
Suporta Parquet e Excel com pandas (opcional — instalar separado).
Funciona com qualquer repositório configurado via PROJECT_PATH.
"""

import csv
import json
import os

from langchain.tools import tool


def _get_project_root() -> str:
    """Retorna o root do projeto via ctx_manager (fonte centralizada)."""
    from core.context_manager import get_project_path
    return get_project_path()


def _safe_path(project_root: str, file_path: str) -> tuple[str, str | None]:
    """Resolve e valida que o caminho está dentro do projeto."""
    full_path = os.path.normpath(os.path.join(project_root, file_path))
    norm_root = os.path.normpath(project_root)
    try:
        if os.path.commonpath([full_path, norm_root]) != norm_root:
            return "", "Caminho fora do diretório permitido."
    except ValueError:
        return "", "Caminho fora do diretório permitido."
    if os.path.islink(full_path):
        return "", "Symlinks não são permitidos."
    if not os.path.isfile(full_path):
        return "", f"Arquivo não encontrado: {file_path}"
    return full_path, None


def _infer_type(value: str) -> str:
    """Infere tipo Python a partir de um valor string."""
    if value.strip() in ("", "null", "NULL", "None", "NA", "N/A", "nan", "NaN"):
        return "null"
    if value.lower() in ("true", "false"):
        return "boolean"
    try:
        # Verifica int primeiro, mas descarta se float() daria resultado diferente
        # (ex: "1e5" é float, não int)
        int_val = int(value)
        if str(int_val) == value.strip():
            return "integer"
    except ValueError:
        pass
    try:
        float(value)
        return "float"
    except ValueError:
        pass
    return "string"


def _read_csv(full_path: str, max_rows: int) -> dict:
    rows = []
    type_samples: dict[str, list[str]] = {}
    total_rows = 0

    with open(full_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []

        for i, row in enumerate(reader):
            total_rows = i + 1
            if i < max_rows:
                rows.append(dict(row))
            for col, val in row.items():
                if col not in type_samples:
                    type_samples[col] = []
                if len(type_samples[col]) < 30:
                    type_samples[col].append(_infer_type(str(val)))
            # Para schema, não precisa ler o arquivo inteiro
            if i >= max_rows and all(len(s) >= 30 for s in type_samples.values()):
                break

    schema = []
    for col in fieldnames:
        samples = type_samples.get(col, [])
        non_null = [t for t in samples if t != "null"]
        dominant = max(set(non_null), key=non_null.count) if non_null else "null"
        null_pct = round(samples.count("null") / len(samples) * 100, 1) if samples else 0.0
        schema.append({"column": col, "type": dominant, "null_pct_sample": null_pct})

    return {
        "format": "csv",
        "total_rows": total_rows,
        "total_columns": len(fieldnames),
        "schema": schema,
        "sample_rows": rows,
    }


def _read_json(full_path: str, max_rows: int) -> dict:
    with open(full_path, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        schema: dict[str, str] = {}
        for item in data[:50]:
            if isinstance(item, dict):
                for k, v in item.items():
                    if k not in schema:
                        schema[k] = type(v).__name__
        return {
            "format": "json",
            "structure": "array",
            "total_records": len(data),
            "schema": schema,
            "sample_records": data[:max_rows],
        }
    elif isinstance(data, dict):
        return {
            "format": "json",
            "structure": "object",
            "total_keys": len(data),
            "keys": list(data.keys()),
            "preview": {k: str(v)[:300] for k, v in list(data.items())[:10]},
        }
    else:
        return {
            "format": "json",
            "structure": type(data).__name__,
            "value_preview": str(data)[:500],
        }


def _read_with_pandas(full_path: str, ext: str, max_rows: int) -> dict:
    try:
        import pandas as pd  # type: ignore
    except ImportError:
        return {
            "error": f"pandas não instalado. Execute: pip install pandas",
            "hint": "Arquivos CSV e JSON funcionam sem dependências extras.",
        }

    try:
        if ext == ".parquet":
            df = pd.read_parquet(full_path)
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(full_path)
        else:
            return {"error": f"Extensão não suportada via pandas: {ext}"}
    except Exception as e:
        return {"error": f"Erro ao ler com pandas: {e}"}

    schema = [
        {
            "column": col,
            "type": str(df[col].dtype),
            "null_count": int(df[col].isna().sum()),
            "unique_count": int(df[col].nunique()),
        }
        for col in df.columns
    ]

    return {
        "format": ext.lstrip("."),
        "total_rows": len(df),
        "total_columns": len(df.columns),
        "schema": schema,
        "sample_rows": df.head(max_rows).fillna("").to_dict(orient="records"),
    }


@tool
def read_data_file(file_path: str, max_rows: int = 50) -> str:
    """Lê um arquivo de dados do repositório e retorna schema, amostra e estatísticas.

    Suporta CSV e JSON (sem dependências extras). Parquet e Excel requerem pandas.
    Retorna: schema com tipos por coluna, amostra de linhas e contagem de registros.

    Use quando o repositório incluir datasets locais (CSV, JSON, Parquet) e o
    usuário quiser entender a estrutura dos dados, colunas disponíveis ou conteúdo.

    Limitação: não acessa dados em bancos externos ou cloud — apenas arquivos
    presentes fisicamente no repositório.

    Args:
        file_path: Caminho relativo do arquivo dentro do repositório
                   (ex: 'data/bronze/casos.csv', 'datasets/treino.json')
        max_rows: Número máximo de linhas na amostra retornada (padrão: 50)
    """
    max_rows = max(1, min(max_rows, 10_000))
    project_root = _get_project_root()
    full_path, err = _safe_path(project_root, file_path)
    if err:
        return json.dumps({"error": err}, ensure_ascii=False)

    ext = os.path.splitext(file_path)[1].lower()
    file_size_kb = round(os.path.getsize(full_path) / 1024, 1)

    try:
        if ext == ".csv":
            result = _read_csv(full_path, max_rows)
        elif ext == ".json":
            result = _read_json(full_path, max_rows)
        elif ext in (".parquet", ".xlsx", ".xls"):
            result = _read_with_pandas(full_path, ext, max_rows)
        else:
            return json.dumps({
                "error": f"Formato '{ext}' não suportado.",
                "supported": [".csv", ".json", ".parquet", ".xlsx", ".xls"],
            }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Erro ao ler '{file_path}': {e}"}, ensure_ascii=False)

    result["file_path"] = file_path
    result["file_size_kb"] = file_size_kb
    return json.dumps(result, ensure_ascii=False, indent=2, default=str)
