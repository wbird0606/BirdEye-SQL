// Package birdeye 是 BirdEye-SQL 引擎的 Go 移植：一套針對 MSSQL (T-SQL) 的
// 雙向 SQL ↔ AST 引擎，具備語意分析、零信任強制、欄位層級意圖萃取，
// 並能從 AST 反向重建 SQL。
//
// 領域詞彙見 CONTEXT.md；移植決策見 docs/adr/；進度見 PORTING.md。
// 所有輸出以凍結的 Python baseline（git tag py-baseline-for-go-port）為
// 逐位元組對照標準，刻意的差異記於 KNOWN_DEVIATIONS.md。
package birdeye

// Version 是本移植目前對齊的 Python baseline 標記。
const Version = "py-baseline-for-go-port"
