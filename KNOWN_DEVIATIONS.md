# Known Deviations

Go 版刻意與 Python [[baseline]] 不同之處。分兩類。

---

## A. 待修 Python bug（Go 忠實複製，[[parity]] 後統一修）

移植途中發現的 Python 明顯 bug。Go 照 Python 現行行為複製，[[conformance-corpus]]
也會編碼這個「錯誤但一致」的行為。達到 parity 後另開 issue 一起修 Python + Go。

見 [ADR 0006](./docs/adr/0006-replicate-python-quirks.md)。

| # | 位置 | 現象 | 發現於里程碑 |
|---|---|---|---|
| A1 | `parser.py` `_parse_block` while 迴圈 | `IF <cond> BEGIN <非語句 token 如 `.`> END` 會無限迴圈：`_parse_single_stmt()` 遇到無法辨識的 token 時回傳 `None` 且**不推進位置**，外層 `while` 因此永不前進。只在畸形輸入下可達。 | 0（fixture 產生器）|

> A1 例外處理：無限迴圈不是「行為」而是掛死，Go **不複製**。Go 版在此情況丟 parser error（syntax 分類）。對應 golden fixture 由產生器標記 `error.category = "hang"`，Go conformance 允許以 syntax error 對應。

| A2 | `reconstructor.py` `_sql_ExecStatement` | 讀 `na['name']` / `na['value']`，但 serializer 對 `named_args`（AssignmentNode）存的是 `column` / `expr` → `KeyError`。忠實複製為 system 分類錯誤。 | 4（reconstructor）|
| A3 | `visualizer.py` ExecStatement `RETURN_VAR` | `f"...RETURN_VAR: {node.return_var}"` 直接格式化 IdentifierNode 物件；無 `__str__` → 印 `<birdeye.ast.IdentifierNode object at 0x…>`（含記憶體位址，**每次執行都不同**）。Go 印變數名。對應 golden 由 conformance 略過。 | 10（visualizer）|

| A4 | `intent_extractor.py` MERGE 來源 | `MERGE … USING <資料表> AS s` 時，來源欄位之意圖（`s.ID`、`s.Name`）的 table 欄位為**別名** `s`，而非真實資料表；權限系統因此查無此表，來源表之欄位讀取實際上未被授權檢查。**Go 已刻意修正**：來源欄位歸屬於真實資料表。對應 5 筆 conformance fixture 於 `intent_conformance_test.go` 之 `knownMergeSourceDeviation` 放行，行為由 `recursive_merge_test.go` 鎖定。 | 2026-11（遞迴 CTE／MERGE 修正）|

| A5 | `intent_extractor.py` CTE 欄位 | 經由 CTE 讀取之欄位，因 binder 標註之 `resolved_table` 為 CTE 名稱，被當成資料表輸出（schema 為空，例：`C.CustomerID`）。權限服務 `EvaluateIntent` 對查無權限列之資料表回傳 Deny，使所有 CTE 查詢被拒。**Go 已刻意修正**：CTE 名稱不輸出為資料表；CTE 內部對真實資料表之讀取意圖不變。對應 19 筆 conformance fixture 於 `knownCTENameDeviation` 放行，行為由 `recursive_merge_test.go` 鎖定。 | 2026-11 |
| A6 | `binder.py` 欄位限定詞檢查 | 對**無別名**之 schema 限定資料表，三段式欄位名（`schema.table.column`）被誤判為「已定義別名卻使用原始表名」而拒絕（比對鍵不含 schema）。Go 已修正：僅在確實以別名登記時才拒絕。 | 2026-11 |

