import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"


def _load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    if not path.exists():
        example_path = CONFIG_DIR / f"{Path(name).stem}.example.yaml"
        if example_path.exists():
            import shutil
            shutil.copyfile(example_path, path)
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raise SystemExit(f"Missing config file: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@dataclass
class Settings:
    profile: dict
    search: dict
    llm_provider: str
    outreach: dict

    @property
    def resume_path(self) -> Path:
        return ROOT / self.profile.get("resume_path", "resume/resume.pdf")


def load_settings(profile_name: str | None = None) -> Settings:
    load_dotenv(CONFIG_DIR / ".env")
    DATA_DIR.mkdir(exist_ok=True)
    target = profile_name or os.getenv("ACTIVE_PROFILE", "").strip()
    if target:
        prof_file = f"profile_{target}.yaml" if (CONFIG_DIR / f"profile_{target}.yaml").exists() else "profile.yaml"
        search_file = f"search_{target}.yaml" if (CONFIG_DIR / f"search_{target}.yaml").exists() else "search.yaml"
    else:
        prof_file = "profile.yaml"
        search_file = "search.yaml"
    return Settings(
        profile=_load_yaml(prof_file),
        search=_load_yaml(search_file),
        llm_provider=os.getenv("LLM_PROVIDER", "none").strip().lower(),
        outreach=_load_yaml("outreach.yaml") if (CONFIG_DIR / "outreach.yaml").exists() else {"enabled": False},
    )
