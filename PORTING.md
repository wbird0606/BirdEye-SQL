# Porting Progress

Baseline: `birdeye_1150831` @ `py-baseline-for-go-port` — **47 suite 檔 / 1216 test**。

狀態：⬜ 未開始 · 🟡 移植中 · 🟢 golden 綠 · ✅ 1:1 綠 · ⏭️ Phase 2 / 不移植

## 里程碑

| # | 里程碑 | 模組 | 狀態 |
|---|---|---|---|
| 0 | skeleton + fixture 產生器 + corpus | `tools/`, `testdata/` | ✅ |
| 1 | Lexer | `token.go` `lexer.go` `errors.go` | ✅ 16/16 unit + 846/846 conformance |
| 2 | AST 結構 | `ast.go` | ✅（型別定義，由 parser/serializer 驗證）|
| 3 | Parser | `parser.go` `params.go` | ✅ 23/23 unit（+ conformance 見里程碑 4）|
| 4 | Serializer + parse_only conformance 關卡 | `serializer.go` | ✅ 29/29 unit + **936/942** parse_only byte 一致（6 skip = Python system/hang）|
| 5 | Registry | `registry.go` | ✅ 14/14 unit |
| 6 | Binder | `binder.go` | ✅ 18/18 unit + run 945/951 · run_multi 941/947 conformance |
| 7 | Runner | `runner.go` `params.go` | ✅ Run/RunMulti/RunScript/ParseOnly* |
| 8 | Feature suites（廣度） | parser + binder | ✅ conformance 涵蓋 + features_test.go 高價值斷言 |
| 9 | Reconstructor | `reconstructor.go` | ✅ 1796/1796 conformance + 1:1 |
| 10 | Visualizer + Mermaid | `visualizer.go` `mermaid.go` `ordered_json.go` | ✅ conformance byte 一致 + 1:1 |
| 11 | Intent Extractor | `intent.go` `ordered_json.go` | ✅ 1796/1796 conformance + 7 套件全 1:1 |
| 12 | Row Filter Injector | `rowfilter.go` | ✅ 77 unit + 10/10 端到端 conformance |
| 13 | Integration + coverage 收尾 | — | ✅ Go 覆蓋率 **97.5%**；整合/coverage 套件全 1:1 |
| 14 | Adversarial | — | ✅ 70 案例 1:1（security_adversarial + appendix）|

**Phase 1 核心 12 模組已全部移植**，所有 conformance 關卡 0 fail（見下）。
**1:1 測試套件 backfill 完成**：全部 47 個可移植套件皆有專屬對照檔案（web/CLI 亦補齊）。
Go 覆蓋率 93.5% → **97.5%**（RunScript 為新增功能，非移植缺口）。

## Phase 2 整合（`zta-proxy-go`）

`../zta-proxy-go` 新增 `internal/birdeye/native.go`：`NativeAnalyser` 以 in-process 的
birdeye-go 實作 proxy 的 `Analyser` 介面，取代 Python subprocess worker
（`python/birdeye_worker.py`），proxy 不再需要 Python runtime。

- `GetIntents` 兩遍流程對照 `birdeye_worker.py._get_intents`：
  `ParseOnlyMulti → ExtractTables → GET /api/zta/columns → LoadFromCSV → RunMulti →
  Extract → ExpandStarIntents`（star 展開採 canonical 的 `birdeye-svc/app.py` 行為，
  worker 少這步）。TTL 記憶體快取，鍵為 `sql\x00dbId`。
- `RewriteWithAST` 對照 `_rewrite_with_ast`：無 filter → `Reconstruct`；有 filter →
  `RowFilterInjector.Inject` + `ReconstructValue`，SUBQUERY 字串值先以無 schema runner 預先 parse。
- `cmd/proxy/main.go` 新增 `BIRDEYE_MODE` switch：`native`（預設）/ `http` / `subprocess`。
- Dockerfile 改為純 Go 映像（移除 Python 3.11 stage）。
- 測試：`internal/birdeye/native_test.go`（7）+ `internal/handler/execute_native_test.go`（4，
  端到端經 JWT ticket → 意圖分析 → 權限檢查 → row filter 改寫 → 執行）。`go test ./...` 全綠（38）。

### Phase 2 CLI / web（已補）

- **`cmd/birdeye`** —— 對照 `main.py`：`-sql`/`-file`/`-ast`/`-ast-file`、`-csv`、
  `-format tree|mermaid|json|all`、`-params`（具名 or qmark 陣列）、`-params-file`。
  退出碼 0/1/2。`main_test.go` 7 測試（對照 `test_cli_suite`）。
- **`cmd/birdeye-web`** —— 對照 `web/app.py`：`GET /`（沿用 `index.html`）、
  `POST /api/parse`、`POST /api/reconstruct`、`POST /api/upload_csv`（熱替換 registry）、
  `GET /health`。輸出經比對與 Python web **byte 一致**。`main_test.go` 15 測試
  （對照 `test_web_api_suite` + upload/health/index）。