| A7 | `reconstructor.py` 子查詢運算式 | 子查詢作為運算式（EXISTS／IN／SELECT 清單純量子查詢／`UPDATE … SET col = (…)`）重建時：（1）把內層 FROM 之**資料表別名**當成運算式別名附加在尾端（`… WHERE d.x = h.x AS d)`）；（2）SELECT 清單與 SET 右側之子查詢缺括號。產生不合法 SQL。Go 已修正；運算式別名另以 `expr_alias` 保存。對應 32 筆 reconstruct fixture 於 `knownReconstructDeviation` 放行。 | 2026-11 |
| A8 | `serializer.py` 字面值／子查詢別名 | `SELECT 0 AS lvl` 之字面值欄位別名在序列化時遺失，重建成 `SELECT 0`（遞迴 CTE 錨點因此失效）。Go 已修正：LiteralNode 於有別名時輸出 `alias`；子查詢運算式別名輸出 `expr_alias`（僅非空時，其餘 AST JSON 不變）。對應 34 筆 AST fixture 於 `knownAliasASTDeviation` 放行。 | 2026-11 |
| A9 | `rowfilter.go` 外部 JOIN（承襲 Python 移植，未於 Python 版另行驗證） | 列過濾一律以 AND 併入 WHERE；外部 JOIN 之可為 NULL 側因此被剔除保留列（退化為內部 JOIN），FULL JOIN 時亦使應被過濾之列以保留列形式漏出（以差分測試對 VM 真實資料庫發現）。Go 已修正：可為 NULL 側改以 `(SELECT * FROM T WHERE …) AS 別名` 取代；非 NULL 側維持 WHERE 注入。 | 2026-11 |
| A10 | `rowfilter.go` 自我 JOIN（承襲 Python 移植，未於 Python 版另行驗證） | 同一資料表出現多個別名時，列過濾僅套用於**第一個**別名，其餘別名完全未過濾，可據以讀取應被過濾之列（**授權繞過**）。Go 已修正：每個別名皆套用。 | 2026-11 |
| A11 | `rowfilter.go` DML 內部查詢（承襲 Python 移植，未於 Python 版另行驗證） | 列過濾注入器僅處理 SELECT、UPDATE／DELETE 之目標表、UNION、IF，**不走進** `INSERT … SELECT` 之來源、`MERGE … USING` 之來源，以及 UPDATE／DELETE 之 WHERE／SET 子查詢；有 INSERT 權限之角色可藉 `INSERT … SELECT` 把受限資料表之全部列（含應被過濾者）複製出去（**授權繞過**）。Go 已修正：INSERT 目標不加 WHERE，僅過濾其讀取來源；MERGE 來源（資料表改以過濾後衍生資料表取代，子查詢遞迴過濾）；UPDATE／DELETE 之子查詢遞迴過濾。MERGE 目標表因 T-SQL 不允許衍生資料表作為目標，具適用列過濾時 Fail-Closed 拒絕。 | 2026-11 |
| A12 | `intent.go` `collectTables` | 第一遍資料表探索未涵蓋 `IF` 區塊，區塊內之 SELECT 資料表無法載入 schema，引擎以 `Table not found` 誤拒（Fail-Closed，非繞過）。Go 已補。 | 2026-11 |

| A13 | `binder.py` `_bind_exec` | 僅以 8 個程序之封鎖清單攔截 `EXEC`，其餘預存程序（含 `usp_*` 自訂程序、`sp_help`、`sp_columns` 等）一律放行。預存程序內部讀寫之欄位對 BirdEye 不可見，因此該呼叫不產生任何欄位意圖，權限平台收到空意圖時回傳 Allowed，列過濾亦不套用。Go 已修正：改為**預設拒絕**，僅允許白名單（`Analyser.SetAllowedProcs`／環境變數 `BIRDEYE_ALLOWED_PROCS`）所列者；封鎖清單恆優先（白名單含封鎖清單之程序視為設定錯誤，啟動即報錯）；以變數指定程序名稱（`EXEC @p`）一律拒絕。一致性測試中受影響之案例記為已知偏離（略過比對）。 |

| A14 | `intent_extractor.py` 位置參數 | qmark 模式下位置參數（`@P1`…）序列化為 `?`，而意圖萃取僅略過 `@` 開頭之名稱，`?` 因此被當成名為 `?` 之欄位，對帶參數之 `WHERE`（例：`WHERE ProductID > ?`）多產生一筆 `column = "?"` 之 FILTER 意圖；權限平台查無此欄位而拒絕，使所有帶參數之篩選查詢被擋（Fail-Closed，非繞過）。**Go 已修正**：`?` 不產生意圖。對應 fixture 於 `wantsPlaceholderColumn` 放行，行為由 `qmark_param_intent_test.go` 鎖定。 | 2026-11 |

---

## B. 語言本質差異（非待修 bug）

因 Go 語言特性或刻意設計選擇而產生、且**不打算**回頭對齊的差異。

| # | 主題 | Python 行為 | Go 行為 | 依據 |
|---|---|---|---|---|
| B1 | Binder 跨呼叫狀態 | 兩次 `run()` 之間 `temp_schemas` / `variable_scope` 外洩（無測試依賴） | 每次呼叫全新 binder 狀態，`Run` 併發安全 | [ADR 0004](./docs/adr/0004-runner-fresh-binder-state-per-call.md) |
| B3 | serializer 未知節點型別 | `type(node).__name__`（如 `"DummyNode"`） | `nodeTypeName` 為編譯期 type switch，未知型別走 `default` 回傳 `""` | Go 無 runtime 型別名；實際 pipeline 不會產生未知節點，此為防禦性 default |
| B2 | JSON 特殊字元 | `U+2028` / `U+2029` 原樣輸出 | Go `encoding/json` 仍會 escape 為 ` ` / ` ` | [ADR 0002](./docs/adr/0002-byte-identical-ast-json.md) |
