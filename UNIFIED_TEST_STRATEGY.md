# BirdEye-SQL 統一測試戰略文件

版本：v1.0  
適用範圍：BirdEye-SQL 全專案（核心引擎、CLI、Web API、意圖提取、重建器）  
最後更新：2026-04-22

---

## 1. 戰略目的

本文件用於統一 BirdEye-SQL 的測試方法、品質門檻、交付節奏與責任分工，確保：

- 功能正確：SQL -> AST -> JSON -> SQL 的全流程一致性。
- 安全可控：Zero Trust Architecture (ZTA) 策略持續生效。
- 變更可回歸：新功能上線不破壞既有語法與語意行為。
- 測試可治理：所有測試活動可追蹤、可量化、可審計。

---

## 2. 品質目標與驗收門檻

### 2.1 品質目標

- 語法正確性：MSSQL 主要語法可穩定解析。
- 語意正確性：型別推導、作用域、歧義檢查、聚合完整性正確。
- 安全性：高風險語句與函式依 ZTA 策略 fail-closed。
- 相容性：新語法與既有功能共存，不造成回歸。
- 可維護性：測試結構一致、命名一致、案例可擴充。

### 2.2 Release Gate（釋出門檻）

每次合併到主分支前，至少滿足：

1. 全測試通過：`PYTHONPATH=. pytest tests/`
2. 核心套件不得出現新增失敗案例。
3. 新功能需附對應測試（至少 1 個成功案例 + 1 個失敗案例）。
4. 涉及 Parser/Binder 變更時，需補對應 coverage/edge case 測試。
5. 涉及安全邏輯（ZTA/黑名單）時，必須補 adversarial 測試。

---

## 3. 測試範圍（Scope）

### 3.1 In Scope

- Lexer：token 化、關鍵字、字串/註解/中括號識別。
- Parser：語句路由、語法結構、錯誤攔截。
- Binder：型別推論、作用域管理、ZTA 規則。
- Serializer / Visualizer / Mermaid exporter。
- Reconstructor：AST JSON 重建 SQL。
- Runner：整體流程、批次 GO、狀態共享。
- Web API：`/api/parse`, `/api/reconstruct`, `/api/intent`。
- CLI：參數、輸出格式、錯誤回傳。

### 3.2 Out of Scope（目前）

- 壓力測試與長時間 soak test。
- 真實 DB 端執行效能基準。
- 前端視覺 UI 細節測試（僅 API 合約驗證）。

---

## 4. 測試方法統一框架

本專案採「黑盒 + 白盒 + 安全對抗」混合策略：

1. TDD（Red -> Green -> Refactor）
2. Syntax-based Testing（語法導向）
3. Boundary Value Testing（邊界值）
4. Equivalence Class Testing（等價類）
5. Decision Table-based Testing（決策表）
6. Input Space Partition（輸入空間分割）
7. Path Testing（路徑）
8. Logic Coverage（邏輯覆蓋）
9. Data Flow Testing（def-use）
10. Integration Testing（跨模組整合）
11. Coverage Regression（覆蓋回歸）

### 4.1 方法與測試檔映射（代表性）

- Syntax-based：`tests/test_parser_suite.py`, `tests/test_parser_coverage_suite.py`
- Boundary Value：`tests/test_mssql_boundary_suite.py`
- Decision Table / Adversarial：`tests/test_adversarial_appendix.py`, `tests/test_security_adversarial_suite.py`
- Data Flow：`tests/test_integration_suite.py`（DECLARE、SELECT INTO、GO、APPLY）
- Integration：`tests/test_integration_suite.py`, `tests/test_web_api_suite.py`, `tests/test_intent_api.py`
- Coverage：`tests/test_final_coverage_suite.py`, `tests/test_binder_runner_coverage_suite.py`, `tests/test_reconstructor_coverage_suite.py`

---

## 5. 測試分層策略（Test Pyramid）

### 5.1 Unit Tests（最大量）

