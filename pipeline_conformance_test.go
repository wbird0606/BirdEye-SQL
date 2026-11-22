package birdeye

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// stageRec 對照 tools/gen_fixtures.py 的逐階段結果。
type stageRec struct {
	OK      bool    `json:"ok"`
	Value   any     `json:"value"`
	ASTJSON string  `json:"ast_json"` // 僅 parse 階段
	Error   *errRec `json:"error"`
}

// pipeRec 對照 pipeline fixture。
type pipeRec struct {
	ID            string          `json:"id"`
	Suite         string          `json:"suite"`
	Mode          string          `json:"mode"`
	SQL           string          `json:"sql"`
	Params        json.RawMessage `json:"params"`
	ParamOrder    []string        `json:"param_order"`
	BinderRan     bool            `json:"binder_ran"`
	Parse         stageRec        `json:"parse"`
	Tree          stageRec        `json:"tree"`
	Mermaid       stageRec        `json:"mermaid"`
	Intents       stageRec        `json:"intents"`
	Reconstructed stageRec        `json:"reconstructed"`
}

func allPipeFixtures(t *testing.T) []pipeRec {
	t.Helper()
	entries, err := os.ReadDir(conformanceDir)
	if err != nil {
		t.Skipf("缺少 %s: %v", conformanceDir, err)
	}
	var out []pipeRec
	for _, e := range entries {
		name := e.Name()
		if filepath.Ext(name) != ".jsonl" || name == "_tokens.jsonl" {
			continue
		}
		out = append(out, readJSONL[pipeRec](t, name)...)
	}
	return out
}

// fixtureParams 把 fixture 的 params 欄位解成 Runner 可用的形式。
// 具名物件用 param_order（原始 key 順序，fixture 本身被 sort_keys 打亂）還原順序。
func fixtureParams(t *testing.T, r pipeRec) any {
	t.Helper()
	s := strings.TrimSpace(string(r.Params))
	if s == "" || s == "null" {
		return nil
	}
	switch s[0] {
	case '[':
		var arr []any
		if err := json.Unmarshal(r.Params, &arr); err != nil {
			t.Fatalf("params array: %v", err)
		}
		return arr
	case '{':
		var vals map[string]any
		if err := json.Unmarshal(r.Params, &vals); err != nil {
			t.Fatalf("params object: %v", err)
		}
		keys := r.ParamOrder
		if keys == nil {
			dec := json.NewDecoder(bytes.NewReader(r.Params))
			dec.Token()
			for dec.More() {
				ktok, _ := dec.Token()
				keys = append(keys, ktok.(string))
				var v any
				dec.Decode(&v)
			}
		}
		return &OrderedParams{Keys: keys, Vals: vals}
	}
	return nil
}

type goPipe struct {
	astJSON string
	tree    string
	mermaid string
}

func TestParseOnlyConformance(t *testing.T) {
	runPipelineConformance(t, "parse_only", func(sql string, params any) (goPipe, error) {
		prepared, _, _, err := prepareSQL(sql, params)
		if err != nil {
			return goPipe{}, err
		}
		toks, err := NewLexer(prepared).Tokenize()
		if err != nil {
			return goPipe{}, err
		}
		n, err := NewParser(toks, prepared).Parse()
		if err != nil {
			return goPipe{}, err
		}
		aj := NewSerializer().ToJSON(n)
		return goPipe{aj, NewVisualizer().Dump(n), NewMermaidExporter().ExportJSON(aj)}, nil
	})
}

func TestRunConformance(t *testing.T) {
	reg := loadAdventureWorks(t)
	runPipelineConformance(t, "run", func(sql string, params any) (goPipe, error) {
		res, err := NewRunner(reg).Run(sql, params)
		if err != nil {
			return goPipe{}, err
		}
		return goPipe{res.JSON, res.Tree, res.Mermaid}, nil
	})
}

func TestRunMultiConformance(t *testing.T) {
	reg := loadAdventureWorks(t)
	runPipelineConformance(t, "run_multi", func(sql string, params any) (goPipe, error) {
		res, err := NewRunner(reg).RunMulti(sql, params)
		if err != nil {
			return goPipe{}, err
		}
		return goPipe{res.JSON, res.Tree, res.Mermaid}, nil
	})
}

