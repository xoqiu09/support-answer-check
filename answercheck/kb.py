"""Read numbered passages from the knowledge base."""

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
