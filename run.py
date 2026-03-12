# -*- coding: utf-8 -*-
"""项目根目录运行入口。"""
import sys
from pathlib import Path

# 将项目根目录加入 path，便于 import src
_root = Path(__file__).resolve().parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.main import main

if __name__ == "__main__":
    main()
