from __future__ import annotations

import sys
from pathlib import Path

agent_root = str(Path(__file__).resolve().parents[1])
repo_root = str(Path(__file__).resolve().parents[3])

for path in (agent_root, repo_root):
    if path not in sys.path:
        sys.path.insert(0, path)
