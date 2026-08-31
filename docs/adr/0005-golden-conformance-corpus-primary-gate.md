# 0005 — Golden conformance corpus 為主要 parity 關卡

## 決策

Go 版的忠實度以 **[[conformance-corpus]]** 為主要驗收關卡，而非把 1138 個 Python 測試逐一 1:1 移植當作前置條件。

- Python 腳本 `tools/gen_fixtures.py`（在本 repo，執行時 `PYTHONPATH` 指向 [[baseline]]）跑真正的 Python pipeline，把大量輸入的輸出（`ast_json` / `tree` / `mermaid` / `intents` / `reconstructed` / `error`）存成 `testdata/conformance/*.jsonl`。
- Go 測試對 `ast_json` / `tree` / `mermaid` / `reconstructed` 做 **byte 比對**，對 `error` 做 **分類比對**（syntax / semantic / value / ok）。
- 輸入語料：自動收割 41 個測試檔的 `@pytest.mark.parametrize` SQL + `run_script` 多語句 + params 案例 + 手挑補漏。
- 之後再逐步把 `test_*_suite.py` 1:1 移植成 `*_test.go`（table-driven、案例名對齊、訊息斷言放寬），但這在達到 parity 後持續進行，不阻擋里程碑。

**Phase 1 「[[parity]] 完成」= golden corpus 全綠 + 核心 package 覆蓋率 ≥ Python。**

## 理由

「先 golden 衝 parity、再逐步補 1:1」比「先花數週逐字翻譯 1138 個測試」更早拿到可驗證的忠實度訊號，也讓大面積的 serializer / reconstructor / intent 輸出比對用一個機制涵蓋。Python 測試套件本身仍是 1:1 移植的藍圖與最終覆蓋目標。

## 理由（不移植的部分）

`test_perf_benchmark.py`（pytest-benchmark 專屬）、`locustfile.py`、以及 Flask API 測試（`test_web_api` / `test_intent_api` / `test_denied_intent` / `test_intent_zta_flow`）不在 Phase 1；前者 Go 之後自寫 `Benchmark*`，後者屬 Phase 2 的 HTTP service。
