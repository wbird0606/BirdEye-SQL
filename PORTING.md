# Porting Progress

Baseline: `birdeye_1150831` @ `py-baseline-for-go-port` — **47 suite 檔 / 1216 test**。

狀態：⬜ 未開始 · 🟡 移植中 · 🟢 golden 綠 · ✅ 1:1 綠 · ⏭️ Phase 2 / 不移植

## 里程碑

| # | 里程碑 | 模組 | 狀態 |
|---|---|---|---|
| 0 | skeleton + fixture 產生器 + corpus | `tools/`, `testdata/` | ✅ |
| 1 | Lexer | `token.go` `lexer.go` `errors.go` | ✅ 16/16 unit + 846/846 conformance |
| 2 | AST 結構 | `ast.go` | ⬜ |
| 3 | Parser | `parser.go` | ⬜ |
| 4 | Serializer + JSON conformance 關卡 | `serializer.go` | ⬜ |
| 5 | Registry | `registry.go` | ⬜ |
| 6 | Binder | `binder.go` | ⬜ |
| 7 | Runner（Run / RunMulti / RunScript / ParseOnly*） | `runner.go` | ⬜ |
| 8 | Feature suites 廣度鋪開 | parser + binder | ⬜ |
| 9 | Reconstructor | `reconstructor.go` | ⬜ |
| 10 | Visualizer + Mermaid | `visualizer.go` `mermaid.go` | ⬜ |
| 11 | Intent Extractor | `intent.go` | ⬜ |
| 12 | Row Filter Injector | `rowfilter.go` | ⬜ |
| 13 | Integration + coverage 收尾 | — | ⬜ |
| 14 | Adversarial | — | ⬜ |

## Suite 對照表

| Suite | test | 目標模組 | 里程碑 | golden | 1:1 |
|---|---:|---|---|---|---|
| test_lexer_suite | 16 | lexer | 1 | 🟢 | ✅ |
| test_parser_suite | 23 | parser | 3 | ⬜ | ⬜ |
| test_parser_coverage_suite | 33 | parser | 3 | ⬜ | ⬜ |
| test_branch_phase2_parser_suite | 22 | parser | 3 | ⬜ | ⬜ |
| test_serializer_suite | 29 | serializer | 4 | ⬜ | ⬜ |
| test_schema_registry_suite | 22 | registry | 5 | ⬜ | ⬜ |
| test_semantic_suite | 32 | binder | 6 | ⬜ | ⬜ |
| test_binder_runner_coverage_suite | 17 | binder/runner | 6 | ⬜ | ⬜ |
| test_branch_phase1_suite | 7 | binder | 6 | ⬜ | ⬜ |
| test_branch_phase3_mixed_suite | 14 | mixed | 7 | ⬜ | ⬜ |
| test_select_features_suite | 44 | parser/binder | 8 | ⬜ | ⬜ |
| test_dml_suite | 39 | parser/binder | 8 | ⬜ | ⬜ |
| test_join_suite | 33 | parser/binder | 8 | ⬜ | ⬜ |
| test_subquery_suite | 32 | parser/binder | 8 | ⬜ | ⬜ |
| test_cte_suite | 10 | parser/binder | 8 | ⬜ | ⬜ |
| test_expressions_suite | 31 | parser/binder | 8 | ⬜ | ⬜ |
| test_functions_suite | 27 | binder/registry | 8 | ⬜ | ⬜ |
| test_window_functions_suite | 27 | parser/binder | 8 | ⬜ | ⬜ |
| test_new_syntax_suite | 46 | parser/binder | 8 | ⬜ | ⬜ |
| test_mssql_features_suite | 49 | parser/binder | 8 | ⬜ | ⬜ |
| test_mssql_boundary_suite | 54 | lexer/parser/binder | 8 | ⬜ | ⬜ |
| test_reconstructor_suite | 36 | reconstructor | 9 | ⬜ | ⬜ |
| test_reconstructor_coverage_suite | 31 | reconstructor | 9 | ⬜ | ⬜ |
| test_reconstructor_subquery_right | 1 | reconstructor | 9 | ⬜ | ⬜ |
| test_metadata_roundtrip_suite | 35 | serializer/reconstructor | 9 | ⬜ | ⬜ |
| test_visualizer_suite | 39 | visualizer | 10 | ⬜ | ⬜ |
| test_mermaid_suite | 3 | mermaid | 10 | ⬜ | ⬜ |
| test_74_star_intent_suite | 6 | intent | 11 | ⬜ | ⬜ |
| test_all_cases_intent_suite | 35 | intent | 11 | ⬜ | ⬜ |
| test_intent_extractor_suite | 16 | intent | 11 | ⬜ | ⬜ |
| test_intent_coverage_suite | 42 | intent | 11 | ⬜ | ⬜ |
| test_intent_coverage_extra | 20 | intent | 11 | ⬜ | ⬜ |
| test_intent_edge_cases_suite | 8 | intent | 11 | ⬜ | ⬜ |
| test_intent_edge_cases_2_suite | 9 | intent | 11 | ⬜ | ⬜ |
| test_row_filter_suite | 77 | rowfilter | 12 | ⬜ | ⬜ |
| test_integration_suite | 23 | runner | 13 | ⬜ | ⬜ |
| test_coverage_100_suite | 18 | mixed | 13 | ⬜ | ⬜ |
| test_final_coverage_suite | 54 | mixed | 13 | ⬜ | ⬜ |
| test_gap_to_100_suite | 10 | mixed | 13 | ⬜ | ⬜ |
| test_clause_coverage_gaps | 46 | mixed (CACC) | 13 | ⬜ | ⬜ |
| test_security_adversarial_suite | 52 | parser/binder | 14 | ⬜ | ⬜ |
| test_adversarial_appendix | 18 | parser/binder | 14 | ⬜ | ⬜ |
| test_cli_suite | 4 | — | — | ⏭️ Phase 2 | |
| test_web_api_suite | 9 | — | — | ⏭️ Phase 2 | |
| test_intent_api | 3 | — | — | ⏭️ Phase 2 | |
| test_intent_zta_flow | 2 | — | — | ⏭️ Phase 2 | |
| test_denied_intent | 2 | — | — | ⏭️ Phase 2 | |
| test_perf_benchmark | 10 | — | — | ⏭️ 不移植 | |

## Conformance corpus

`tools/gen_fixtures.py` 由 baseline 產生，存於 `testdata/conformance/*.jsonl`。
每個 harvested SQL × 3 mode（`parse_only` / `run` / `run_multi`）+ `_extra` 的 param 案例。

| 指標 | 值 |
|---|---|
| baseline commit | `94498cb` |
| fixture 檔數 | 46 pipeline + `_tokens`（846 SQL）|
| fixture 筆數 | 2840 pipeline（ok 1793 / err 1047）|
| Go 通過率 | lexer: 846/846 tokens；pipeline: 尚未（parser 進行中）|

> 註：許多 `run` / `run_multi` fixture 是 semantic error —— 測試檔用虛構資料表
> （`Users`、`Orders`）；這些 SQL 的 AST 只在 `parse_only` mode 有正輸出。

