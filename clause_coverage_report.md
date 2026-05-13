# Clause Coverage Report / Clause Coverage 報告

## Summary / 摘要

This document summarizes the latest clause-level coverage analysis for the BirdEye-SQL codebase.

本文整理 BirdEye-SQL 最新的 clause-level coverage 分析結果。

## Latest Results / 最新結果

- Total clauses / 總 clause 數: 2,749
- Fully covered clauses / 完全覆蓋: 2,097
- Clause coverage / Clause 覆蓋率: 76%
- Only-True clauses / 只有 True: 433
- Only-False clauses / 只有 False: 219
- Never hit / 從未命中: 0

## Main Coverage Gaps / 主要覆蓋缺口

### High-frequency only-True clauses / 高頻 only-True clause

These clauses are frequently evaluated as `True` but never observed as `False` in the current test set.

這些 clause 在現有測試中經常被評估為 `True`，但尚未觀察到 `False`。

- `birdeye/parser.py` helper and routing conditions around line 47
- `birdeye/parser.py` branch-heavy parsing logic around lines 490, 572, 582, 775, 777, and 781
- `birdeye/registry.py` function metadata lookup around line 189

### High-frequency only-False clauses / 高頻 only-False clause

These clauses are frequently evaluated as `False` but never observed as `True` in the current test set.

這些 clause 在現有測試中經常被評估為 `False`，但尚未觀察到 `True`。

- `birdeye/lexer.py` N-string branch around line 270
- `birdeye/registry.py` function lookup and type checks around lines 184 and 191
- `birdeye/ast.py` constructor / validation branch around line 94
- `birdeye/parser.py` error-handling branch around line 71

## Why Some Clauses Stay One-Sided / 為什麼有些 clause 會單邊

Not every one-sided clause indicates a missing test. Common reasons include:

不是每個單邊 clause 都代表少測試。常見原因包括：

- Short-circuit evaluation in `and` / `or` expressions
- Defensive error paths that only run on invalid input
- Helper functions whose boolean result is biased by the normal execution path
- Test scenarios that exercise the main flow but not the opposite branch

## What Was Added / 已新增內容

Targeted tests were added in [tests/test_clause_coverage_gaps.py](tests/test_clause_coverage_gaps.py) to exercise:

已在 [tests/test_clause_coverage_gaps.py](tests/test_clause_coverage_gaps.py) 新增目標測試，用來覆蓋：


 Recent CACC-focused additions also cover parser alias matching with identifier / reserved-keyword / EOF combinations, plus registry `is_aggregate()` true / false / missing-function cases.

 ## Recent updates / 最近更新

 - Added 12 Correlated Active Clause Coverage (CACC) tests targeting high-value one-sided clauses in parser, lexer, registry, and binder.
 - Gap test file [tests/test_clause_coverage_gaps.py](tests/test_clause_coverage_gaps.py) now passes: 45 tests passed.

最近新增的 CACC 導向測試也涵蓋 parser alias matching 的 identifier / 保留字 / EOF 組合，以及 registry `is_aggregate()` 的 true / false / missing-function 路徑。

- Coverage gap analysis helper: [tools/analyze_coverage_gaps.py](tools/analyze_coverage_gaps.py)
- GitHub issue: https://github.com/wbird0606/BirdEye-SQL/issues/92

## Current Interpretation / 目前解讀

The project currently has a healthy clause coverage baseline, but a portion of the remaining one-sided clauses are caused by short-circuit behavior and defensive checks. The rest are genuine opportunities for additional edge-case tests.

目前專案已有不錯的 clause coverage 基礎，但剩餘的單邊 clause 有一部分是由短路求值與防禦式檢查造成；其餘則是真正值得補強的邊界測試機會。
