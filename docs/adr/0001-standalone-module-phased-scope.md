# 0001 — 獨立 Go module、分階段範圍、達 parity 後淘汰 Python

## 決策

BirdEye-SQL 的 Go 版是一個**獨立 module**（`github.com/wbird0606/BirdEye-SQL`，單獨的本地 git repo，位於 `D:\1150513\birdeye-go\`），而非 `birdeye_1150831` 的子目錄，也不是塞進 `zta-proxy-go/internal/`。範圍分兩階段：

- **Phase 1（現行）**：移植 12 個核心模組成 library —— `token`/`lexer`、`parser`、`ast`、`registry`、`binder`、`serializer`、`reconstructor`、`intent_extractor`、`row_filter`、`runner`、`visualizer`、`mermaid_exporter`。
- **Phase 2（延後）**：Go CLI、取代 `birdeye-svc` 的 Go HTTP service、把 `zta-proxy-go` 的 `Analyser` 換成純 Go 實作並移除 Python subprocess worker。

Python 版 `birdeye` 在 Go 版達到 [[parity]] 並經一段觀察期後淘汰。

## 理由

`zta-proxy-go` 目前靠 Python subprocess（`python/birdeye_worker.py`）或 HTTP（`birdeye-svc`）呼叫 birdeye，容器內因此綁著 Python runtime。獨立 module 讓 `zta-proxy-go` 和未來的 Go `birdeye-svc` 都能以 `require` 引入同一份實作；平行目錄則讓凍結的 Python repo 留在旁邊當 [[baseline]] oracle 與 [[conformance-corpus]] 產生器的來源。

## Considered Options

- **子目錄 `birdeye_1150831/go/`**：與 Python 測試共處一室，但無法被其他 repo 乾淨引入，且混淆兩套語言的建置。
- **直接寫進 `zta-proxy-go/internal/`**：最快，但把 library 鎖死在單一 consumer，違背「未來 Go `birdeye-svc` 也要用」。
