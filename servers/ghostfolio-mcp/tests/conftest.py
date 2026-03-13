from __future__ import annotations

import sys
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
LIB_ROOT = REPO_ROOT / "servers" / "lib"

for path in (SERVER_ROOT, REPO_ROOT, LIB_ROOT):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
