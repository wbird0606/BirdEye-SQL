# 🦅 BirdEye-SQL: Semantic-Aware & Zero-Trust SQL Parser

[![Testing: pytest](https://img.shields.io/badge/Testing-pytest-blue.svg)](https://docs.pytest.org/)
[![Tests](https://img.shields.io/badge/Tests-533%20passed-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

🌍 **Language Switch / 語言切換**: [English](#english-version) | [繁體中文](#繁體中文版本)

---

<a id="english-version"></a>
# 🇬🇧 English Version

## 📖 Overview
**BirdEye-SQL** is a high-performance **bidirectional SQL ↔ AST** (Abstract Syntax Tree) engine specifically designed for **MSSQL** environments. Unlike traditional syntactic parsers, BirdEye-SQL features **Semantic Awareness**, allowing it to validate queries against real database metadata in a **Zero Trust Architecture (ZTA)** context. It acts as a security gatekeeper, intercepting malicious or ambiguous queries before they reach the database engine. The engine also supports the **reverse direction**: reconstructing valid SQL from an AST JSON, enabling round-trip transformations and query rewriting workflows.

## 🚀 Getting Started

### Environment Setup
Ensure you have Python 3.10+ installed, then run:
```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### Web UI Dashboard
BirdEye-SQL features a modern, Flask-based Web UI that supports dynamic CSV metadata loading, real-time type inference, and interactive Mermaid flowchart rendering (with Pan/Zoom and PNG/SVG downloads).
```powershell
python web/app.py
```
Open your browser and navigate to `http://127.0.0.1:5000`!

**REST API Endpoints:**
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/parse` | SQL → AST: parse SQL and return `tree`, `mermaid`, `json` |
| `POST` | `/api/reconstruct` | AST → SQL: accepts `{"ast": <dict or JSON string>}`, returns reconstructed SQL |
| `POST` | `/api/upload_csv` | Upload a CSV metadata file to update the schema context |

### CLI Utility
You can also use the parser directly from the terminal:
```powershell
# SQL → AST: parse SQL and output an AST tree
python main.py --sql "SELECT * FROM Address" --format tree

# SQL → AST: parse from a file, use custom metadata, and output Mermaid syntax
python main.py --file my_query.sql --csv custom_schema.csv --format mermaid

# AST → SQL: reconstruct SQL from an AST JSON string
python main.py --ast '{"node_type": "SelectStatement", ...}'

# AST → SQL: reconstruct SQL from an AST JSON file
python main.py --ast-file my_ast.json
```

## ✨ Key Features

### 🛡️ ZTA Security Enforcement
* **Strict Type Inference**: A robust type inference engine supporting implicit casting (e.g., `DATETIME` vs `NVARCHAR`) and User-Defined Types (UDT). It blocks illegal operations like comparing incompatible types.
* **Strict Alias Policy**: Once a table alias is defined, the original table name is invalidated to prevent semantic shadowing attacks.
* **Ambiguity Defense**: Mandatory qualifiers in JOIN environments to prevent "Column Ambiguity Attacks".
* **Function Sandbox**: Implements a "Deny-by-Default" whitelist for database functions. Prevents execution of dangerous system functions like `xp_cmdshell`.

### ⚙️ Engine Capabilities
* **Full Pipeline Integration**: The `BirdEyeRunner` seamlessly connects the Lexer, Parser, Binder, and Visualizer. The `ASTReconstructor` provides the reverse direction: AST JSON → SQL.
* **Bidirectional Transformation**: Round-trip SQL → AST JSON → SQL is fully supported, enabling query rewriting, AST manipulation, and programmatic SQL generation.
* **Comprehensive Expression Engine**: Arithmetic (`+`, `-`, `*`, `/`, `%`), bitwise (`&`, `|`, `^`, `~`), logical (`AND`, `OR`, `IS NULL`, `BETWEEN`), comparison (`IN`, `NOT IN`, `EXISTS`, `NOT EXISTS`, `LIKE`), and nested `CASE WHEN` logic.
* **Star Expansion**: Automatically expands `SELECT *` or `Table.*` into explicit column lists using metadata.
* **MSSQL-Specific Syntax**: `TOP N [PERCENT]`, `OFFSET/FETCH`, `DECLARE @var`, `SELECT INTO #temp`, `CROSS/OUTER APPLY`, `WITH (CTE)`.

### 📐 Supported SQL Features

| Category | Features |
|---|---|
| **SELECT** | DISTINCT, TOP N / TOP N PERCENT, OFFSET/FETCH, INTO #temp |
| **JOIN** | INNER, LEFT, RIGHT, FULL OUTER, CROSS JOIN, JOIN subquery |
| **APPLY** | CROSS APPLY, OUTER APPLY |
| **Set Ops** | UNION, UNION ALL, INTERSECT, EXCEPT |
| **Subqueries** | Scalar, correlated, derived tables, ANY/ALL |
| **DML** | INSERT (single/multi-row/SELECT), UPDATE, DELETE, TRUNCATE |
| **CTE** | Single, multiple, WITH + DML (UPDATE/DELETE) |
| **Expressions** | CASE WHEN, BETWEEN, CAST(x AS TYPE(len)), CONVERT(TYPE, x, style) |
| **Operators** | Arithmetic, bitwise, modulo, comparison, LIKE, IN/NOT IN |
| **Functions** | 60+ built-in: aggregates, string, numeric, date, NULL-handling |
| **MSSQL** | DECLARE @var, #temp / ##global temp tables, GO, BULK INSERT |

## 🧪 Testing Strategy (533 Tests Across 20 Suites)

We strictly adhere to **Test-Driven Development (TDD)**. Every feature follows a **Red → Green → Zero Regression** cycle. The project contains **533 comprehensive test cases** across **20 specialized test suites**:

| Test Suite | Tests | Coverage |
|---|---|---|
| `test_lexer_suite.py` | 16 | Tokenization, keywords, comments, bracket escaping, N'' prefix |
| `test_parser_suite.py` | 23 | Statement routing, AST construction, syntax error boundaries |
| `test_expressions_suite.py` | 31 | Arithmetic/bitwise/modulo, CASE WHEN, BETWEEN, CAST/CONVERT with length/style |
| `test_functions_suite.py` | 27 | 60+ built-in functions, function sandbox, aggregate integrity, COUNT(DISTINCT) |
| `test_select_features_suite.py` | 41 | DISTINCT, TOP/PERCENT, ORDER BY, GROUP BY/HAVING, OFFSET/FETCH, NULL literals |
| `test_dml_suite.py` | 39 | INSERT (single/multi-row/SELECT), UPDATE, DELETE, TRUNCATE, mandatory WHERE |
| `test_join_suite.py` | 33 | INNER/LEFT/RIGHT/FULL/CROSS JOIN, nullable propagation, multi-table chains |
| `test_subquery_suite.py` | 32 | Scalar, correlated, derived tables, UNION/INTERSECT/EXCEPT derived, ANY/ALL |
| `test_cte_suite.py` | 10 | Single/multiple CTEs, CTE + UPDATE/DELETE, CTE scope isolation |
| `test_semantic_suite.py` | 23 | ZTA enforcement, type safety, alias policy, scope stack, ambiguity detection |
| `test_mssql_features_suite.py` | 49 | DECLARE, #temp tables, CROSS/OUTER APPLY, advanced types (Geography, XML…) |
| `test_mssql_boundary_suite.py` | 42 | Edge cases: negative literals, global ##temp, operators, INTERSECT/EXCEPT, string functions |
| `test_integration_suite.py` | 23 | End-to-end pipeline with real AdventureWorks metadata, cross-feature integration |
| `test_window_functions_suite.py` | 22 | Window function syntax boundaries (expected-failure suite) |
| `test_visualizer_suite.py` | 39 | Tree rendering, Mermaid output, type annotation, all statement types |
| `test_serializer_suite.py` | 29 | JSON serialization of all AST node types, round-trip accuracy |
| `test_cli_suite.py` | 4 | CLI argument parsing, file I/O, output format validation |
| `test_web_api_suite.py` | 3 | RESTful endpoints, JSON response format, HTTP error codes |
| `test_mermaid_suite.py` | 3 | Mermaid flowchart generation and node structure |
| `test_reconstructor_suite.py` | 32 | AST JSON → SQL reconstruction, round-trip accuracy, all statement types |

**Current Status**: ✅ **100% Tests Passed** (533/533)
```powershell
pytest tests/
```

<br>
<hr>
<br>

<a id="繁體中文版本"></a>
# 🇹🇼 繁體中文版本

## 📖 專案概述
**BirdEye-SQL** 是一款專為 **MSSQL** 環境設計的高效能 **雙向 SQL ↔ AST**（抽象語法樹）引擎。不同於傳統的語法解析器，BirdEye-SQL 具備**語意覺知**功能，使其能在**零信任架構 (ZTA)** 背景下，根據真實的資料庫元數據驗證查詢語句。它作為資安守門員，在查詢進入資料庫引擎前，先行攔截具備惡意特徵或語意模糊的語句。引擎同時支援**反向轉換**：由 AST JSON 重建有效的 SQL 字串，實現往返轉換與查詢改寫工作流程。

## 🚀 快速開始

### 環境建置
請確保你已安裝 Python 3.10+，然後執行以下指令安裝必要套件：
```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### Web 視覺化儀表板
BirdEye-SQL 內建了一個基於 Flask 的現代化 Web UI，支援動態載入 CSV 元數據，並能即時渲染帶有型別推導的 AST Tree 與 Mermaid 流程圖（支援平移縮放與圖片下載）。
```powershell
python web/app.py
```
打開瀏覽器前往 `http://127.0.0.1:5000` 即可體驗！

**REST API 端點：**
| 方法 | 端點 | 說明 |
|---|---|---|
| `POST` | `/api/parse` | SQL → AST：解析 SQL，回傳 `tree`、`mermaid`、`json` |
| `POST` | `/api/reconstruct` | AST → SQL：接受 `{"ast": <dict 或 JSON 字串>}`，回傳重建後的 SQL |
| `POST` | `/api/upload_csv` | 上傳 CSV 元數據檔案以更新 schema 上下文 |

### 命令列工具 (CLI)
你也可以直接在終端機使用 CLI 工具：
```powershell
# SQL → AST：解析一段 SQL 並顯示樹狀圖
python main.py --sql "SELECT * FROM Address" --format tree

# SQL → AST：解析檔案並輸出 Mermaid 語法，同時指定自定義的元數據
python main.py --file my_query.sql --csv custom_schema.csv --format mermaid

# AST → SQL：由 AST JSON 字串重建 SQL
python main.py --ast '{"node_type": "SelectStatement", ...}'

# AST → SQL：由 AST JSON 檔案重建 SQL
python main.py --ast-file my_ast.json
```

## ✨ 核心功能

### 🛡️ 零信任資安強化 (ZTA)
* **嚴格型別推導**: 具備強大的型別推導與相容性檢查引擎，支援隱含轉型（如 `DATETIME` 與 `NVARCHAR`）及使用者定義類型 (UDT)，防堵不合法的賦值與比較。
* **嚴格別名規範**: 一旦定義了別名，原始表名即刻失效，防止語義陰影攻擊。
* **歧義防禦**: 在 JOIN 環境下強制要求限定符，防止「欄位歧義攻擊」。
* **函數沙箱**: 實作「預設拒絕」的函數白名單機制，攔截如 `xp_cmdshell` 等高風險系統函數。

### ⚙️ 引擎能力
* **全域流水線整合**: 提供 `BirdEyeRunner` 核心引擎，完美串接 Lexer → Parser → Binder → Visualizer 完整流水線。`ASTReconstructor` 提供反向轉換：AST JSON → SQL。
* **雙向轉換**: 完整支援 SQL → AST JSON → SQL 的往返轉換，實現查詢改寫、AST 操作與程式化 SQL 生成。
* **強大表達式引擎**: 算術運算（`+`, `-`, `*`, `/`, `%`）、位元運算（`&`, `|`, `^`, `~`）、邏輯條件（`AND`, `OR`, `IS NULL`, `BETWEEN`）、比較（`IN`, `NOT IN`, `EXISTS`, `LIKE`）與多層巢狀 `CASE WHEN` 的精確解析。
* **星號自動展開**: 利用元數據自動將 `SELECT *` 或 `Table.*` 展開為明確的實體欄位清單。
* **MSSQL 特有語法**: `TOP N [PERCENT]`、`OFFSET/FETCH`、`DECLARE @var`、`SELECT INTO #temp`、`CROSS/OUTER APPLY`、`WITH (CTE)`。

### 📐 支援的 SQL 語法

| 類別 | 功能 |
|---|---|
| **SELECT** | DISTINCT、TOP N / TOP N PERCENT、OFFSET/FETCH、INTO #temp |
| **JOIN** | INNER、LEFT、RIGHT、FULL OUTER、CROSS JOIN、子查詢 JOIN |
| **APPLY** | CROSS APPLY、OUTER APPLY |
| **集合運算** | UNION、UNION ALL、INTERSECT、EXCEPT |
| **子查詢** | 純量、關聯、衍生資料表、ANY/ALL |
| **DML** | INSERT（單列/多列/SELECT來源）、UPDATE、DELETE、TRUNCATE |
| **CTE** | 單一/多個 CTE、WITH + DML（UPDATE/DELETE） |
| **表達式** | CASE WHEN、BETWEEN、CAST(x AS TYPE(len))、CONVERT(TYPE, x, style) |
| **運算子** | 算術、位元、模數、比較、LIKE、IN/NOT IN |
| **函數** | 60+ 內建函數：聚合、字串、數值、日期、NULL 處理 |
| **MSSQL** | DECLARE @var、#temp / ##global 暫存表、GO、BULK INSERT |

## 🧪 測試策略（533 個測試案例，涵蓋 20 個套件）

我們嚴格遵守**測試驅動開發 (TDD)**，每個功能均遵循 **Red → Green → 零回歸** 循環。專案內包含 **20 個專門化測試套件**、**533 個全面測試案例**：

| 測試套件 | 測試數 | 涵蓋範圍 |
|---|---|---|
| `test_lexer_suite.py` | 16 | Token 化、關鍵字、多行註解、中括號、N'' 前綴 |
| `test_parser_suite.py` | 23 | 語句路由、AST 建構、語法錯誤邊界 |
| `test_expressions_suite.py` | 31 | 算術/位元/模數、CASE WHEN、BETWEEN、CAST/CONVERT 含長度與 style |
| `test_functions_suite.py` | 27 | 60+ 內建函數、函數沙箱、聚合完整性、COUNT(DISTINCT) |
| `test_select_features_suite.py` | 41 | DISTINCT、TOP/PERCENT、ORDER BY、GROUP BY/HAVING、OFFSET/FETCH、NULL 字面值 |
| `test_dml_suite.py` | 39 | INSERT（單列/多列/SELECT）、UPDATE、DELETE、TRUNCATE、強制 WHERE |
| `test_join_suite.py` | 33 | INNER/LEFT/RIGHT/FULL/CROSS JOIN、可空性傳導、多表鏈接 |
| `test_subquery_suite.py` | 32 | 純量、關聯、衍生資料表、UNION/INTERSECT/EXCEPT 衍生、ANY/ALL |
| `test_cte_suite.py` | 10 | 單一/多個 CTE、CTE + UPDATE/DELETE、CTE 作用域隔離 |
| `test_semantic_suite.py` | 23 | ZTA 強化、型別安全、別名規範、作用域堆疊、歧義檢測 |
| `test_mssql_features_suite.py` | 49 | DECLARE、#temp 暫存表、CROSS/OUTER APPLY、進階型別（Geography、XML…） |
| `test_mssql_boundary_suite.py` | 42 | 邊界案例：負數字面值、##global temp、位元運算子、INTERSECT/EXCEPT、字串函數 |
| `test_integration_suite.py` | 23 | 載入真實 AdventureWorks 元數據的端到端流水線、跨功能整合 |
| `test_window_functions_suite.py` | 22 | 視窗函數語法邊界（預期失敗套件） |
| `test_visualizer_suite.py` | 39 | 樹狀圖渲染、Mermaid 輸出、型別標註、全語句類型 |
| `test_serializer_suite.py` | 29 | 所有 AST 節點的 JSON 序列化、往返準確性 |
| `test_cli_suite.py` | 4 | CLI 參數解析、檔案 I/O、輸出格式驗證 |
| `test_web_api_suite.py` | 3 | RESTful 端點、JSON 回應格式、HTTP 錯誤代碼 |
| `test_mermaid_suite.py` | 3 | Mermaid 流程圖產生與節點結構 |
| `test_reconstructor_suite.py` | 32 | AST JSON → SQL 重建、往返準確性、所有語句類型 |

**目前狀態**: ✅ **100% 測試通過** (533/533)
```powershell
pytest tests/
```
