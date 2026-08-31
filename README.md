# birdeye-go

[BirdEye-SQL](../birdeye_1150831) 引擎的 Go 移植。針對 MSSQL 的雙向 SQL ↔ AST
引擎：解析 → 語意分析（型別推導 + 零信任強制）→ 序列化 / 反向重建 / 意圖萃取 /
列層過濾注入。

Consumer：[`zta-proxy-go`](../zta-proxy-go) —— proxy 已可完全脫離 Python runtime。

## 現況

**Phase 1 完成**（核心 library）+ **CLI / web 儀表板**。狀態見 [PORTING.md](./PORTING.md)。

- 對照標準：Python `birdeye_1150831` 的 git tag `py-baseline-for-go-port`
- 忠實度：AST JSON / tree / mermaid / 重建 SQL 逐位元組一致；error 分類一致
- 47 個測試套件除 web/CLI（已補）外全部 1:1；覆蓋率 97.8%；conformance 0 fail
- 決策：[docs/adr/](./docs/adr/) · 詞彙：[CONTEXT.md](./CONTEXT.md) · 差異：[KNOWN_DEVIATIONS.md](./KNOWN_DEVIATIONS.md)

## 使用

### CLI（對照 Python `main.py`）

```sh
go build -o bin/birdeye ./cmd/birdeye

# SQL → AST
bin/birdeye -sql "SELECT AddressID, City FROM Address" -format tree
bin/birdeye -sql "SELECT * FROM Address" -format all         # tree + mermaid + json
bin/birdeye -file query.sql -csv data/output.csv -format json

# AST → SQL（反向重建）
bin/birdeye -ast '{"node_type":"SelectStatement","is_star":true,"table":{"node_type":"IdentifierNode","name":"Address","qualifiers":[]}}'
bin/birdeye -ast-file ast.json

# 參數：具名 or 位置（qmark）
bin/birdeye -sql "SELECT @p AS x" -params '{"@p": 30}'
bin/birdeye -sql "SELECT ?, ?" -params '["Taipei", 30]'
```

退出碼：`0` 成功 · `1` 語法/語意/系統錯誤 · `2` 參數錯誤。

### Web 儀表板（對照 Python `web/app.py`）

```sh
go run ./cmd/birdeye-web            # http://127.0.0.1:5000
go run ./cmd/birdeye-web -addr :8080 -csv data/output.csv
```

端點（前端 `cmd/birdeye-web/index.html` 直接沿用 Python 版）：

| 端點 | 說明 |
|---|---|
| `GET /` | 視覺化儀表板（Mermaid flowchart + AST tree + JSON + 反向重建）|
| `POST /api/parse` | `{sql, params?}` → `{status, result:{tree, mermaid, json}}` |
| `POST /api/reconstruct` | `{ast}`（物件或 JSON 字串）→ `{status, sql}` |
| `POST /api/upload_csv` | multipart `file` → 熱替換 metadata registry |
| `GET /health` | `{status:"ok"}` |

> `index.html` 由 CDN 載入 `mermaid` 與 `svg-pan-zoom`，需要網路。

## 開發

```sh
go test ./...            # 全部測試（含 cmd/）
go test ./... -run Conf  # 只跑 conformance golden 比對
go test ./... -cover
```

### 重新產生 conformance corpus

需要能 import Python baseline 的環境（`birdeye_1150831` 的 venv）：

```sh
BIRDEYE_BASELINE=../birdeye_1150831 \
  ../birdeye_1150831/.venv/Scripts/python tools/gen_fixtures.py
```

輸出至 `testdata/conformance/*.jsonl` 與 `testdata/conformance/_manifest.json`。
Corpus 應隨 baseline 變動而重新產生並 commit。

## 範圍

| | 內容 |
|---|---|
| ✅ 核心 | `token`/`lexer`、`parser`、`ast`、`registry`、`binder`、`serializer`、`reconstructor`、`intent`、`rowfilter`、`runner`（含 `RunScript` GO 批次）、`visualizer`、`mermaid` |
| ✅ CLI / web | `cmd/birdeye`、`cmd/birdeye-web` |
| ✅ 整合 | `zta-proxy-go` native analyser |
| 待辦 | 取代 `birdeye-svc` 的獨立 Go HTTP service；移除 `zta-proxy-go/python/birdeye_worker.py`、`birdeye-svc/` |
| 不移植 | pytest-benchmark、locust |
