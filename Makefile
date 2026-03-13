# StewardOS Monorepo — test & lint orchestration
# Each server/agent runs tests in its own venv via uv.

SHELL := /bin/bash

# ── Per-project test ─────────────────────────────────────────────────────────
# Usage: make test-server NAME=health-graph-mcp
test-server:
	@test -n "$(NAME)" || (echo "Usage: make test-server NAME=<server-dir>" && exit 1)
	@if [ -d "servers/$(NAME)/tests" ]; then \
		echo "=== Testing servers/$(NAME) ==="; \
		cd servers/$(NAME) && uv run --extra dev pytest tests/ -v; \
	elif [ -d "agents/$(NAME)/tests" ]; then \
		echo "=== Testing agents/$(NAME) ==="; \
		cd agents/$(NAME) && uv run --extra dev pytest tests/ -v; \
	else \
		echo "No tests/ directory found for $(NAME)"; exit 1; \
	fi

# Projects excluded from test-all (need credentials or external services)
SKIP_PROJECTS := servers/google-workspace-mcp servers/investing-workspace/market-intel-direct

# ── Test all projects that have tests/ ───────────────────────────────────────
test-all:
	@failed=0; \
	for d in $$(find servers agents -maxdepth 3 -name tests -type d | sort); do \
		project=$$(dirname "$$d"); \
		skip=0; \
		for s in $(SKIP_PROJECTS); do \
			[ "$$project" = "$$s" ] && skip=1; \
		done; \
		[ $$skip -eq 1 ] && echo "" && echo "=== Skipping $$project (needs credentials) ===" && continue; \
		echo ""; echo "=== Testing $$project ==="; \
		(cd "$$project" && uv run --extra dev pytest tests/ -v) || failed=$$((failed + 1)); \
	done; \
	echo ""; \
	if [ $$failed -gt 0 ]; then \
		echo "FAIL: $$failed project(s) had test failures"; exit 1; \
	else \
		echo "PASS: All projects passed"; \
	fi

# ── Lint ─────────────────────────────────────────────────────────────────────
lint:
	ruff check servers/ agents/ scripts/

# ── Skill-to-tool contract verification ──────────────────────────────────────
verify-skills:
	python3 scripts/verify_skill_tool_refs.py

.PHONY: test-server test-all lint verify-skills
