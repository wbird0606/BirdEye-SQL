package birdeye

import (
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

// pipeRec 對照 pipeline fixture（parse / tree / mermaid / intents / reconstructed 各一階段）。
type pipeRec struct {
	ID            string   `json:"id"`
	Suite         string   `json:"suite"`
	Mode          string   `json:"mode"`
	SQL           string   `json:"sql"`
	Params        any      `json:"params"`
	BinderRan     bool     `json:"binder_ran"`
	Parse         stageRec `json:"parse"`
	Tree          stageRec `json:"tree"`
	Mermaid       stageRec `json:"mermaid"`
	Intents       stageRec `json:"intents"`
	Reconstructed stageRec `json:"reconstructed"`
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

// TestParseOnlyConformance：Go lex+prepare+parse+serialize 對照 Python parse_only
// 的 parse 階段輸出，逐位元組比對 ast_json（ADR 0002）。
func TestParseOnlyConformance(t *testing.T) {
	var total, pass, skip int
	fails := map[string]int{}

	for _, r := range allPipeFixtures(t) {
		if r.Mode != "parse_only" {
			continue
		}
		total++
		got, gerr := goParseSerialize(r.SQL, r.Params)

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
				pass++
			}
			continue
		}

		if gerr != nil {
			fails["非預期錯誤"]++
			t.Errorf("[%s] 非預期錯誤: %v\nSQL: %q", r.ID, gerr, r.SQL)
			continue
		}
		if got != r.Parse.ASTJSON {
			fails["ast_json 不符"]++
			t.Errorf("[%s] ast_json 不一致\nSQL: %q\n%s", r.ID, r.SQL, firstDiff(got, r.Parse.ASTJSON))
			continue
		}
		pass++
	}

	t.Logf("parse_only conformance: %d/%d pass（skip %d：Python system/hang）", pass, total, skip)
	if len(fails) > 0 {
		t.Errorf("失敗分類: %v", fails)
	}
}

func goParseSerialize(sql string, params any) (string, error) {
	prepared, _, _, err := prepareSQL(sql, params)
	if err != nil {
		return "", err
	}
	toks, err := NewLexer(prepared).Tokenize()
	if err != nil {
		return "", err
	}
	n, err := NewParser(toks, prepared).Parse()
	if err != nil {
		return "", err
	}
	return NewSerializer().ToJSON(n), nil
}

// firstDiff 回傳兩字串第一個相異處附近的片段。
func firstDiff(got, want string) string {
	n := min(len(got), len(want))
	i := 0
	for i < n && got[i] == want[i] {
		i++
	}
	lo := max(i-60, 0)
	ghi := min(i+80, len(got))
	whi := min(i+80, len(want))
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

func itoa(i int) string {
	if i == 0 {
		return "0"
	}
	neg := i < 0
	if neg {
		i = -i
	}
	var d []byte
	for i > 0 {
		d = append([]byte{byte('0' + i%10)}, d...)
		i /= 10
	}
	if neg {
		d = append([]byte{'-'}, d...)
	}
	return string(d)
}
