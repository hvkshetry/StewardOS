#!/usr/bin/env python3
"""Verify that every tool reference in SKILL.md files resolves to a real tool
registered in the corresponding MCP server.

Usage:
    python scripts/verify_skill_tool_refs.py [--verbose]

Exit code 0 = all references valid, 1 = mismatches found.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# ── Server resolution map ────────────────────────────────────────────────────
# Maps the server prefix used in skills (e.g. "household-tax") to the server
# paths and the registration pattern to use for extracting tool names.

SERVER_MAP: dict[str, dict] = {
    "actual-budget": {
        "paths": ["servers/actual-mcp/src/tools/consolidated.ts"],
        "pattern": "ts_schema_name",
    },
    "finance-graph": {
        "paths": ["servers/finance-graph-mcp"],
        "pattern": "py_decorator_recursive",
    },
    "estate-planning": {
        "paths": ["servers/estate-planning-mcp"],
        "pattern": "py_decorator_recursive",
    },
    "household-tax": {
        "paths": ["servers/household-tax-mcp"],
        "pattern": "py_decorator_recursive",
    },
    "portfolio-analytics": {
        "paths": ["servers/investing-workspace/portfolio-analytics"],
        "pattern": "py_decorator_recursive",
    },
    "market-intel-direct": {
        "paths": ["servers/investing-workspace/market-intel-direct"],
        "pattern": "py_decorator_recursive",
    },
    "policy-events": {
        "paths": ["servers/investing-workspace/policy-events"],
        "pattern": "py_decorator_recursive",
    },
    "sec-edgar": {
        "paths": ["servers/investing-workspace/sec-edgar/consolidated_server.py"],
        "pattern": "py_decorator",
    },
    "ghostfolio": {
        "paths": ["servers/ghostfolio-mcp"],
        "pattern": "py_decorator_recursive",
    },
    "paperless": {
        "paths": ["servers/paperless-mcp/src/tools"],
        "pattern": "ts_server_tool",
    },
    "google-workspace": {
        "paths": ["servers/google-workspace-mcp"],
        "pattern": "py_decorator_recursive",
    },
    "memos": {
        "paths": ["servers/memos-mcp/server.py"],
        "pattern": "py_decorator",
    },
    "homebox": {
        "paths": ["servers/homebox-mcp/server.py"],
        "pattern": "py_decorator",
    },
    "grocy": {
        "paths": ["servers/grocy-mcp/server.py"],
        "pattern": "py_decorator",
    },
    "mealie": {
        "paths": ["servers/mealie-mcp/src/tools"],
        "pattern": "py_decorator_recursive",
    },
    "wger": {
        "paths": ["servers/wger-mcp/server.py"],
        "pattern": "py_decorator",
    },
    "health-graph": {
        "paths": ["servers/health-graph-mcp"],
        "pattern": "py_decorator_recursive",
    },
    "family-edu": {
        "paths": ["servers/family-edu-mcp"],
        "pattern": "py_decorator_recursive",
    },
}

# Server aliases — some skills reference alternative config names
SERVER_ALIASES: dict[str, str] = {
    "google-workspace-personal-ro": "google-workspace",
}

# Servers that are external/upstream and should not be validated
EXTERNAL_SERVERS = {
    "office-mcp",
    "oura",
    "apple-health",
    "openbb-curated",
    "knowledge-base",
    "openproject-mcp",
    "twenty-mcp",
    "medical",
    "us-legal",
}


# ── Tool extraction functions ─────────────────────────────────────────────────

def extract_py_decorator_tools(filepath: Path) -> set[str]:
    """Extract tool names from Python @mcp.tool() / @server.tool() decorated functions."""
    tools: set[str] = set()
    if not filepath.exists():
        return tools
    text = filepath.read_text()
    # Match: @mcp.tool() or @server.tool() followed (possibly with intermediate
    # decorators) by async def name or def name.  Allow up to 5 lines of other
    # decorators between the tool decorator and the def line.
    for m in re.finditer(
        r"@(?:mcp|server)\.tool\(\).*\n(?:\s*@\w[\w.]*\(.*\).*\n)*\s*(?:async\s+)?def\s+(\w+)",
        text,
    ):
        tools.add(m.group(1))
    # Also match dynamic registration: mcp.tool()(func_name) / server.tool()(func_name)
    for m in re.finditer(
        r"(?:mcp|server)\.tool\(\)\((\w+)\)",
        text,
    ):
        tools.add(m.group(1))
    # Match make_enveloped_tool alias pattern:
    #   _tool = make_enveloped_tool(mcp)   or   _tool = _make_enveloped_tool(mcp)
    #   @_tool
    #   async def tool_name(...):
    alias_names: set[str] = set()
    for m in re.finditer(
        r"(\w+)\s*=\s*_?make_enveloped_tool\(", text
    ):
        alias_names.add(m.group(1))
    if alias_names:
        alias_alt = "|".join(re.escape(a) for a in alias_names)
        for m in re.finditer(
            rf"@(?:{alias_alt})\s*\n\s*(?:async\s+)?def\s+(\w+)",
            text,
        ):
            tools.add(m.group(1))
    return tools


SKIP_DIRS = {".venv", "__pycache__", "node_modules", ".git", "tests"}


def extract_py_decorator_tools_recursive(dirpath: Path) -> set[str]:
    """Extract tool names from all Python files in a directory tree."""
    tools: set[str] = set()
    if not dirpath.exists():
        return tools
    for pyfile in dirpath.rglob("*.py"):
        if any(part in SKIP_DIRS for part in pyfile.parts):
            continue
        tools |= extract_py_decorator_tools(pyfile)
    return tools


def extract_ts_server_tool(dirpath: Path) -> set[str]:
    """Extract tool names from TypeScript server.tool("name", ...) calls."""
    tools: set[str] = set()
    target = dirpath if dirpath.is_dir() else dirpath.parent
    for tsfile in target.rglob("*.ts"):
        text = tsfile.read_text()
        for m in re.finditer(r'server\.tool\(\s*["\'](\w+)["\']', text):
            tools.add(m.group(1))
    return tools


def extract_ts_schema_name(filepath: Path) -> set[str]:
    """Extract tool names from TypeScript schema objects with name: field."""
    tools: set[str] = set()
    if not filepath.exists():
        return tools
    text = filepath.read_text()
    for m in re.finditer(r'name:\s*["\'](\w+)["\']', text):
        tools.add(m.group(1))
    return tools


def get_server_tools(server_name: str) -> set[str] | None:
    """Return the set of registered tool names for a server, or None if unknown."""
    if server_name in EXTERNAL_SERVERS:
        return None  # skip validation
    cfg = SERVER_MAP.get(server_name)
    if cfg is None:
        return None
    tools: set[str] = set()
    for rel_path in cfg["paths"]:
        full = REPO_ROOT / rel_path
        pattern = cfg["pattern"]
        if pattern == "py_decorator":
            tools |= extract_py_decorator_tools(full)
        elif pattern == "py_decorator_recursive":
            if full.is_dir():
                tools |= extract_py_decorator_tools_recursive(full)
            else:
                tools |= extract_py_decorator_tools(full)
        elif pattern == "ts_server_tool":
            tools |= extract_ts_server_tool(full)
        elif pattern == "ts_schema_name":
            tools |= extract_ts_schema_name(full)
    return tools


# ── Skill reference extraction ────────────────────────────────────────────────

# Matches patterns like:
#   `server-name.tool_name`
#   `server-name.tool_name(args)`
#   server-name.tool_name (without backticks, in tool map sections)
# Requires the server part to start with a letter (filters out numbers like 2.5)
TOOL_REF_PATTERN = re.compile(
    r"`?([a-zA-Z][\w-]*)\.([\w]+)(?:\([^)]*\))?`?"
)


def extract_skill_refs(filepath: Path) -> list[tuple[int, str, str]]:
    """Extract (line_number, server, tool) tuples from a SKILL.md file."""
    refs: list[tuple[int, str, str]] = []
    text = filepath.read_text()
    for lineno, line in enumerate(text.splitlines(), 1):
        # Skip YAML frontmatter
        if lineno <= 5 and (line.startswith("---") or line.startswith("name:") or line.startswith("description:")):
            continue
        for m in TOOL_REF_PATTERN.finditer(line):
            server = m.group(1)
            tool = m.group(2)
            # Filter out false positives
            if server in (
                "e", "g", "http", "https", "www", "eg", "i", "ex",
                "memory", "context", "config", "src", "skills",
                "risk", "illiquid_overlay", "vol_regime",
                "risk_decomposition", "risk_data_integrity",
                "most_recent_observation",
            ):
                continue
            # Filter out template placeholders like X.XX, XX.X
            if re.fullmatch(r"[Xx]+", server):
                continue
            # Filter out file extensions and paths (e.g., scan_001.pdf, AGENTS.md)
            if re.match(r".*\.(md|pdf|jpg|png|html|json|yaml|yml|ts|py|js|css)$",
                        f"{server}.{tool}", re.IGNORECASE):
                continue
            # Filter out file path patterns
            if "/" in line[max(0, m.start() - 5):m.start()]:
                continue
            refs.append((lineno, server, tool))
    return refs


# ── Main validation ──────────────────────────────────────────────────────────

def main() -> int:
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    skills_dir = REPO_ROOT / "skills"
    if not skills_dir.exists():
        print(f"ERROR: skills directory not found at {skills_dir}")
        return 1

    # Cache server tool sets
    tool_cache: dict[str, set[str] | None] = {}

    mismatches: list[tuple[str, int, str, str, str]] = []
    checked = 0
    skipped_external = 0
    skipped_unknown = 0

    for skill_file in sorted(skills_dir.rglob("SKILL.md")):
        refs = extract_skill_refs(skill_file)
        rel_path = skill_file.relative_to(REPO_ROOT)

        for lineno, server, tool in refs:
            # Resolve aliases
            server = SERVER_ALIASES.get(server, server)

            if server in EXTERNAL_SERVERS:
                skipped_external += 1
                continue

            if server not in SERVER_MAP:
                # Could be a false positive or an unknown server
                skipped_unknown += 1
                if verbose:
                    print(f"  SKIP {rel_path}:{lineno}  {server}.{tool} (unknown server)")
                continue

            if server not in tool_cache:
                tool_cache[server] = get_server_tools(server)

            server_tools = tool_cache[server]
            if server_tools is None:
                skipped_external += 1
                continue

            checked += 1
            if tool not in server_tools:
                mismatches.append((str(rel_path), lineno, server, tool, "not found"))

    # Report
    print(f"Skill-to-tool contract verification")
    print(f"  Checked:          {checked} references")
    print(f"  External (skip):  {skipped_external}")
    print(f"  Unknown (skip):   {skipped_unknown}")
    print()

    if mismatches:
        print(f"FAIL: {len(mismatches)} mismatch(es) found:\n")
        for path, lineno, server, tool, reason in mismatches:
            registered = tool_cache.get(server)
            print(f"  {path}:{lineno}")
            print(f"    Reference:  {server}.{tool}")
            print(f"    Reason:     {reason}")
            if registered and verbose:
                # Suggest closest match
                candidates = sorted(registered, key=lambda t: _edit_distance(tool, t))[:3]
                print(f"    Did you mean: {', '.join(candidates)}")
            print()
        return 1
    else:
        print("PASS: All skill tool references resolve to registered server tools.")
        return 0


def _edit_distance(a: str, b: str) -> int:
    """Simple Levenshtein distance for suggesting corrections."""
    if len(a) < len(b):
        return _edit_distance(b, a)
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (ca != cb)))
        prev = curr
    return prev[len(b)]


if __name__ == "__main__":
    sys.exit(main())
