# BirdEye-SQL

BirdEye-SQL 是一套針對 MSSQL (T-SQL) 的雙向 SQL ↔ AST 引擎：在零信任架構下依真實資料庫元數據驗證查詢，萃取欄位層級操作意圖，並能從 AST 反向重建 SQL。本 repo 是它的 Go 移植，對照標準為凍結的 Python [[baseline]]。

## Language

### 管線角色 (Pipeline Roles)

**Binder**:
對已解析的 AST 進行語意分析的管線階段 —— 涵蓋型別推導、名稱解析、以及 [[zta-enforcement]]。
_Avoid_: Analyzer, Resolver, Sema, Type Checker（各只涵蓋 Binder 職責的一部分）

**Serializer**:
把 AST 轉成 JSON 的管線階段。
_Avoid_: Marshaller, Encoder

**Reconstructor**:
把 AST JSON 反向轉回可執行 SQL 字串的管線階段。
_Avoid_: Generator, Printer, Unparser, Emitter

**Visualizer**:
把 AST 轉成帶型別標註的文字樹的管線階段。
_Avoid_: Tree Printer, Dumper

**Mermaid Exporter**:
把 AST 轉成 Mermaid 流程圖語法的管線階段。

**Runner**:
串接 Lexer → Parser → Binder → 各輸出階段的協調者，也是對外主要 API 入口。
_Avoid_: Engine, Pipeline, Processor, Facade

**Registry**:
資料表 schema 與內建函數元數據的唯一事實來源 (source of truth)，從 CSV 載入。
_Avoid_: Catalog, Schema Store, Metadata Provider

### 意圖分析 (Intent Analysis)

**Intent**:
一條 SQL 語句對「某個資料表欄位」執行的一種操作；權限系統以此逐欄比對。五種：READ、FILTER、INSERT、UPDATE、DELETE。
_Avoid_: Operation, Action, Permission；尤其避免 READ/WRITE/DELETE 三分法

**READ intent**:
欄位出現在 SELECT 投影清單（被直接讀取回傳）。

**FILTER intent**:
欄位出現在 WHERE / JOIN ON / HAVING / GROUP BY / ORDER BY，構成推理攻擊面，與投影讀取語意不同。
_Avoid_: 把這種情況也叫 READ

**Star Expansion**:
[[binder]] 依 [[registry]] 元數據把 `SELECT *` 或 `T.*` 展開成明確的欄位清單。
_Avoid_: Wildcard Expansion, Glob

**Star Intent Expansion**:
把一條 column 為空的 READ [[intent]]（來自 `SELECT *` 或 `COUNT(*)`）展開成每欄各一條 READ intent。與 [[star-expansion]] 是不同動作、不同階段。

### 零信任強制 (ZTA Enforcement)

**ZTA Enforcement**:
[[binder]] 執行的一組安全規則，預設拒絕 (deny-by-default)、失敗即擋 (fail-closed)。
_Avoid_: Validation, Security Check（太籠統）

**Alias Policy**:
一旦某資料表定義了別名，其原始表名即失效，之後只能以別名限定欄位。防「語意陰影 (semantic shadowing)」攻擊。

**Column Ambiguity Defense**:
JOIN 環境下，未限定的欄位若在多於一個資料表中存在即報錯，強制加限定符。

**Function Sandbox**:
內建函數採白名單；`xp_cmdshell`、`OPENROWSET` 等高風險系統函數與預存程序被封鎖。
_Avoid_: Function Whitelist（Sandbox 同時涵蓋封鎖清單）

**Mandatory WHERE**:
UPDATE / DELETE 若無 WHERE 子句，於解析階段即報錯。

**Structural Parameter**:
出現在 MSSQL 無法參數化之位置的 `@param`（如 `FROM @t`、`ORDER BY @col`、`GROUP BY @field`）。失敗即擋：只接受通過白名單的安全識別符值。
_Avoid_: Dynamic Identifier

### 名稱解析與作用域 (Name Resolution & Scope)

**Scope**:
[[binder]] 解析欄位／資料表名稱時的一層可見名稱集合。

