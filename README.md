# birdeye-go

[BirdEye-SQL](../birdeye_1150831) 引擎的 Go 移植。針對 MSSQL 的雙向 SQL ↔ AST
引擎：解析 → 語意分析（型別推導 + 零信任強制）→ 序列化 / 反向重建 / 意圖萃取 /
列層過濾注入。

第一個 consumer 是 [`zta-proxy-go`](../zta-proxy-go)：移植完成後 proxy 可完全
脫離 Python runtime。

## 現況

**Phase 1 進行中** —— 移植核心 library。狀態見 [PORTING.md](./PORTING.md)。

- 對照標準：Python `birdeye_1150831` 的 git tag `py-baseline-for-go-port`
- 忠實度：AST JSON / tree / mermaid / 重建 SQL 逐位元組一致；error 分類一致
- 決策紀錄：[docs/adr/](./docs/adr/)
- 領域詞彙：[CONTEXT.md](./CONTEXT.md)
- 刻意的 Go ≠ Python 差異：[KNOWN_DEVIATIONS.md](./KNOWN_DEVIATIONS.md)

## 開發

```sh
go test ./...            # 全部測試
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
| Phase 1 | `token`/`lexer`、`parser`、`ast`、`registry`、`binder`、`serializer`、`reconstructor`、`intent`、`rowfilter`、`runner`、`visualizer`、`mermaid` |
| Phase 2 | Go CLI、取代 `birdeye-svc` 的 HTTP service、`zta-proxy-go` 整合並移除 Python worker |
| 不移植 | pytest-benchmark、locust、Flask API 測試套件 |
