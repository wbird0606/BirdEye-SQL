# 0006 — 忠實複製 Python 的 quirk 與 bug

## 決策

移植途中若發現 Python [[baseline]] 的行為明顯是 bug（例：`reconstructor._sql_ExecStatement` 讀 `na['value']` 但 serializer 對 `named_args` 存的 key 是 `expr`；`intent_extractor` 某些節點型別漏走訪），Go 版**照 Python 現行行為複製（含 bug）**，把每一項記進 `KNOWN_DEVIATIONS.md`。達到 [[parity]] 後再另開 issue，一起修 Python + Go。

不採「Go 就地寫正確行為、該 golden fixture 標記為刻意不同」。

## 理由

Phase 1 的單一目標是 byte-parity。若一邊移植一邊修 bug，會不斷產生「到底哪邊才對」的判斷成本，也讓 [[conformance-corpus]] 失去「唯一標準」的地位。先讓兩邊完全一致，再以一個乾淨的 diff 一次修掉所有已知 bug，風險最低、可審計。

## Consequences

- `KNOWN_DEVIATIONS.md` 會累積一份「已知 Python bug」清單，本身就是 Phase 1 的有用產出。
- 少數為配合 Go 語言本質（如 [[0004]] 的 binder 狀態）產生的差異也記在同一份文件，但標明「非待修 bug」。
