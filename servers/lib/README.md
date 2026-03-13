# stewardos-lib

Shared domain library for StewardOS MCP servers. Extracted from duplicated code across `estate-planning-mcp` and `finance-graph-mcp`.

## Modules

| Module | Contents |
|--------|----------|
| `db.py` | `row_to_dict()`, `rows_to_dicts()`, `float_or_none()` — asyncpg Record serialization with UUID, Decimal-as-number, date, and JSON handling |
| `constants.py` | `ASSET_TYPE_BY_CLASS`, `REAL_ESTATE_SUBCLASSES`, `OCF_MINIMAL_SCHEMA`, `ISO_CURRENCY_RE`, `canonical_asset_type()` |
| `json_utils.py` | `coerce_json_input()`, `extract_numeric_value()` — LLM-friendly JSON coercion |
| `domain_ops.py` | `insert_valuation_observation()`, `list_entities_query()`, `get_ownership_graph_query()`, `normalize_currency_code()`, `parse_iso_date()` |

## Usage

Consuming servers add a local path dependency in `pyproject.toml`:

```toml
[project]
dependencies = ["stewardos-lib"]

[tool.uv.sources]
stewardos-lib = { path = "../../servers/lib", editable = true }
```

Then import:

```python
from stewardos_lib.db import row_to_dict, rows_to_dicts
from stewardos_lib.constants import canonical_asset_type
from stewardos_lib.domain_ops import insert_valuation_observation
```

## Tests

```bash
cd servers/lib && uv run --extra dev pytest tests/ -v
```

## Conventions

- All `domain_ops` functions accept an `asyncpg.Pool` and return raw `asyncpg.Record(s)`. Callers handle serialization via `db.row_to_dict()`.
- `row_to_dict()` emits `Decimal` values as numeric JSON values so downstream MCP payloads have stable numeric typing.
- Currency codes are normalized to uppercase ISO-4217 via `normalize_currency_code()`.
- Pure-logic helpers go in `constants.py` or `json_utils.py`; anything touching the database goes in `domain_ops.py`.
