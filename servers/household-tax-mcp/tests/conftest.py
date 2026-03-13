"""Shared test infrastructure for household-tax-mcp tests."""

import sys
from pathlib import Path

# Add the server and repo roots so local modules and shared test helpers import cleanly.
server_root = str(Path(__file__).resolve().parents[1])
if server_root not in sys.path:
    sys.path.insert(0, server_root)

repo_root = str(Path(__file__).resolve().parents[3])
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
