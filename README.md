# BirdEye-SQL

[![Go CI](https://github.com/wbird0606/BirdEye-SQL/actions/workflows/go.yml/badge.svg)](https://github.com/wbird0606/BirdEye-SQL/actions/workflows/go.yml)

針對 MSSQL（T-SQL）的雙向 SQL ↔ AST 引擎（Go）：解析 → 語意分析（型別推導 + 零信任強制）→
序列化／反向重建／**欄位層級意圖萃取**／**列層過濾（Row Filter）注入**。

本專案是零信任資料庫存取代理 [ZTA-DBProxy](https://github.com/wbird0606/ZTA-DBProxy) 的 SQL 分析核心，
由其以 in-process 方式呼叫（`BIRDEYE_MODE=native`），也可獨立以 `cmd/birdeye-svc` 提供 HTTP 服務。

> **語言說明：** 本專案原為 Python 實作，現以 Go 為主要維護版本。最後一版 Python 實作保留於標籤
> [`python-final`](https://github.com/wbird0606/BirdEye-SQL/tree/python-final)，並作為 Go 版一致性測試
> （conformance）之基準。

## 功能

| 能力 | 說明 |
|---|---|
| 解析與語意分析 | MSSQL T-SQL 遞迴下降解析器；binder 做型別推導與別名／欄位解析，無法解析者 Fail-Closed |
| 意圖萃取 | 依 AST 語境將欄位存取分類為 `READ`／`FILTER`／`INSERT`／`UPDATE`／`DELETE` 五種操作屬性 |
| 列層過濾注入 | 對 AST 注入權限系統回傳之列過濾條件並重建 SQL；涵蓋外部 JOIN 可為 NULL 側、自我 JOIN、子查詢運算式、`INSERT … SELECT`、`MERGE … USING`、`UPDATE`／`DELETE` 之子查詢與目標表 |
| 語法覆蓋 | 含遞迴 CTE（含欄位清單）、帶 schema 限定之 `MERGE`、三段式欄位名稱、視窗函式、`CROSS APPLY` 等；尚不支援者見 [KNOWN_DEVIATIONS.md](./KNOWN_DEVIATIONS.md) |
| 整表操作政策 | 辨識 `DROP`／`CREATE`／`ALTER TABLE`、`TRUNCATE`、`SELECT … INTO` 與 `BULK INSERT` 並 Fail-Closed 拒絕 |
| Schema 快取 | `Analyser` 以 `(db_id, schema, table)` 為鍵快取欄位 schema，並合併併發之相同查詢，避免變更 SQL 字面值造成對權限服務之重複查詢 |

## 現況

- 對照標準：Python 版（標籤 `python-final`）；AST JSON／tree／mermaid／重建 SQL 逐位元組一致，error 分類一致。
- 測試：`go test ./...` 全數通過，根套件覆蓋率約 97%；conformance 以 golden corpus 為主要關卡（見 [ADR 0005](./docs/adr/0005-golden-conformance-corpus-primary-gate.md)）。
- 移植進度：[PORTING.md](./PORTING.md)
- 決策紀錄：[docs/adr/](./docs/adr/) · 詞彙：[CONTEXT.md](./CONTEXT.md) · 與 Python 版之差異：[KNOWN_DEVIATIONS.md](./KNOWN_DEVIATIONS.md)

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

需要能 import Python baseline 的環境（取出標籤 `python-final` 並建立其 venv）：

```sh
BIRDEYE_BASELINE=/path/to/BirdEye-SQL@python-final \
  /path/to/BirdEye-SQL@python-final/.venv/bin/python tools/gen_fixtures.py
```

輸出至 `testdata/conformance/*.jsonl` 與 `testdata/conformance/_manifest.json`。
Corpus 應隨 baseline 變動而重新產生並 commit。

## 範圍

| | 內容 |
|---|---|
| ✅ 核心 | `token`/`lexer`、`parser`、`ast`、`registry`、`binder`、`serializer`、`reconstructor`、`intent`、`rowfilter`、`runner`（含 `RunScript` GO 批次）、`visualizer`、`mermaid` |
| ✅ CLI / web / svc | `cmd/birdeye`、`cmd/birdeye-web`、`cmd/birdeye-svc`（取代 Python `birdeye-svc/`）|
| ✅ 整合 | [ZTA-DBProxy](https://github.com/wbird0606/ZTA-DBProxy)：`native`（in-process）與 `http`（→ `cmd/birdeye-svc`）共用 `birdeye.Analyser` |
| 不移植 | pytest-benchmark、locust |
