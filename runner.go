package birdeye

import (
	"fmt"
	"regexp"
	"strings"
)

// Runner 對照 Python birdeye/runner.py 的 BirdEyeRunner：串接
// Lexer → Parser → Binder → 各輸出階段。
//
// 與 Python 不同：Runner 只持有 immutable 的 registry；每次呼叫都建立全新的
// binder 狀態，因此 Run 天生併發安全（見 ADR 0004）。
type Runner struct {
	registry     *MetadataRegistry
	allowedProcs map[string]bool // 預存程序白名單；nil = 預設拒絕
}

// ParseProcAllowList 將以逗號分隔之預存程序名稱（可含 schema，如 "dbo.usp_GetOrders"）轉為白名單。
func ParseProcAllowList(csv string) []string {
	var out []string
	for _, s := range strings.Split(csv, ",") {
		if s = strings.TrimSpace(s); s != "" {
			out = append(out, s)
		}
	}
	return out
}

// ValidateProcAllowList 檢查白名單是否含封鎖清單之程序（以名稱最後一段比對，如 master.dbo.xp_cmdshell）。
// 封鎖清單之程序無論如何都不得放行，列入白名單屬設定錯誤，應於啟動時即報錯而非靜默忽略。
func ValidateProcAllowList(names []string) error {
	var bad []string
	for _, n := range names {
		parts := strings.Split(strings.TrimSpace(n), ".")
		last := strings.Trim(parts[len(parts)-1], "[]\" ")
		if blockedProcs[strings.ToUpper(last)] {
			bad = append(bad, n)
		}
	}
	if len(bad) > 0 {
		return fmt.Errorf("procedure allow-list contains blocked procedure(s): %s", strings.Join(bad, ", "))
	}
	return nil
}

func procSet(names []string) map[string]bool {
	if len(names) == 0 {
		return nil
	}
	m := make(map[string]bool, len(names))
	for _, n := range names {
		m[strings.ToUpper(strings.TrimSpace(n))] = true
	}
	return m
}

// WithAllowedProcs 回傳帶有預存程序白名單之 Runner 副本；未呼叫則所有 EXEC（封鎖清單之外）皆被拒絕。
func (r *Runner) WithAllowedProcs(names []string) *Runner {
	cp := *r
	cp.allowedProcs = procSet(names)
	return &cp
}

func (r *Runner) newBinder() *Binder {
	b := NewBinder(r.registry)
	b.allowedProcs = r.allowedProcs
	return b
}

// Result 對照 Python run() 回傳的 dict。Binder 供白箱測試檢視 scope / nullable 狀態。
type Result struct {
	Status  string
	AST     Node
	Tree    string
	JSON    string
	Mermaid string
	Binder  *Binder
}

// NewRunner 建立 runner（可傳入既有 registry，否則新建）。
func NewRunner(registry *MetadataRegistry) *Runner {
	if registry == nil {
		registry = NewMetadataRegistry()
	}
	return &Runner{registry: registry}
}

// Registry 回傳底層 registry。
func (r *Runner) Registry() *MetadataRegistry { return r.registry }

// LoadMetadataFromCSV 對照 load_metadata_from_csv。
func (r *Runner) LoadMetadataFromCSV(csv string) error {
	return r.registry.LoadFromCSV(csv)
}

// Run 對照 run()：完整 pipeline，回傳 tree / json / mermaid。
func (r *Runner) Run(sql string, params any) (*Result, error) {
	prepared, mode, pin, err := prepareSQL(sql, params)
	if err != nil {
		return nil, err
	}
	toks, err := NewLexer(prepared).Tokenize()
	if err != nil {
		return nil, err
	}
	ast, err := NewParser(toks, prepared).Parse()
	if err != nil {
		return nil, err
	}
	bd := r.newBinder()
	bound, err := bd.Bind(ast, pin)
	if err != nil {
		return nil, err
	}
	if m := metaOf(bound); m != nil {
		m.ParamInputMode = string(mode)
	}
	res := r.outputs(bound)
	res.Binder = bd
	return res, nil
}

