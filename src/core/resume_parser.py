import hashlib
from pathlib import Path

from pypdf import PdfReader

from src.config import DATA_DIR


def load_resume_text(path: Path) -> str:
    """PDF -> text, cached in data/resume_<hash>.txt until the PDF changes."""
    if not path.exists():
        print(f"[warn] Resume not found at {path} — LLM answers will use profile.yaml only.")
        return ""
    h = hashlib.md5(str(path.resolve()).encode("utf-8")).hexdigest()[:8]
    cache = DATA_DIR / f"resume_{h}.txt"
    if cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
        return cache.read_text(encoding="utf-8")
    text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages).strip()
    cache.write_text(text, encoding="utf-8")
    return text
