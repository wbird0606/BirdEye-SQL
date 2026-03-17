# 🦅 BirdEye-SQL: Semantic-Aware SQL Parser
### 透過 AI 增強型 TDD 實作具備語意覺知之 SQL 解析器

[![Testing: pytest](https://img.shields.io/badge/Testing-pytest-blue.svg)](https://docs.pytest.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![AI-Assisted: Gemini/Claude](https://img.shields.io/badge/AI--Assisted-Gemini%20%7C%20Claude-orange)](https://gemini.google.com/)

## 📖 Overview | 專案概述
**BirdEye-SQL** is a high-performance SQL to AST (Abstract Syntax Tree) parser specifically designed for MSSQL environments. Unlike traditional syntactic parsers, BirdEye-SQL features **Semantic Awareness**, allowing it to validate queries against real database metadata in a **Zero Trust Architecture (ZTA)** context.

**BirdEye-SQL** 是一款專為 MSSQL 環境設計的高效能 SQL 轉 AST（抽象語法樹）解析器。不同於傳統的語法解析器，BirdEye-SQL 具備**語意覺知**功能，使其能在**零信任架構 (ZTA)** 背景下，根據真實的資料庫元數據驗證查詢語句。

---

## ✨ Key Features | 核心功能
* **Zero-copy Lexer**: Optimized memory efficiency using index-based scanning.
    * **零拷貝詞法分析器**：透過索引掃描優化記憶體使用效率。
* **Semantic Binding**: Resolves table aliases (`AS`) and validates columns against CSV-based metadata.
    * **語意綁定**：處理資料表別名 (`AS`) 並根據 CSV 元數據驗證欄位真實性。
* **Star Expansion**: Automatically expands `SELECT *` into explicit column lists using database schema.
    * **星號展開**：利用資料庫 Schema 自動將 `SELECT *` 展開為明確的欄位清單。
* **AI-Augmented TDD**: Developed with 100% test coverage driven by Gemini, Claude, and GitHub Copilot.
    * **AI 增強型 TDD**：由 Gemini、Claude 與 Copilot 驅動，達成 100% 邏輯測試覆蓋率。

---

## 🏗️ Architecture | 系統架構
The project follows a modular compiler-front-end pipeline:
本專案遵循模組化的編譯器前端管線：



1. **Lexer**: Tokenizes raw SQL into index-based symbols.
    * **詞法分析器**：將原始 SQL 切分為基於索引的標記。
2. **Parser**: Builds a Raw AST using **Recursive Descent** algorithms.
    * **解析器**：採用**遞迴下降**演算法建構原始 AST。
3. **Metadata Registry**: Loads MSSQL schema from CSV files.
    * **元數據註冊表**：從 CSV 檔案載入 MSSQL Schema。
4. **Binder**: Resolves semantic meaning and performs security validation.
    * **綁定器**：解析語意並進行資安驗證校驗。

---

## 🧪 Testing Strategy | 測試策略
We strictly adhere to the **Test-Driven Development (TDD)** methodology:
我們嚴格遵守**測試驅動開發 (TDD)** 方法論：



* **Red Phase**: Define failing tests for SQL edge cases (e.g., MSSQL brackets `[]`).
    * **紅燈階段**：針對 SQL 邊界案例（如 MSSQL 中括號 `[]`）定義失敗測試。
* **Green Phase**: Implement minimal logic to pass the test suite.
    * **綠燈階段**：實作最精簡邏輯以通過測試套件。
* **Refactor**: Optimize performance and code structure.
    * **重構階段**：優化效能與程式碼結構。

---

## 🤖 Human-AI Collaboration | 人機協作
This project is a testament to modern AI-assisted software engineering:
本專案是現代 AI 輔助軟體工程的實踐證明：

* **Human (Architect)**: Design patterns, security auditing, and project management.
    * **人類（架構師）**：負責設計模式、資安審核與專案管理。
* **Gemini 3 Flash**: Test Case Engineer; generates comprehensive `pytest` suites and boundary cases.
    * **Gemini 3 Flash（測試工程師）**：負責生成完整的 `pytest` 套件與邊界案例。
* **Claude**: Quality Assurance & Refactoring; specializes in complex semantic logic analysis.
    * **Claude（品質保證與重構）**：負責程式碼重構與複雜語意邏輯分析。
* **GitHub Copilot**: Development Assistant; handles boilerplate code and regex patterns.
    * **GitHub Copilot（開發助理）**：負責處理基礎代碼與正規表示式標記。

---

## 🚀 Getting Started | 快速開始

### Prerequisites | 前置作業
Export your MSSQL metadata to a CSV file using the following SQL command:
使用以下 SQL 指令將您的 MSSQL 元數據導出為 CSV 檔案：

```sql
SELECT t.name AS table_name, c.name AS column_name, tp.name AS data_type
FROM sys.tables t
JOIN sys.columns c ON t.object_id = c.object_id
JOIN sys.types tp ON c.user_type_id = tp.user_type_id
WHERE t.is_ms_shipped = 0
ORDER BY table_name, c.column_id;