// RunMulti 對照 run_multi()：ScriptNode 為根，貫穿整個 pipeline。
func (r *Runner) RunMulti(sql string, params any) (*Result, error) {
	prepared, mode, pin, err := prepareSQL(sql, params)
	if err != nil {
		return nil, err
	}
	toks, err := NewLexer(prepared).Tokenize()
	if err != nil {
		return nil, err
	}
	script, err := NewParser(toks, prepared).ParseScript()
	if err != nil {
		return nil, err
	}
	bd := r.newBinder()
	bound, err := bd.Bind(script, pin)
	if err != nil {
		return nil, err
	}
	if m := metaOf(bound); m != nil {
		m.ParamInputMode = string(mode)
	}
	res := r.outputs(bound)
	res.Binder = bd
	return res, nil
}

var (
	goSepRE     = regexp.MustCompile(`(?im)^[ \t]*GO[ \t]*$`)
	stmtStartRE = regexp.MustCompile(`(?im)^[ \t]*(?:SELECT|INSERT|UPDATE|DELETE|TRUNCATE|DECLARE|WITH|IF|BEGIN|EXEC|EXECUTE|CREATE|DROP|ALTER|MERGE|PRINT|SET)\b`)
)

// splitStmtStart 對照 Python 的 _stmt_start.split(part)（lookahead 分割）：
// 在每個「語句起始關鍵字」出現前切開。
func splitStmtStart(part string) []string {
	locs := stmtStartRE.FindAllStringIndex(part, -1)
	if len(locs) == 0 {
		s := strings.TrimSpace(part)
		if s == "" {
			return nil
		}
		return []string{s}
	}
	var out []string
	// 第一個關鍵字之前若有非空內容，保留
	if pre := strings.TrimSpace(part[:locs[0][0]]); pre != "" {
		out = append(out, pre)
	}
	for i, loc := range locs {
		end := len(part)
		if i+1 < len(locs) {
			end = locs[i+1][0]
		}
		if s := strings.TrimSpace(part[loc[0]:end]); s != "" {
			out = append(out, s)
		}
	}
	return out
}

// RunScript 對照 run_script()：以獨立成行的 GO 分隔批次，批次內以 ; 及語句起始
// 關鍵字分割；同一個 Binder 貫穿整個腳本（variable_scope 跨批次保留）。
func (r *Runner) RunScript(sql string, params any) ([][]Node, error) {
	prepared, _, pin, err := prepareSQL(sql, params)
	if err != nil {
		return nil, err
	}
	bd := r.newBinder()
	var batches [][]Node
	for _, batchSQL := range goSepRE.Split(prepared, -1) {
		batchSQL = strings.TrimSpace(batchSQL)
		if batchSQL == "" {
			continue
		}
		var stmtsSQL []string
		for _, part := range strings.Split(batchSQL, ";") {
			stmtsSQL = append(stmtsSQL, splitStmtStart(part)...)
		}
		var batchASTs []Node
		for _, stmtSQL := range stmtsSQL {
			toks, err := NewLexer(stmtSQL).Tokenize()
			if err != nil {
				return nil, err
			}
			ast, err := NewParser(toks, stmtSQL).Parse()
			if err != nil {
				return nil, err
			}
			if _, err := bd.Bind(ast, pin); err != nil {
				return nil, err
			}
			batchASTs = append(batchASTs, ast)
		}
		batches = append(batches, batchASTs)
	}
	return batches, nil
}

// ParseOnly 對照 parse_only()：Lexer + Parser，跳過 Binder。
func (r *Runner) ParseOnly(sql string, params any) (Node, error) {
	prepared, _, _, err := prepareSQL(sql, params)
	if err != nil {
		return nil, err
	}
	toks, err := NewLexer(prepared).Tokenize()
	if err != nil {
		return nil, err
	}
	return NewParser(toks, prepared).Parse()
}

// ParseOnlyMulti 對照 parse_only_multi()。
func (r *Runner) ParseOnlyMulti(sql string, params any) (Node, error) {
	prepared, _, _, err := prepareSQL(sql, params)
	if err != nil {
		return nil, err
	}
	toks, err := NewLexer(prepared).Tokenize()
	if err != nil {
		return nil, err
	}
	return NewParser(toks, prepared).ParseScript()
}

func (r *Runner) outputs(bound Node) *Result {
	astJSON := NewSerializer().ToJSON(bound)
	return &Result{
		Status:  "success",
		AST:     bound,
		JSON:    astJSON,
		Tree:    NewVisualizer().Dump(bound),
		Mermaid: NewMermaidExporter().ExportJSON(astJSON),
	}
}
