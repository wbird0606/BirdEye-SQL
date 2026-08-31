# 0002 — AST JSON 對 Python 做到 byte-identical，用手寫 ordered writer

## 決策

[[serializer]] 產出的 AST JSON 必須與 [[baseline]] 的 Python 輸出**逐位元組相同**，對照基準是 stdlib `json.dumps(obj, indent=2, ensure_ascii=False)`（已確認 `ujson` 未安裝）。實作方式：**不使用** `encoding/json` 的 struct tag / reflection marshal，改用 type switch + 明確的 ordered writer（`bytes.Buffer`），逐節點複製 Python 每種節點型別的 key 順序與條件輸出邏輯。Go 端 encoder 設 `SetEscapeHTML(false)`。

## 理由

這份 JSON 是跨行程契約：`GetIntents` 回傳 `ast_json` → `RewriteWithAST` 再吃回去 → [[row-filter-injection]] 直接改這個 dict。下游若做字串比對，任何差異都會炸。而 Python `_serialize` 的行為（「有值才輸出某個 key」、且 `inferred_type` / `bound_params` 這類 key 插在型別專屬 key **之前**）無法用 Go struct tag 乾淨表達；`encoding/json` 對 `map[string]any` 還會把 key 排序，更不可行。明確 ordered writer 是唯一能穩定對齊 byte 的做法，同時保住 Go 的型別安全（節點仍是具體 struct）。

## Consequences

- 已知無法對齊的邊角：Go 對 `U+2028` / `U+2029` 仍會 escape（`SetEscapeHTML(false)` 不涵蓋），Python 不會。若語料出現則列為 [[known-deviation]]。
- 新增節點型別時，Serializer 要手動補該型別的 key 順序；由 [[conformance-corpus]] 把關。