### Phase 2 standalone HTTP 服務（已補）

- **`birdeye.Analyser`**（`analyser.go`）—— 高階「意圖分析 + row filter 改寫」流程，
  對照 Python `birdeye-svc/app.py` 的 `_get_intents` / `_rewrite_endpoint`。
  `SchemaFetcher` 抽象「向 Permission API 查欄位」；SELECT * / COUNT(*) 的 star 展開
  在有 fetch 到 schema 時用「原始大小寫」欄位名（birdeye-svc 行為），否則退回
  `ExpandStarIntents`。`analyser_test.go` 6 測試。
- **`cmd/birdeye-svc`** —— 純 Go HTTP 服務，取代 Python `birdeye-svc/`。端點
  `POST /intents`、`POST /rewrite`、`GET /health`（與 proxy 的 `internal/birdeye/client.go`
  契約一致）。`main_test.go` 5 測試。Dockerfile（純 Go 映像）。
- **`zta-proxy-go/internal/birdeye/native.go`** 重構為 `bird.Analyser` 的薄轉接層
  （223 → ~100 行，邏輯 DRY）。
- 與 Python `birdeye-svc` 的 `/intents` + `/rewrite` 輸出經跨進程比對**逐位元組一致**
  （含 COUNT(*)、SELECT *、GROUP BY、CROSS APPLY）。

仍待辦：移除 `zta-proxy-go/python/birdeye_worker.py`、Python `birdeye-svc/` 目錄（清理）。

## Suite 對照表

| Suite | test | 目標模組 | 里程碑 | golden | 1:1 |
|---|---:|---|---|---|---|
| test_lexer_suite | 16 | lexer | 1 | 🟢 | ✅ |
| test_parser_suite | 23 | parser | 3 | 🟢 | ✅ |
| test_parser_coverage_suite | 33 | parser | 3 | 🟢 | ✅ |
| test_branch_phase2_parser_suite | 22 | parser | 3 | 🟢 | ✅ |
| test_serializer_suite | 29 | serializer | 4 | 🟢 | ✅ |
| test_schema_registry_suite | 22 | registry | 5 | 🟢 | 🟡 (binder 部分待 M6) |
| test_semantic_suite | 32 | binder | 6 | 🟢 | ✅ (28/32；4 需 visualizer) |
| test_binder_runner_coverage_suite | 17 | binder/runner | 6 | 🟢 | ✅ |
| test_branch_phase1_suite | 7 | binder | 6 | 🟢 | ✅ |
| test_branch_phase3_mixed_suite | 14 | mixed | 7 | 🟢 | ✅ |
| test_select_features_suite | 44 | parser/binder | 8 | 🟢 | ✅ |
| test_dml_suite | 39 | parser/binder | 8 | 🟢 | ✅ |
| test_join_suite | 33 | parser/binder | 8 | 🟢 | ✅ |
| test_subquery_suite | 32 | parser/binder | 8 | 🟢 | ✅ |
| test_cte_suite | 10 | parser/binder | 8 | 🟢 | ✅ |
| test_expressions_suite | 31 | parser/binder | 8 | 🟢 | ✅ |
| test_functions_suite | 27 | binder/registry | 8 | 🟢 | ✅ |
| test_window_functions_suite | 27 | parser/binder | 8 | 🟢 | ✅ |
| test_new_syntax_suite | 46 | parser/binder | 8 | 🟢 | ✅ |
| test_mssql_features_suite | 49 | parser/binder | 8 | 🟢 | ✅ |
| test_mssql_boundary_suite | 54 | lexer/parser/binder | 8 | 🟢 | ✅ |
| test_reconstructor_suite | 36 | reconstructor | 9 | 🟢 | ✅ |
| test_reconstructor_coverage_suite | 31 | reconstructor | 9 | 🟢 | ✅ |
| test_reconstructor_subquery_right | 1 | reconstructor | 9 | 🟢 | ✅ |
| test_metadata_roundtrip_suite | 35 | serializer/reconstructor | 9 | 🟢 | ✅ |
| test_visualizer_suite | 39 | visualizer | 10 | 🟢 | ✅ |
| test_mermaid_suite | 3 | mermaid | 10 | 🟢 | ✅ |
| test_74_star_intent_suite | 6 | intent | 11 | 🟢 | ✅ |
| test_all_cases_intent_suite | 35 | intent | 11 | 🟢 | ✅ |
| test_intent_extractor_suite | 16 | intent | 11 | 🟢 | ✅ |
| test_intent_coverage_suite | 42 | intent | 11 | 🟢 | ✅ |
| test_intent_coverage_extra | 20 | intent | 11 | 🟢 | ✅ |
| test_intent_edge_cases_suite | 8 | intent | 11 | 🟢 | ✅ |
| test_intent_edge_cases_2_suite | 9 | intent | 11 | 🟢 | ✅ |
| test_row_filter_suite | 77 | rowfilter | 12 | 🟢 | ✅ |
| test_integration_suite | 23 | runner | 13 | 🟢 | ✅ |
| test_coverage_100_suite | 18 | mixed | 13 | 🟢 | ✅ |
| test_final_coverage_suite | 54 | mixed | 13 | 🟢 | ✅ |
| test_gap_to_100_suite | 10 | mixed | 13 | 🟢 | ✅ |
| test_clause_coverage_gaps | 46 | mixed (CACC) | 13 | 🟢 | ✅ (web/app 端點 ⏭️ Phase 2) |
| test_security_adversarial_suite | 52 | parser/binder | 14 | 🟢 | ✅ |
| test_adversarial_appendix | 18 | parser/binder | 14 | 🟢 | ✅ |
| test_cli_suite | 4 | cmd/birdeye | P2 | 🟢 | ✅ |
| test_web_api_suite | 9 | cmd/birdeye-web | P2 | 🟢 | ✅ |
| test_intent_api | 3 | cmd/birdeye-web | P2 | 🟢 | ✅ |
| test_intent_zta_flow | 2 | cmd/birdeye-web | P2 | 🟢 | ✅ (非 ZTA-proxy skip 部分) |
| test_denied_intent | 2 | cmd/birdeye-web | P2 | 🟢 | ✅ (非 ZTA-proxy skip 部分) |
| test_perf_benchmark | 10 | — | — | ⏭️ 不移植 | |

