package birdeye

import (
	"context"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Analyser 是「意圖分析 + row filter 改寫」的高階流程，對照 Python
// birdeye-svc/app.py 的 _get_intents / _rewrite_endpoint 與 birdeye_worker.py：
//
//   - GetIntents：兩遍分析。第一遍 parse-only 探索資料表 → 透過 SchemaFetcher
//     取得每個資料表的欄位 schema → 第二遍完整 pipeline（含 binder 型別推導）→
//     萃取欄位層級意圖 → 展開 SELECT * / COUNT(*) 的 table-level READ。
//   - Rewrite：把權限系統回傳的 RowFilter 注入已解析的 AST 並重建 SQL。
//
// SchemaFetcher 抽象了「向 Permission API 查欄位」這件事，因此本套件不需要知道
// HTTP 細節；standalone 服務（cmd/birdeye-svc）與 zta-proxy 各自注入實作。
type Analyser struct {
	fetch    SchemaFetcher
	cacheTTL time.Duration

	allowedProcs []string // 預存程序白名單（啟動時設定；空 = 預設拒絕所有 EXEC）

	mu    sync.Mutex
	cache map[string]analyserEntry
}

// SchemaColumn 是 Permission API 回傳的欄位描述。
type SchemaColumn struct {
	ColumnName string
	DataType   string
}

// SchemaFetcher 依 (dbID, schema, table) 取得欄位清單。
// 回傳 error 或空 slice 皆視為「該表查無 schema」——單表失敗不影響其他表（fail-soft，對照 Python）。
type SchemaFetcher func(ctx context.Context, dbID int, schema, table string) ([]SchemaColumn, error)

// AnalyserIntent 是對外（JSON）的意圖表示：column 為 nil 代表資料表層級。
type AnalyserIntent struct {
	Schema string  `json:"schema"`
	Table  string  `json:"table"`
	Column *string `json:"column"`
	Intent string  `json:"intent"`
}

// AnalyserResult 是 GetIntents 的輸出：意圖清單 + 序列化後的 AST（供 Rewrite 直接使用，免再 parse）。
type AnalyserResult struct {
	Intents []AnalyserIntent
	ASTJSON string
}

type analyserEntry struct {
	result AnalyserResult
	at     time.Time
}

// NewAnalyser 建立 Analyser。cacheTTL <= 0 表示不快取。
func NewAnalyser(fetch SchemaFetcher, cacheTTL time.Duration) *Analyser {
	// schema 查詢另以 (db_id, schema, table) 為鍵快取並合併併發請求（見 schemacache.go），
	// 使變更 SQL 字面值不致使每次未命中都重複查詢 Permission API。
	if fetch != nil {
		fetch = newSchemaCache(fetch, cacheTTL).get
	}
	return &Analyser{fetch: fetch, cacheTTL: cacheTTL, cache: map[string]analyserEntry{}}
}

// SetAllowedProcs 設定允許呼叫之預存程序白名單（名稱可含 schema，不分大小寫）。
// 須於開始處理請求前呼叫；未設定時，封鎖清單以外的 EXEC 一律被拒絕（Fail-Closed）。
func (a *Analyser) SetAllowedProcs(names []string) {
	a.allowedProcs = append([]string(nil), names...)
}

func (a *Analyser) getCache(key string) (AnalyserResult, bool) {
	if a.cacheTTL <= 0 {
		return AnalyserResult{}, false
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	e, ok := a.cache[key]
	if !ok || time.Since(e.at) >= a.cacheTTL {
		return AnalyserResult{}, false
	}
	return e.result, true
}

func (a *Analyser) setCache(key string, r AnalyserResult) {
	if a.cacheTTL <= 0 {
		return
	}
	a.mu.Lock()
	a.cache[key] = analyserEntry{result: r, at: time.Now()}
	a.mu.Unlock()
}

// GetIntents 對照 birdeye-svc 的 _get_intents。params 為 qmark 定位參數（[]any）。
func (a *Analyser) GetIntents(ctx context.Context, sql string, dbID int, params []any) (AnalyserResult, error) {
	cacheKey := sql + "\x00" + strconv.Itoa(dbID)
	if r, ok := a.getCache(cacheKey); ok {
		return r, nil
	}

	// Pass 1：不帶 schema，探索資料表
	var tables [][2]string
	if node, err := NewRunner(nil).ParseOnlyMulti(sql, listAny(params)); err == nil {
		var m any
		if json.Unmarshal([]byte(NewSerializer().ToJSON(node)), &m) == nil {
			tables = NewIntentExtractor().ExtractTables(m)
		}
	}

	// 向 SchemaFetcher 取每個資料表的欄位
	reg := NewMetadataRegistry()
	var lines []string
	tableCols := map[string][]string{} // UPPER(table) → 原始大小寫欄位名（fetch 順序），供 star 展開
	for _, tb := range tables {
		schema := tb[0]
		if schema == "" {
			schema = "dbo"
		}
		cols, err := a.fetch(ctx, dbID, schema, tb[1])
		if err != nil {
			continue // fail-soft
		}
		key := strings.ToUpper(tb[1])
		for _, c := range cols {
			dt := c.DataType
			if dt == "" {
				dt = "nvarchar"
			}
			lines = append(lines, schema+","+tb[1]+","+c.ColumnName+","+dt)
			if c.ColumnName != "" {
				tableCols[key] = append(tableCols[key], c.ColumnName)
			}
		}
	}
	if len(lines) > 0 {
		if err := reg.LoadFromCSV("table_schema,table_name,column_name,data_type\n" + strings.Join(lines, "\n")); err != nil {
			return AnalyserResult{}, fmt.Errorf("birdeye: load schema: %w", err)
		}
	}

	// Pass 2：完整 pipeline
	res, err := NewRunner(reg).WithAllowedProcs(a.allowedProcs).RunMulti(sql, listAny(params))
	if err != nil {
		return AnalyserResult{}, fmt.Errorf("birdeye: %w", err)
	}
	var astDict any
	if err := json.Unmarshal([]byte(res.JSON), &astDict); err != nil {
		return AnalyserResult{}, fmt.Errorf("birdeye: ast json: %w", err)
	}

	// 整表操作政策：本閘道管理之角色於資料庫層一律不獲授 DDL／ALTER 權限，且下列
	// 語句無法以列過濾（Row Filter）約束其影響範圍，故一經辨識即於意圖分析階段以
	// Fail-Closed 拒絕，不進入權限查核、亦不轉發至資料庫（即便夾帶於多語句批次）：
	//   - 針對持久資料表之 schema 變更：DROP／CREATE／ALTER TABLE
	//   - TRUNCATE TABLE：語意上等同無條件刪除全表，且需 ALTER 權限
	// 暫存資料表（#／##）非 schema 變更、亦無列過濾需求，不在此限。
	if k := findForbiddenTableStmt(astDict); k != "" {
		return AnalyserResult{}, semanticErr(k + " is not permitted by ZTA policy")
	}

	ie := NewIntentExtractor()
	raw := ie.Extract(astDict)

	// 展開 column=nil 的 READ（SELECT * / COUNT(*)）為逐欄意圖。
	// 對照 birdeye-svc/app.py：有 fetch 到 schema 時，用 fetch 回來的「原始大小寫」
	// 欄位名（table_cols）；否則退回 expand_star_intents（registry 大寫）。
	var intents []Intent
	if len(tableCols) > 0 {
		for _, it := range raw {
			if it.Column == nil && it.Intent == IntentRead {
				if cs := tableCols[strings.ToUpper(it.Table)]; len(cs) > 0 {
					for _, c := range cs {
						cc := c
						ni := it
						ni.Column = &cc
						intents = append(intents, ni)
					}
					continue
				}
			}
			intents = append(intents, it)
		}
	} else {
		intents = ie.ExpandStarIntents(raw, reg)
	}

	out := make([]AnalyserIntent, len(intents))
	for i, it := range intents {
		out[i] = AnalyserIntent{Schema: it.Schema, Table: it.Table, Column: it.Column, Intent: it.Intent}
	}
	result := AnalyserResult{Intents: out, ASTJSON: res.JSON}
	a.setCache(cacheKey, result)
	return result, nil
}

// Rewrite 對照 birdeye-svc 的 _rewrite_endpoint：
// 無 filter → 直接由 astJSON 重建；有 filter → 注入 WHERE 後重建。
// SUBQUERY 型別且 Value 為字串時，先以無 schema 的 runner 預先 parse（與 Python 一致，
// 該路徑受 schemaless binder 限制）。
func (a *Analyser) Rewrite(astJSON string, rowFilters []RowFilter) (sql string, err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("birdeye: rewrite panic: %v", r)
		}
	}()

	rc := NewReconstructor()
	if len(rowFilters) == 0 {
		return rc.Reconstruct(astJSON)
	}

	filters := make([]RowFilter, len(rowFilters))
	for i, rf := range rowFilters {
		bf := rf
		if strings.EqualFold(rf.ValueType, "SUBQUERY") {
			if s, ok := rf.Value.(string); ok {
				subRes, subErr := NewRunner(nil).Run(s, nil)
				if subErr != nil {
					return "", fmt.Errorf("birdeye: rewrite subquery: %w", subErr)
				}
				var subMap map[string]any
				if e := json.Unmarshal([]byte(subRes.JSON), &subMap); e != nil {
					return "", fmt.Errorf("birdeye: rewrite subquery json: %w", e)
				}
				bf.Value = subMap
			}
		}
		filters[i] = bf
	}

	var astMap map[string]any
	if e := json.Unmarshal([]byte(astJSON), &astMap); e != nil {
		return "", fmt.Errorf("birdeye: rewrite ast json: %w", e)
	}
	modified := NewRowFilterInjector().Inject(astMap, filters)
	return rc.ReconstructValue(modified), nil
}

