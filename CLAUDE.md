# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**BirdEye-SQL** is a bidirectional SQL ↔ AST engine for MSSQL with semantic analysis and Zero Trust Architecture (ZTA) enforcement. It parses SQL into an AST, performs type inference and semantic validation, and can reconstruct SQL from the AST JSON.

## Commands

### Setup
```bash
python -m venv .venv
pip install -r requirements.txt
```

### Run Tests
```bash
# All tests (must set PYTHONPATH)
PYTHONPATH=. pytest tests/

# Single suite
PYTHONPATH=. pytest tests/test_dml_suite.py -v

# Single test
PYTHONPATH=. pytest tests/test_dml_suite.py::test_insert_basic -v

# Collect without running (verify test discovery)
PYTHONPATH=. pytest --collect-only -q
```

### Web UI
```bash
python web/app.py   # http://127.0.0.1:5000
```

### CLI
```bash
# SQL → AST
python main.py --sql "SELECT * FROM Address" --format tree
python main.py --sql "SELECT * FROM Address" --format all   # tree + mermaid + json

# AST JSON → SQL
python main.py --ast '{"node_type":"SelectStatement",...}'
python main.py --ast-file ast.json

# With custom schema metadata
python main.py --file query.sql --csv data/output.csv --format json
```

## Architecture

The core pipeline: **Lexer → Parser → Binder → Visualizer/Serializer**, orchestrated by `BirdEyeRunner` in `birdeye/runner.py`.

### Core Modules (`birdeye/`)

| Module | Role |
|--------|------|
| `lexer.py` | Tokenizes SQL into 80+ token types; handles bracket-escaped identifiers `[Name]`, N-strings, bitwise/modulo operators |
| `parser.py` | Recursive descent parser; converts tokens to AST nodes; handles all MSSQL-specific syntax (APPLY, CTEs, DECLARE, OFFSET/FETCH, etc.) |
| `binder.py` | Semantic analysis: type inference, ZTA enforcement, scope management, NULL propagation, aggregate validation |
| `ast.py` | AST node dataclasses (`SelectStatement`, `JoinNode`, `BinaryExpressionNode`, `CastExpressionNode`, etc.) |
| `registry.py` | `MetadataRegistry` — central source of truth for table schemas and 60+ built-in function metadata; loads from CSV |
| `visualizer.py` | AST → text tree with type annotations |
| `serializer.py` | AST → JSON |
| `reconstructor.py` | JSON → SQL (enables round-trip) |
| `mermaid_exporter.py` | AST → Mermaid flowchart |
| `runner.py` | Pipeline orchestrator; `run(sql)` returns tree/json/mermaid; `run_script(sql)` handles GO batch separators |

### Web API (`web/app.py`)
- `POST /api/parse` — SQL → AST outputs (tree, mermaid, json)
- `POST /api/reconstruct` — AST JSON → SQL
- `POST /api/upload_csv` — hot-load custom schema metadata
- `GET /` — web dashboard

### Test Suite (`tests/`)
Session-scoped `global_runner` fixture in `conftest.py` pre-loads AdventureWorks metadata from `data/output.csv`. All suites use this shared fixture for performance.

### Schema Metadata (`data/output.csv`)
CSV with columns `table_name,column_name,data_type` — uses AdventureWorks tables. Loaded at runtime by `MetadataRegistry`.

## Key Design Patterns

- **Zero Trust Architecture (ZTA)**: Binder enforces strict type compatibility, alias policy (original table name invalidated after alias), column ambiguity prevention in JOINs, and function sandboxing (whitelist; restricted functions like `xp_cmdshell` blocked).
- **Scope Stack**: Multi-level scope for CTEs, subqueries, and derived tables tracked in binder.
- **Type Inference**: Propagated bottom-up through the expression tree; all `ExpressionNode`s carry an `inferred_type` after binding.
- **Round-trip**: SQL → Serializer JSON → Reconstructor → SQL is a first-class feature; test suite `test_reconstructor_suite.py` validates this.
- **GO batch handling**: `run_script()` splits on `GO` tokens and shares binder state (temp tables, DECLARE vars) across batches.