目標：快速定位缺陷，驗證單模組行為。  
範圍：lexer/parser/binder/serializer/reconstructor/intent extractor。

### 5.2 Integration Tests（中量）

目標：驗證模組間契約與資料流。  
範圍：Runner 全流程、GO 分批、temp table/variable scope、API handler。

### 5.3 End-to-End/API Tests（少量但關鍵）

目標：驗證外部介面可用性與錯誤語義。  
範圍：Flask API + JSON contract + HTTP status code。

---

## 6. 缺陷預防與回歸策略

1. 每個 bug 必須對應至少一個 regression test。
2. 測試命名需反映 issue 或行為，例如：
   - `test_xxx_raises_semantic_error`
   - `test_issue_74_count_star_expands_columns`
3. 高風險區域（Parser/Binder/ZTA）採「變更即補測」規則。
4. 對抗性案例維持固定案例集，避免安全能力退化。

---

## 7. 測試資料與環境策略

### 7.1 Metadata 策略

- 主要使用 `data/output.csv`（AdventureWorks 風格）驗證真實語意。
- 部分套件使用最小化 CSV fixture 聚焦單一行為。

### 7.2 Fixture 策略

- 共用 session fixture（`tests/conftest.py`）提升執行效率。
- API 測試使用 Flask test client，避免外部依賴。

### 7.3 執行命令基準

```powershell
PYTHONPATH=. pytest tests/
PYTHONPATH=. pytest tests/test_integration_suite.py -v
PYTHONPATH=. pytest --collect-only -q
```

---

## 8. 指標（Metrics）

### 8.1 必追指標

- Test Pass Rate（整體通過率）
- Regression Escapes（回歸外洩缺陷數）
- Security Case Pass Rate（對抗測試通過率）
- Parser/Binder 變更對應測試覆蓋率

### 8.2 建議新增指標

- 每 PR 新增測試數
- 失敗案例平均修復時間（MTTR）
- 模組級 flaky test 追蹤（若未來出現）

---

## 9. CI/CD 導入藍圖（建議）

### Phase 1（立即）

- 將 `pytest tests/` 納入 PR 必跑檢查。
- 失敗即阻擋合併。

### Phase 2（短期）

- 新增 coverage job（如 `pytest-cov`）並產出 `term-missing` 報告。
- 設定核心模組最低 coverage 門檻。

### Phase 3（中期）

- 分層任務：unit/integration/security 分 job 平行執行。
- 產生測試趨勢報表（每週通過率、失敗熱點）。

---

## 10. 角色與責任

- Feature 開發者：
  - 新功能與缺陷修復必附測試。
  - 確保本地測試通過後再提交。
- Reviewer：
  - 檢查測試是否覆蓋成功/失敗路徑。
  - 檢查是否遺漏安全或作用域回歸風險。
- Maintainer：
  - 維護測試分層與命名規範。
  - 管理基準測試與對抗案例集。

---

## 11. 風險與對策

1. 風險：測試數量大，執行時間增加。  
   對策：分層執行、平行化、必要時標記慢測試。

2. 風險：功能變更造成舊案例失效。  
   對策：先修測試語義，再修功能；禁止直接刪除失敗案例。

3. 風險：安全測試案例與實際攻擊面脫節。  
   對策：每季檢視 OWASP/CWE，更新 adversarial case。

---

## 12. 文件治理

- 本文件為測試治理主文件。
- 當測試策略、門檻、流程改變時，需同步更新本文件。
- 建議在 README 增加連結至本文件，避免策略散落。

---

## 13. 快速檢查清單（PR 用）

在送 PR 前，請確認：

1. 是否新增或更新對應測試？
2. 是否涵蓋至少一個失敗路徑？
3. 是否涉及 ZTA/作用域/型別？若是，是否補安全或語意測試？
4. `PYTHONPATH=. pytest tests/` 是否全綠？
5. 是否更新必要文件（若策略或行為有改變）？

---

（完）
