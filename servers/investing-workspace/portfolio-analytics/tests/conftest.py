"""Shared test infrastructure for portfolio-analytics tests."""

import sys
from pathlib import Path

server_root = str(Path(__file__).resolve().parents[1])
if server_root not in sys.path:
    sys.path.insert(0, server_root)