## Conformance corpus

`tools/gen_fixtures.py` 由 baseline 產生，存於 `testdata/conformance/*.jsonl`。
每個 harvested SQL × 3 mode（`parse_only` / `run` / `run_multi`）+ `_extra` 的 param 案例。

baseline commit `94498cb`。逐階段記錄（parse / tree / mermaid / intents / reconstructed）。

| 關卡 | Go vs Python baseline |
|---|---|
| lexer tokens | **846 / 846** |
| parse_only `ast_json` | **936 / 942**（6 = Python system/hang）|
| run `ast_json` | **945 / 951** |
| run_multi `ast_json` | **941 / 947** |
| tree（visualizer） | 全 parse-OK fixture byte 一致 |
| mermaid | 全 parse-OK fixture byte 一致 |
| reconstruct（AST JSON → SQL） | **1796 / 1796** |
| intents | **1796 / 1796** |
| row filter（inject + reconstruct） | **10 / 10** |

**0 fail。** skip 僅限 Python 端 system 例外 / 無限迴圈 / 不可重現的物件 repr
（見 `KNOWN_DEVIATIONS.md` A1–A3）。

> 註：許多 `run` / `run_multi` fixture 是 semantic error —— 測試檔用虛構資料表
> （`Users`、`Orders`）；這些 SQL 的 AST 只在 `parse_only` mode 有正輸出。

## Go 測試

- ~180 個 top-level 測試函式，數百個 table-driven / 子測試；`go test ./...` 全綠（含 `-shuffle=on`）
- 已 1:1 移植（36 個測試檔）：lexer · parser（+ coverage + branch_phase2）· serializer ·
  registry · semantic · reconstructor（suite + coverage + subquery_right + metadata_roundtrip）·
  visualizer · mermaid · intent（全 7 套件）· rowfilter · **security_adversarial + appendix（70）** ·
  dml · integration · branch_phase1/3 · binder_runner_coverage ·
  coverage_100 · gap_to_100 · final_coverage · clause_coverage_gaps ·
  expressions · functions · window · mssql_boundary（features_test.go）
- 全部 47 個可移植套件皆有專屬 1:1 檔案：dml/join/subquery/cte/new_syntax/mssql_features/
  select_features/**functions/window/mssql_boundary**/expressions/reconstructor×4/visualizer/
  mermaid/intent×7/整合/coverage×4/branch×3/binder_runner/adversarial/lexer/parser/serializer/
  registry/semantic/rowfilter/metadata_roundtrip/cli/web_api。
  `features_test.go` 保留為額外的高價值跨套件斷言。
- **覆蓋率 97.5%**（Python baseline: 100% line；`cmd/` 為 66–67%，屬 main() 膠水碼）

### 剩餘覆蓋率缺口（~2.2%）

皆為 Go 語言本質的防禦性分支：`bindSet` 的變數型別 fallback、深層遞迴的型別不符
早退（`deepEqualJ` / `serialize2`）、罕見 lexer/parser 錯誤路徑。另 `baseNode.aNode()` /
`nodeList.aNode()` 為空函式體的 interface marker，Go cover 工具不插入計數器 → 永遠 0%
（Python 無 marker method 對應）。conformance 0 fail（見上）是比行覆蓋率更強的忠實度保證。

