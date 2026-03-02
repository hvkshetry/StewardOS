#!/usr/bin/env python3
"""Compatibility wrapper: delegate to household-comptroller canonical script."""

from __future__ import annotations

from pathlib import Path
import runpy

TARGET = (
    Path(__file__).resolve().parents[2]
    / "household-comptroller"
    / "scripts"
    / "build_ingestion_payload.py"
)

if not TARGET.exists():
    raise SystemExit(f"Canonical script missing: {TARGET}")

runpy.run_path(str(TARGET), run_name="__main__")
