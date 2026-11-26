"""Read numbered passages from the knowledge base."""

import json
from pathlib import Path


def load_kb(directory):
    """Return a mapping from passage IDs to their section bodies."""
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError(f"知识库目录不存在：{directory}")
    passages = {}
    for document in sorted(directory.glob("*.md")):
        number = 0
        body = []
        for line in document.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                if number:
                    passages[f"{document.stem}#{number}"] = "\n".join(body).strip()
                number += 1
                body = []
            elif number:
                body.append(line)
        if number:
            passages[f"{document.stem}#{number}"] = "\n".join(body).strip()
    return passages


def load_synonyms(directory):
    """Return the optional alias-to-canonical phrase table for fact checks."""
    path = Path(directory) / "synonyms.json"
    try:
        synonyms = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(synonyms, dict) or any(
        not alias.strip() or not isinstance(phrase, str) or not phrase.strip()
        for alias, phrase in synonyms.items()
    ):
        raise ValueError("synonyms.json 必须把非空别名映射到非空短语")
    return synonyms
