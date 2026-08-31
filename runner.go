package birdeye

import (
	"regexp"
	"strings"
)

// Runner 對照 Python birdeye/runner.py 的 BirdEyeRunner：串接
// Lexer → Parser → Binder → 各輸出階段。
//
// 與 Python 不同：Runner 只持有 immutable 的 registry；每次呼叫都建立全新的
// binder 狀態，因此 Run 天生併發安全（見 ADR 0004）。
type Runner struct {
	registry *MetadataRegistry
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
	bd := NewBinder(r.registry)
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
	bd := NewBinder(r.registry)
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
	bd := NewBinder(r.registry)
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