// listAny：nil → 空 []any（qmark 定位參數）。
func listAny(p []any) any {
	if p == nil {
		return []any{}
	}
	out := make([]any, len(p))
	copy(out, p)
	return out
}

var forbiddenTableStmtKind = map[string]string{
	"DropTableStatement":   "DROP TABLE",
	"CreateTableStatement": "CREATE TABLE",
	"AlterTableStatement":  "ALTER TABLE",
	"TruncateStatement":    "TRUNCATE TABLE",
}

// findForbiddenTableStmt 遞迴尋找序列化 AST 中，針對「持久資料表」且本閘道政策
// 不允許之整表／結構操作，回傳其種類（如 "DROP TABLE"）；找不到則回空字串。
// 涵蓋：
//   - DROP／CREATE／ALTER TABLE、TRUNCATE TABLE
//   - SELECT ... INTO <persistent>（以查詢結果建立新資料表，屬 DDL）
//   - BULK INSERT（伺服器端檔案存取原語，與 OPENROWSET 同類）
//
// 暫存資料表（#local／##global）為 session 範疇，不計入。BirdEye 之 parser 僅
// 辨識上述少數 DDL 形式以維持文法完整性；其餘 DDL／DCL（CREATE VIEW、GRANT、
// BACKUP…）於 parser 階段即無法辨識而 Fail-Closed。
func findForbiddenTableStmt(node any) string {
	switch n := node.(type) {
	case map[string]any:
		nt := dstr(n, "node_type")
		if kind, ok := forbiddenTableStmtKind[nt]; ok && !ddlTargetIsTemp(n["table"]) {
			return kind
		}
		if nt == "SqlBulkCopyStatement" {
			return "BULK INSERT"
		}
		if nt == "SelectStatement" {
			if into, ok := n["into_table"].(map[string]any); ok && !ddlTargetIsTemp(into) {
				return "SELECT ... INTO"
			}
		}
		for _, v := range n {
			if k := findForbiddenTableStmt(v); k != "" {
				return k
			}
		}
	case []any:
		for _, v := range n {
			if k := findForbiddenTableStmt(v); k != "" {
				return k
			}
		}
	}
	return ""
}

func ddlTargetIsTemp(tbl any) bool {
	m, ok := tbl.(map[string]any)
	if !ok {
		return false
	}
	name, _ := m["name"].(string)
	return strings.HasPrefix(name, "#")
}
