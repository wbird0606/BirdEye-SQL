# 0003 — 整個引擎放在單一 `birdeye` package

## 決策

Phase 1 的 12 個模組全部放在**單一 Go package `birdeye`**（`lexer.go`、`parser.go`、`ast.go`、`binder.go`、`serializer.go`、`reconstructor.go`、`registry.go`、`intent.go`、`rowfilter.go`、`visualizer.go`、`mermaid.go`、`runner.go`、`token.go`）。測試為白箱（`package birdeye`，`_test.go` 同 package）。

## 理由

Python `birdeye/` 是單一扁平 package，且有隱性循環依賴：[[binder]] 的 aggregate integrity 檢查會用序列化結果做節點結構比對（`binder → serializer`），而 `serializer`、`reconstructor`、`visualizer` 又都依賴 `ast`。拆成子 package 會撞上 Go 禁止循環 import，得先把節點結構比對抽進 `ast` 之類的重構 —— 對「1:1 快速對齊 Python」這個目標是純負擔。單一 package 讓移植與 Python 檔案一一對應，零循環問題。日後真有需要再拆。

白箱測試對應 Python 既有的白箱測試（多處直接存取 binder 內部狀態）。
