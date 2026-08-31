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

---

## B. 語言本質差異（非待修 bug）

因 Go 語言特性或刻意設計選擇而產生、且**不打算**回頭對齊的差異。

| # | 主題 | Python 行為 | Go 行為 | 依據 |
|---|---|---|---|---|
| B1 | Binder 跨呼叫狀態 | 兩次 `run()` 之間 `temp_schemas` / `variable_scope` 外洩（無測試依賴） | 每次呼叫全新 binder 狀態，`Run` 併發安全 | [ADR 0004](./docs/adr/0004-runner-fresh-binder-state-per-call.md) |
| B3 | serializer 未知節點型別 | `type(node).__name__`（如 `"DummyNode"`） | `nodeTypeName` 為編譯期 type switch，未知型別走 `default` 回傳 `""` | Go 無 runtime 型別名；實際 pipeline 不會產生未知節點，此為防禦性 default |
| B2 | JSON 特殊字元 | `U+2028` / `U+2029` 原樣輸出 | Go `encoding/json` 仍會 escape 為 ` ` / ` ` | [ADR 0002](./docs/adr/0002-byte-identical-ast-json.md) |
