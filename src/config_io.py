# -*- coding: utf-8 -*-
"""配置读写，供 GUI 与 main 共用。"""
from pathlib import Path


def get_config_dir() -> Path:
    base = Path(__file__).resolve().parent
    return base.parent / "config"


def load_yaml(path: Path) -> dict:
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"load config error {path}: {e}")
        return {}


def save_yaml(path: Path, data: dict) -> None:
    import yaml
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
