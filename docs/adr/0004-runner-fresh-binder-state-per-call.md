# 0004 — Runner 持 immutable Registry，每次呼叫開全新 binder 狀態

## 決策

Go 版 `Runner` 只持有一個 immutable 的 [[registry]]。每次 `Run` / `RunMulti` / `RunScript` / `ParseOnly` / `ParseOnlyMulti` 呼叫都在內部建立**全新的 binder 狀態**（scope stack、[[temp-schema]]、[[variable-scope]]、nullable stack）。因此 `Run` 天生併發安全，多個 goroutine 可共用同一個 `Runner`。

Python `BirdEyeRunner` 持有一個有狀態的 `self._binder`，且 `bind()` 不重置 `temp_schemas` / `variable_scope` —— 兩次獨立 `run()` 呼叫之間狀態會外洩。**此外洩行為不移植。**

## 理由

查證 [[baseline]] 全部測試：沒有任何案例依賴跨 `run()` 呼叫的狀態持久化；所有跨語句狀態都活在單一 `run_script()` / `run_multi()` 呼叫內。而 `zta-proxy-go` 會多 goroutine 併發呼叫，需要一個併發安全的入口。保留持久 binder + mutex 能逐字對齊 Python，但會把併發請求序列化、失去併發效益，且對齊的是一個沒人依賴的 bug。

## Consequences

- 少數直接存取 binder 私有狀態的白箱測試（`_last_root_nullables`、`nullable_scopes`、`temp_schemas`）在移植時改為從 result 取值或改斷言方式，列入移植筆記。
- 這是一項刻意的 [[known-deviation]]，但因無測試依賴，不需事後「修正」。