func runPipelineConformance(t *testing.T, mode string, fn func(sql string, params any) (goPipe, error)) {
	var total, skip int
	pass := map[string]int{"ast_json": 0, "tree": 0, "mermaid": 0}
	fails := map[string]int{}

	for _, r := range allPipeFixtures(t) {
		if r.Mode != mode {
			continue
		}
		total++
		got, gerr := fn(r.SQL, fixtureParams(t, r))

		if !r.Parse.OK {
			if gerr == nil {
				fails["應報錯卻成功"]++
				t.Errorf("[%s] 應 %s error 卻成功\nSQL: %q", r.ID, r.Parse.Error.Category, r.SQL)
				continue
			}
			if r.Parse.Error.Category == "hang" || r.Parse.Error.Category == "system" {
				skip++
				continue
			}
			if be, ok := gerr.(*Error); ok && be.Kind.String() != r.Parse.Error.Category {
				fails["錯誤分類不符"]++
				t.Errorf("[%s] 錯誤分類 got %s want %s\nSQL: %q\nGo: %v\nPy: %s",
					r.ID, be.Kind, r.Parse.Error.Category, r.SQL, gerr, r.Parse.Error.Message)
			} else {
				pass["ast_json"]++
			}
			continue
		}

		if gerr != nil && isExecPolicyDeviation(gerr) {
			// 刻意偏離（KNOWN_DEVIATIONS A13）：預存程序預設拒絕，Python 基準版則放行任何非封鎖清單之 EXEC
			skip++
			continue
		}
		if gerr != nil {
			fails["非預期錯誤"]++
			t.Errorf("[%s] 非預期錯誤: %v\nSQL: %q", r.ID, gerr, r.SQL)
			continue
		}
		if knownAliasASTDeviation[r.ID] {
			// 刻意偏離（KNOWN_DEVIATIONS A8）：字面值別名與子查詢運算式別名現於 AST JSON 保留
			pass["ast_json"]++
		} else if got.astJSON != r.Parse.ASTJSON {
			fails["ast_json 不符"]++
			t.Errorf("[%s] ast_json 不一致\nSQL: %q\n%s", r.ID, r.SQL, firstDiff(got.astJSON, r.Parse.ASTJSON))
		} else {
			pass["ast_json"]++
		}
		if want, ok := r.Tree.Value.(string); ok && r.Tree.OK {
			if strings.Contains(want, "<birdeye.ast.") {
				// KNOWN_DEVIATIONS A3：Python 印物件 repr（含記憶體位址），本身不可重現
				skip++
			} else if got.tree != want {
				fails["tree 不符"]++
				t.Errorf("[%s] tree 不一致\nSQL: %q\n%s", r.ID, r.SQL, firstDiff(got.tree, want))
			} else {
				pass["tree"]++
			}
		}
		if want, ok := r.Mermaid.Value.(string); ok && r.Mermaid.OK {
			if got.mermaid != want {
				fails["mermaid 不符"]++
				t.Errorf("[%s] mermaid 不一致\nSQL: %q\n%s", r.ID, r.SQL, firstDiff(got.mermaid, want))
			} else {
				pass["mermaid"]++
			}
		}
	}

	t.Logf("%s conformance: ast_json %d · tree %d · mermaid %d（total %d, skip %d）",
		mode, pass["ast_json"], pass["tree"], pass["mermaid"], total, skip)
	if len(fails) > 0 {
		t.Errorf("失敗分類: %v", fails)
	}
}

// loadAdventureWorks 載入 testdata/output.csv（與 Python conftest 相同的 schema）。
func loadAdventureWorks(t *testing.T) *MetadataRegistry {
	t.Helper()
	data, err := os.ReadFile(filepath.Join("testdata", "output.csv"))
	if err != nil {
		t.Skipf("缺少 testdata/output.csv: %v", err)
	}
	reg := NewMetadataRegistry()
	if err := reg.LoadFromCSV(string(data)); err != nil {
		t.Fatalf("LoadFromCSV: %v", err)
	}
	return reg
}

// firstDiff 回傳兩字串第一個相異處附近的片段。
func firstDiff(got, want string) string {
	n := min(len(got), len(want))
	i := 0
	for i < n && got[i] == want[i] {
		i++
	}
	lo := max(i-60, 0)
	ghi := min(i+120, len(got))
	whi := min(i+120, len(want))
	var b strings.Builder
	b.WriteString("首個差異 @")
	b.WriteString(itoa(i))
	b.WriteString(" (got len ")
	b.WriteString(itoa(len(got)))
	b.WriteString(", want len ")
	b.WriteString(itoa(len(want)))
	b.WriteString(")\n--- got  ---\n")
	b.WriteString(got[lo:ghi])
	b.WriteString("\n--- want ---\n")
	b.WriteString(want[lo:whi])
	return b.String()
}
