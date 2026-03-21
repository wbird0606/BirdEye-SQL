# 🦅 BirdEye-SQL: Semantic-Aware & Zero-Trust SQL Parser

[![Testing: pytest](https://img.shields.io/badge/Testing-pytest-blue.svg)](https://docs.pytest.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

🌍 **Language Switch / 語言切換**: [English](#english-version) | [繁體中文](#繁體中文版本)

---

<a id="english-version"></a>
# 🇬🇧 English Version

## 📖 Overview
**BirdEye-SQL** is a high-performance SQL to AST (Abstract Syntax Tree) parser specifically designed for **MSSQL** environments. Unlike traditional syntactic parsers, BirdEye-SQL features **Semantic Awareness**, allowing it to validate queries against real database metadata in a **Zero Trust Architecture (ZTA)** context. It acts as a security gatekeeper, intercepting malicious or ambiguous queries before they reach the database engine.

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

### CLI Utility
You can also use the parser directly from the terminal:
```powershell
# Parse SQL and output an AST tree
python main.py --sql "SELECT * FROM Address" --format tree

# Parse from a file, use custom metadata, and output Mermaid syntax
python main.py --file my_query.sql --csv custom_schema.csv --format mermaid
```

## ✨ Key Features

### 🛡️ ZTA Security Enforcement
* **Strict Type Inference**: A robust type inference engine supporting implicit casting (e.g., `DATETIME` vs `NVARCHAR`) and User-Defined Types (UDT). It blocks illegal operations like comparing incompatible types.
* **Strict Alias Policy**: Once a table alias is defined, the original table name is invalidated to prevent semantic shadowing attacks.
* **Ambiguity Defense**: Mandatory qualifiers in JOIN environments to prevent "Column Ambiguity Attacks".
* **Function Sandbox**: Implements a "Deny-by-Default" whitelist for database functions. Prevents execution of dangerous system functions like `xp_cmdshell`.

### ⚙️ Engine Optimization
* **Full Pipeline Integration**: The `BirdEyeRunner` seamlessly connects the Lexer, Parser, Binder, and Visualizer.
* **Expression Engine**: Supports arithmetic operations (`+`, `-`, `*`, `/`), logical conditions (`AND`, `OR`, `IS NULL`), and nested `CASE WHEN` logic.
* **Star Expansion**: Automatically expands `SELECT *` or `Table.*` into explicit column lists using metadata.

## 🧪 Testing Strategy (189 Test Cases Across 21 Suites)
We strictly adhere to **Test-Driven Development (TDD)**. The project contains **189 comprehensive test cases** across **21 specialized test suites**, ensuring both syntactic correctness and semantic security:

### Core Component Testing
1. **`test_lexer_suite.py`** (8 tests) - Lexical Analysis
   * Tokenization, keyword recognition, MSSQL nested comments (`/* /* */ */`), bracket escaping, and syntax boundary validation.

2. **`test_parser_suite.py`** (7 tests) - Syntactic Analysis  
   * Statement routing, AST construction, syntax error handling, and parsing boundary checks.

### Semantic & Type Safety Testing
3. **`test_type_checking_suite.py`** (4 tests) - Type Safety Enforcement
   * Function parameter type validation, binary operator type compatibility, and CASE expression result consistency.

4. **`test_expression_suite.py`** (16 tests) - Expression Engine
   * Arithmetic precedence (PEMDAS), `IS NULL` operators, type compatibility, and complex expression evaluation.

5. **`test_functions_suite.py`** (6 tests) - Function Sandbox
   * Built-in function validation, parameter type checking, aggregate function integrity, and restricted function blocking.

### SQL Feature Testing
6. **`test_between_suite.py`** (5 tests) - BETWEEN Syntax
   * BETWEEN expression parsing, type compatibility validation, and NOT BETWEEN handling.

7. **`test_case_when_suite.py`** (4 tests) - CASE WHEN Logic
   * CASE expression parsing, branch evaluation, nested CASE structures, and result type consistency.

8. **`test_cast_suite.py`** (3 tests) - Type Casting
   * CAST/CONVERT syntax parsing, type conversion validation, and expression integration.

9. **`test_cte_suite.py`** (3 tests) - Common Table Expressions
   * WITH clause parsing, CTE reference validation, and recursive CTE handling.

10. **`test_union_suite.py`** (5 tests) - UNION Operations
    * UNION/UNION ALL syntax, column count matching, and type compatibility across queries.

### Data Manipulation Testing
11. **`test_dml_suite.py`** (6 tests) - DML Operations
    * UPDATE/DELETE statement validation, mandatory WHERE clauses, and type-safe assignments.

12. **`test_insert_suite.py`** (8 tests) - INSERT Operations
    * INSERT syntax parsing, column alignment, value type checking, and bulk insert handling.

### Query Structure Testing
13. **`test_join_suite.py`** (7 tests) - JOIN Operations
    * Multi-table JOIN syntax, ambiguity prevention, alias shadowing protection, and ON condition validation.

14. **`test_join_multi_table_suite.py`** (3 tests) - Multi-Table JOINs
    * Three-way JOIN visibility, table alias resolution, and complex JOIN chain validation.

15. **`test_join_nullable_suite.py`** (2 tests) - NULL Handling in JOINs
    * LEFT/RIGHT JOIN nullability propagation and nullable column tracking.

16. **`test_group_by_having_suite.py`** (6 tests) - Aggregation
    * GROUP BY expression integrity, aggregate function validation, and HAVING clause processing.

17. **`test_order_by_top_suite.py`** (10 tests) - Sorting & Pagination
    * ORDER BY column resolution, TOP N syntax, alias resolution, and sort direction handling.

18. **`test_scope_stack_suite.py`** (4 tests) - Scope Management
    * Variable scoping rules, correlated subquery binding, and nested scope resolution.

### Security & ZTA Testing
19. **`test_semantic_zta_suite.py`** (16 tests) - Zero Trust Architecture
    * Semantic security enforcement, metadata-driven validation, star expansion security, and ZTA policy compliance.

### Integration & Interface Testing
20. **`test_integration_suite.py`** (8 tests) - End-to-End Integration
    * Complete pipeline validation with real AdventureWorks metadata, performance benchmarking, and cross-component integration.

21. **`test_cli_suite.py`** (4 tests) - CLI Interface
    * Command-line argument parsing, file I/O operations, output format validation, and error handling.

22. **`test_web_api_suite.py`** (3 tests) - Web API
    * RESTful endpoint validation, JSON response formatting, HTTP error codes, and API stability.

23. **`test_visualizer_suite.py`** (11 tests) - AST Visualization
    * Tree diagram rendering, Mermaid flowchart generation, type annotation display, and visual output validation.

24. **`test_serializer_suite.py`** (4 tests) - AST Serialization
    * JSON serialization accuracy, AST reconstruction, metadata preservation, and format compatibility.

**Current Status**: ✅ **100% Tests Passed** (189/189)
```powershell
pytest tests/
```

<br>
<hr>
<br>

<a id="繁體中文版本"></a>
# 🇹🇼 繁體中文版本

## 📖 專案概述
**BirdEye-SQL** 是一款專為 **MSSQL** 環境設計的高效能 SQL 轉 AST（抽象語法樹）解析器。不同於傳統的語法解析器，BirdEye-SQL 具備**語意覺知**功能，使其能在**零信任架構 (ZTA)** 背景下，根據真實的資料庫元數據驗證查詢語句。它作為資安守門員，在查詢進入資料庫引擎前，先行攔截具備惡意特徵或語意模糊的語句。

## 🚀 快速開始

### 環境建置
請確保你已安裝 Python 3.10+，然後執行以下指令安裝必要套件：
```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### Web 視覺化儀表板
BirdEye-SQL 內建了一個基於 Flask 的現代化 Web UI，支援動態載入 CSV 元數據，並能即時渲染帶有型別推導的 AST Tree 與 Mermaid 流程圖 (支援平移縮放與圖片下載)。
```powershell
python web/app.py
```
打開瀏覽器前往 `http://127.0.0.1:5000` 即可體驗！

### 命令列工具 (CLI)
你也可以直接在終端機使用 CLI 工具：
```powershell
# 解析一段 SQL 並顯示樹狀圖
python main.py --sql "SELECT * FROM Address" --format tree

# 解析檔案並輸出 Mermaid 語法，同時指定自定義的元數據
python main.py --file my_query.sql --csv custom_schema.csv --format mermaid
```

## ✨ 核心功能

### 🛡️ 零信任資安強化 (ZTA)
* **嚴格型別推導**: 具備強大的型別推導與相容性檢查引擎，支援隱含轉型 (如 `DATETIME` 與 `NVARCHAR`) 及使用者定義類型 (UDT)，防堵不合法的賦值與比較。
* **嚴格別名規範**: 一旦定義了別名，原始表名即刻失效，防止語義陰影攻擊。
* **歧義防禦**: 在 JOIN 環境下強制要求限定符，防止「欄位歧義攻擊」。
* **函數沙箱**: 實作「預設拒絕」的函數白名單機制，攔截如 `xp_cmdshell` 等高風險系統函數。

### ⚙️ 引擎優化與特性
* **全域流水線整合**: 提供 `BirdEyeRunner` 核心引擎，完美串接 Lexer -> Parser -> Binder -> Visualizer 完整流水線。
* **強大表達式引擎**: 支援算術運算 (`+`, `-`, `*`, `/`)、邏輯條件 (`AND`, `OR`, `IS NULL`) 與多層巢狀 `CASE WHEN` 的精確解析。
* **星號自動展開**: 利用元數據自動將 `SELECT *` 或 `Table.*` 展開為明確的實體欄位清單。

## 🧪 測試策略 (總計 189 測試案例，涵蓋 21 個測試套件)
我們嚴格遵守**測試驅動開發 (TDD)**。專案內包含 **21 個專門化測試套件**、**189 個全面測試案例**，全面涵蓋語法解析與語意防禦：

### 核心組件測試
1. **`test_lexer_suite.py`** (8 測試) - 詞法分析
   * Token 化、關鍵字識別、MSSQL 巢狀多行註解 (`/* /* */ */`)、中括號轉義以及語法邊界驗證。

2. **`test_parser_suite.py`** (7 測試) - 語法分析
   * 語句路由、AST 構建、語法錯誤處理以及解析邊界檢查。

### 語意與類型安全測試
3. **`test_type_checking_suite.py`** (4 測試) - 類型安全強化
   * 函數參數類型驗證、二元運算子類型相容性以及 CASE 表達式結果一致性。

4. **`test_expression_suite.py`** (16 測試) - 表達式引擎
   * 算術優先級 (先乘除後加減)、`IS NULL` 運算子、類型相容性以及複雜表達式計算。

5. **`test_functions_suite.py`** (6 測試) - 函數沙箱
   * 內建函數驗證、參數類型檢查、聚合函數完整性以及受限函數攔截。

### SQL 特性測試
6. **`test_between_suite.py`** (5 測試) - BETWEEN 語法
   * BETWEEN 表達式解析、類型相容性驗證以及 NOT BETWEEN 處理。

7. **`test_case_when_suite.py`** (4 測試) - CASE WHEN 邏輯
   * CASE 表達式解析、分支計算、巢狀 CASE 結構以及結果類型一致性。

8. **`test_cast_suite.py`** (3 測試) - 類型轉換
   * CAST/CONVERT 語法解析、類型轉換驗證以及表達式整合。

9. **`test_cte_suite.py`** (3 測試) - 公共表達式
   * WITH 子句解析、CTE 引用驗證以及遞歸 CTE 處理。

10. **`test_union_suite.py`** (5 測試) - UNION 操作
    * UNION/UNION ALL 語法、欄位數量匹配以及跨查詢的類型相容性。

### 資料操作測試
11. **`test_dml_suite.py`** (6 測試) - DML 操作
    * UPDATE/DELETE 語句驗證、強制 WHERE 子句以及類型安全賦值。

12. **`test_insert_suite.py`** (8 測試) - INSERT 操作
    * INSERT 語法解析、欄位對齊、數值類型檢查以及批次插入處理。

### 查詢結構測試
13. **`test_join_suite.py`** (7 測試) - JOIN 操作
    * 多表 JOIN 語法、歧義預防、別名遮蔽保護以及 ON 條件驗證。

14. **`test_join_multi_table_suite.py`** (3 測試) - 多表 JOIN
    * 三向 JOIN 可見性、表別名解析以及複雜 JOIN 鏈驗證。

15. **`test_join_nullable_suite.py`** (2 測試) - JOIN 中的 NULL 處理
    * LEFT/RIGHT JOIN 可空性傳導以及可空欄位追蹤。

16. **`test_group_by_having_suite.py`** (6 測試) - 聚合操作
    * GROUP BY 表達式完整性、聚合函數驗證以及 HAVING 子句處理。

17. **`test_order_by_top_suite.py`** (10 測試) - 排序與分頁
    * ORDER BY 欄位解析、TOP N 語法、別名解析以及排序方向處理。

18. **`test_scope_stack_suite.py`** (4 測試) - 作用域管理
    * 變數作用域規則、相關子查詢綁定以及巢狀作用域解析。

### 安全與 ZTA 測試
19. **`test_semantic_zta_suite.py`** (16 測試) - 零信任架構
    * 語意安全強化、元數據驅動驗證、星號展開安全以及 ZTA 政策合規。

### 整合與介面測試
20. **`test_integration_suite.py`** (8 測試) - 端到端整合
    * 載入真實 AdventureWorks 元數據的完整流水線驗證、效能基準測試以及跨組件整合。

21. **`test_cli_suite.py`** (4 測試) - CLI 介面
    * 命令列參數解析、檔案 I/O 操作、輸出格式驗證以及錯誤處理。

22. **`test_web_api_suite.py`** (3 測試) - Web API
    * RESTful 端點驗證、JSON 回應格式、HTTP 錯誤代碼以及 API 穩定性。

23. **`test_visualizer_suite.py`** (11 測試) - AST 可視化
    * 樹狀圖渲染、Mermaid 流程圖生成、類型註解顯示以及視覺輸出驗證。

24. **`test_serializer_suite.py`** (4 測試) - AST 序列化
    * JSON 序列化準確性、AST 重建、元數據保留以及格式相容性。

**目前狀態**: ✅ **100% 測試通過** (189/189)
```powershell
pytest tests/
```