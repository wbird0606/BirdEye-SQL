package birdeye

import "testing"

// TestLexerConformance：對照 _tokens.jsonl（Python baseline 對每個 harvested SQL
// 的 token 序列）。value 逐字比對、type 名稱逐字比對；預期錯誤只比對分類。
func TestLexerConformance(t *testing.T) {
	type rec struct {
		SQL    string     `json:"sql"`
		Tokens [][]string `json:"tokens"`
		Error  *errRec    `json:"error"`
	}
	corpus := readJSONL[rec](t, "_tokens.jsonl")

	var pass, fail int
	for _, r := range corpus {
		toks, err := NewLexer(r.SQL).Tokenize()

		if r.Tokens == nil { // Python 預期報錯
			if err == nil {
				fail++
				t.Errorf("SQL %q: 預期 %s error，卻成功", r.SQL, r.Error.Category)
				continue
			}
			if be, ok := err.(*Error); ok && r.Error != nil && be.Kind.String() != r.Error.Category {
				fail++
				t.Errorf("SQL %q: 錯誤分類 got %s want %s", r.SQL, be.Kind, r.Error.Category)
				continue
			}
			pass++
			continue
		}

		if err != nil {
			fail++
			t.Errorf("SQL %q: 非預期錯誤 %v", r.SQL, err)
			continue
		}
		if len(toks) != len(r.Tokens) {
			fail++
			t.Errorf("SQL %q: token 數 got %d want %d", r.SQL, len(toks), len(r.Tokens))
			continue
		}
		mismatch := false
		for i, want := range r.Tokens {
			if toks[i].Type.String() != want[0] || toks[i].Value != want[1] {
				mismatch = true
				t.Errorf("SQL %q token[%d]: got [%s %q] want [%s %q]",
					r.SQL, i, toks[i].Type, toks[i].Value, want[0], want[1])
			}
		}
		if mismatch {
			fail++
		} else {
			pass++
		}
	}
	t.Logf("lexer conformance: %d/%d SQL 通過", pass, pass+fail)
}
