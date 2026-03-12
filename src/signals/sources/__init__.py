# -*- coding: utf-8 -*-
"""信号源包：自动导入所有信号源模块以触发 @register_source 注册。"""
from pathlib import Path
import importlib

from .registry import create_source, list_source_types, register_source  # noqa: F401

# 自动导入当前目录下所有 .py 模块（排除 __init__ 和 registry）
_pkg_dir = Path(__file__).parent
for _f in _pkg_dir.glob("*.py"):
    _name = _f.stem
    if _name.startswith("_") or _name == "registry":
        continue
    importlib.import_module(f".{_name}", package=__name__)
