# 🦅 BirdEye-SQL: Semantic-Aware & Zero-Trust SQL Parser
### 透過 AI 增強型 TDD 實作具備語意覺知與零信任防禦之 SQL 解析器

[![Testing: pytest](https://img.shields.io/badge/Testing-pytest-blue.svg)](https://docs.pytest.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Security: Zero Trust](https://img.shields.io/badge/Security-Zero%20Trust-red.svg)](#-zta-security-policies--零信任資安規範)

## 📖 Overview | 專案概述
**BirdEye-SQL** is a high-performance SQL to AST (Abstract Syntax Tree) parser specifically designed for **MSSQL** environments. Unlike traditional syntactic parsers, BirdEye-SQL features **Semantic Awareness**, allowing it to validate queries against real database metadata in a **Zero Trust Architecture (ZTA)** context. It acts as a security gatekeeper, intercepting malicious or ambiguous queries before they reach the database engine.

**BirdEye-SQL** 是一款專為 **MSSQL** 環境設計的高效能 SQL 轉 AST（抽象語法樹）解析器。不同於傳統的語法解析器，BirdEye-SQL 具備**語意覺知**功能，使其能在**零信任架構 (ZTA)** 背景下，根據真實的資料庫元數據驗證查詢語句。它作為資安守門員，在查詢進入資料庫引擎前，先行攔截具備惡意特徵或語意模糊的語句。

---

## ✨ Key Features | 核心功能

### 🛡️ ZTA Security Enforcement | 零信任資安強化
* **Strict Alias Policy (Issue #19)**: Once a table alias is defined, the original table name is invalidated to prevent semantic shadowing attacks.
    * **嚴格別名規範**：一旦定義了別名，原始表名即刻失效，防止語義陰影攻擊。
* **Ambiguity Defense (Issue #23)**: Mandatory qualifiers in JOIN environments to prevent "Column Ambiguity Attacks".
    * **歧義防禦**：在 JOIN 環境下強制要求限定符，防止「欄位歧義攻擊」。
* **Function Sandbox (Issue #24)**: Implements a "Deny-by-Default" whitelist for database functions (e.g., `COUNT`, `SUM`). Prevents execution of dangerous system functions like `xp_cmdshell`.
    * **函數沙箱**：實作「預設拒絕」的函數白名單機制，攔截如 `xp_cmdshell` 等高風險系統函數。

### 🏗️ MSSQL Specific Support | MSSQL 特性支援
* **Nested Comment Parsing (Issue #21)**: Full support for nested multi-line comments (`/* /* */ */`), closing security gaps in comment-based SQL injection.
    * **巢狀註解解析**：支援 MSSQL 巢狀多行註解，封堵利用註解差異進行的注入漏洞。
* **Bracket Escaping (Issue #22)**: Handles MSSQL's unique `]]` escaping within bracketed identifiers.
    * **括號轉義支援**：精準解析中括號轉義語法，確保標識符識別不被混淆。

### ⚙️ Engine Optimization | 引擎優化
* **Expression Engine (Issue #24)**: Supports recursive parsing of arithmetic operations (`+`, `-`, `*`, `/`, `%`) with proper operator precedence.
    * **表達式引擎**：支援算術運算的遞迴解析與運算子優先級處理。
* **Star Expansion**: Automatically expands `SELECT *` or `Table.*` into explicit column lists using metadata.
    * **星號展開**：利用元數據自動將星號展開為明確的欄位清單。

---

## 🧪 Testing Strategy | 測試策略
We strictly adhere to the **Test-Driven Development (TDD)** methodology with centralized regression suites:
我們嚴格遵守**測試驅動開發 (TDD)** 與集中化回歸測試套件：

* **`test_lexer_suite.py`**: Validates tokenization, constants, and nested comment integrity.
* **`test_parser_suite.py`**: Ensures syntactic correctness and precise boundary checks (e.g., `;` interception).
* **`test_semantic_zta_suite.py`**: Verifies alias enforcement and star expansion logic.
* **`test_join_suite.py`**: Tests relational queries and column ambiguity protection.
* **`test_expression_suite.py`**: (New) Validates arithmetic operations and function sandbox security.

**Current Status**: 47/47 Tests Passed. ✅
**執行指令：**
```powershell
python -m pytest .\tests