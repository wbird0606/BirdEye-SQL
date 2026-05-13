# Clause Coverage Notes / Clause Coverage 說明

## What this document is for / 本文件用途

This file explains how to read the clause coverage report and why some clauses remain one-sided even after adding targeted tests.

本文件說明如何解讀 clause coverage 報告，以及為什麼即使加入了針對性測試，部分 clauses 仍可能維持單邊覆蓋。

## How to read the report / 如何閱讀報告

- `Fully covered` means both `True` and `False` outcomes were observed.
- `Only-True` means the clause has been seen as `True` but not yet as `False`.
- `Only-False` means the clause has been seen as `False` but not yet as `True`.
- `Never hit` means the clause was not executed at all.

- `Fully covered` 代表 `True` 與 `False` 兩種結果都已被觀察到。
- `Only-True` 代表 clause 曾被評估為 `True`，但尚未觀察到 `False`。
- `Only-False` 代表 clause 曾被評估為 `False`，但尚未觀察到 `True`。
- `Never hit` 代表該 clause 完全未執行。

## Why one-sided clauses happen / 為什麼會有單邊 clauses

Some one-sided clauses are genuine test gaps. Others are caused by normal control flow, such as:

有些單邊 clauses 真的代表測試缺口；另一些則是正常控制流程造成，例如：

- short-circuit evaluation in `and` / `or`
- defensive checks for invalid or unsupported input
- helper predicates that are naturally biased by the common path

- `and` / `or` 的短路求值
- 針對無效或不支援輸入的防禦式檢查
- 受主要流程影響而天生偏向單側的 helper predicate

## Current focus / 目前重點

The current work focuses on CACC-oriented test additions for parser and registry paths that can still be improved with correlated clause behavior.

目前工作重點是加入 CACC 導向測試，優先補強 parser 與 registry 中仍可透過 correlated clause 行為提升的路徑。

## Recent updates / 最近更新

- Added 12 Correlated Active Clause Coverage (CACC) tests targeting high-value one-sided clauses in parser, lexer, registry, and binder.
- Gap test file [tests/test_clause_coverage_gaps.py](tests/test_clause_coverage_gaps.py) now passes: 45 tests passed.

These tests focus on correlated clause behaviors such as parser alias matching (identifier vs reserved keyword vs EOF), registry `is_aggregate()` true/false/missing cases, lexer N-string and literal branches, and binder NULL/cast propagation paths.

本次新增的 12 個 CACC 測試涵蓋：parser alias matching（identifier / 保留字 / EOF）、registry 的 `is_aggregate()`（true/false/缺少函式）、lexer 的 N-string 與文字常數分支、以及 binder 的 NULL / cast 傳播路徑。Gap 測試檔目前 45 題皆通過。

## Related files / 相關檔案

- Report: [clause_coverage_report.md](clause_coverage_report.md)
- Coverage analysis: [tools/analyze_clause_coverage.py](tools/analyze_clause_coverage.py)
- Gap analysis helper: [tools/analyze_coverage_gaps.py](tools/analyze_coverage_gaps.py)
- Targeted tests: [tests/test_clause_coverage_gaps.py](tests/test_clause_coverage_gaps.py)