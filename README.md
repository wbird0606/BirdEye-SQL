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

## 🧪 Testing Strategy (135+ Test Cases)
We strictly adhere to **Test-Driven Development (TDD)**. The project contains over 135 robust test cases across 19 suites, ensuring both syntactic correctness and semantic security:

1. **Lexer & Parser (`test_lexer_suite.py`, `test_parser_suite.py`)**: 
   * Tests tokenization, constants, MSSQL nested comments (`/* /* */ */`), bracket escaping, and syntax boundary checks.
2. **Expression & Functions (`test_expression_suite.py`, `test_functions_suite.py`)**: 
   * Validates arithmetic precedence (PEMDAS), `IS NULL` operators, type compatibility, and function sandboxing (blocking unregistered functions).
3. **DML & INSERT (`test_dml_suite.py`, `test_insert_suite.py`)**: 
   * Ensures `UPDATE`/`DELETE` statements have mandatory `WHERE` clauses, performs strict type checking on assignments, and validates `INSERT` column count alignments.
4. **JOIN & Aggregation (`test_join_suite.py`, `test_group_by_having_suite.py`)**: 
   * Tests ambiguity defense in multi-table queries, alias shadowing, `GROUP BY` expression integrity, and `HAVING` clause validations.
5. **ZTA & Integration (`test_semantic_zta_suite.py`, `test_integration_suite.py`, `test_order_by_top_suite.py`)**: 
   * End-to-end tests using real AdventureWorks metadata. Validates star expansion, UDT implicit casting, and `ORDER BY` alias resolution.
6. **Interface Stability (`test_cli_suite.py`, `test_web_api_suite.py`, `test_visualizer_suite.py`)**: 
   * Tests CLI argument parsing, Web API JSON responses, error handling, and visualizer type displays.

**Current Status**: 100% Tests Passed. ✅
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

## 🧪 測試策略 (總計 135+ 測試案例)
我們嚴格遵守**測試驅動開發 (TDD)**。專案內包含 19 個測試套件、超過 135 個以上的精確測試案例，全面涵蓋語法解析與語意防禦：

1. **詞法與語法解析 (`test_lexer_suite.py`, `test_parser_suite.py`)**：
   * 驗證 Token 化、MSSQL 巢狀多行註解 (`/* /* */ */`)、中括號轉義以及語法邊界攔截。
2. **表達式與函數沙箱 (`test_expression_suite.py`, `test_functions_suite.py`)**：
   * 驗證算術優先級 (先乘除後加減)、`IS NULL` 判斷、型別相容性，以及未註冊函數的沙箱攔截機制。
3. **DML 與寫入防禦 (`test_dml_suite.py`, `test_insert_suite.py`)**：
   * 確保 `UPDATE` 與 `DELETE` 強制包含 `WHERE` 條件，並驗證 `INSERT` 時的欄位數量對齊與嚴格寫入型別檢查。
4. **關聯與聚合檢查 (`test_join_suite.py`, `test_group_by_having_suite.py`)**：
   * 測試多表 JOIN 的歧義防禦、別名失效機制，以及 `GROUP BY` 中複雜表達式的聚合完整性與 `HAVING` 校驗。
5. **真實元數據端到端整合 (`test_semantic_zta_suite.py`, `test_integration_suite.py`, `test_order_by_top_suite.py`)**：
   * 載入 AdventureWorks 真實元數據進行端到端測試。驗證星號展開、UDT (使用者定義類型) 的隱含轉型，以及 `ORDER BY` 正確解析 `SELECT` 別名。
6. **介面與視覺化穩定性 (`test_cli_suite.py`, `test_web_api_suite.py`, `test_visualizer_suite.py`)**：
   * 驗證命令列參數解析、Web API 的 JSON 回應格式、錯誤處理機制，以及視覺化工具是否正確顯示推導型別。

**目前狀態**: 100% 測試通過。 ✅
```powershell
pytest tests/
```