**Scope Stack**:
巢狀 [[scope]] 的堆疊，對應 CTE、子查詢、[[derived-table]]、APPLY 的層級。

**Derived Table**:
FROM 或 JOIN 中帶別名的子查詢。其欄位只能透過別名參照，無法歸屬到來源資料表。
_Avoid_: Inline View, Subquery Table

**Virtual Schema**:
非來自 [[registry]] 的欄位 schema —— 即 CTE 或臨時表的投影欄位集合。

**Temp Schema**:
`#local` 或 `##global` 臨時表的 schema，於 bind 階段從 `SELECT ... INTO` 或 `CREATE TABLE #t` 動態註冊。

**Variable Scope**:
`DECLARE @v` / `SET @v` 宣告的變數及其型別。

**Nullable Propagation**:
追蹤哪些資料表的欄位因外連接 (LEFT / RIGHT / FULL JOIN、OUTER APPLY) 而變成可為 NULL。

### 型別與聚合 (Types & Aggregation)

**Inferred Type**:
[[binder]] 由下而上為每個運算式節點計算出的型別；未知時為 `UNKNOWN`。
_Avoid_: Resolved Type, Computed Type

**Aggregate Integrity**:
GROUP BY 規則 —— 投影清單中未被聚合的欄位必須出現在 GROUP BY 子句。
_Avoid_: GROUP BY Validation

### 參數 (Parameters)

**Parameter Input Mode**:
一次 Run 的參數傳入形式，三選一：`named`（`@name` + 物件）、`qmark`（位置 `?`，內部改寫為 `@P1..@Pn`）、`none`。

**Bound Params**:
外部參數名 → 推導型別 的對應。

**Bound Param Values**:
外部參數名 → 執行期實際值 的對應。

### 多語句 (Multi-Statement)

**Script**:
以 `;` 分隔的多條語句共構的單一根節點，供 `RunMulti` 使用；同一 Script 內的語句共享 [[temp-schema]] 與 [[variable-scope]]。
_Avoid_: Statement List, Program

**Batch**:
以單獨成行的 `GO` 分隔的語句群，供 `RunScript` 使用；批次之間共享 [[binder]] 狀態。
_Avoid_: GO Block

### 列層過濾 (Row-Level Security)

**Row Filter**:
權限系統回傳、需注入 WHERE 的一條述詞。欄位：Schema、Table、Column、Operator、ValueType（`LITERAL` 或 `SUBQUERY`）、Value。
_Avoid_: Row Predicate, RLS Rule, Filter Condition

**Row Filter Injection**:
把一組 [[row-filter]] 以 AND 併入目標語句 WHERE 子句的動作（作用於 SelectStatement / UpdateStatement / DeleteStatement，並遞迴子查詢）。

### 雙向轉換 (Bidirectional Transformation)

**Round-trip**:
SQL → [[serializer]] JSON → [[reconstructor]] → SQL 的一致性；本引擎的一級功能。

### 移植專屬 (Port-Specific)

**Baseline**:
被凍結並打上 tag `py-baseline-for-go-port` 的 Python commit。Go 版所有輸出以此為對照標準。
_Avoid_: Reference；不要與 [[registry]] 的「事實來源」混用

**Conformance Corpus**:
由 [[baseline]] 的 Python pipeline 產生的一批預期輸出（`ast_json` / `tree` / `mermaid` / `intents` / `reconstructed` / `error`），存於 `testdata/conformance/`。

**Golden Fixture**:
[[conformance-corpus]] 中的單一筆案例。

**Parity**:
Go 版達到「[[golden-fixture]] 全數通過（byte 一致 / error 分類一致），且核心 package 覆蓋率 ≥ Python」的狀態。
_Avoid_: Equivalence, Compatibility

**Known Deviation**:
Go 版刻意與 Python 不同之處 —— 通常是為先達成 byte-parity 而「忠實複製的 Python bug」，待 [[parity]] 後統一修正；記於 `KNOWN_DEVIATIONS.md`。
