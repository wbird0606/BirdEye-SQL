package birdeye

import (
	"encoding/json"
	"testing"
)

// TestRowFilterConformance：以 Python 的 ast_json 為輸入，Go inject + reconstruct
// 的 SQL 對照 Python（inject + to_sql）的輸出，逐位元組比對。
func TestRowFilterConformance(t *testing.T) {
	type rec struct {
		SQL        string            `json:"sql"`
		RowFilters []json.RawMessage `json:"row_filters"`
		ASTJSON    string            `json:"ast_json"`
		SQLOut     *string           `json:"sql_out"`
		Error      *errRec           `json:"error"`
	}
	corpus := readJSONL[rec](t, "_rowfilter.jsonl")
	if len(corpus) == 0 {
		t.Skip("無 _rowfilter.jsonl")
	}

	var pass int
	for _, r := range corpus {
		if r.SQLOut == nil {
			continue // Python 端錯誤，跳過
		}
		var filters []RowFilter
		for _, raw := range r.RowFilters {
			var f RowFilter
			if err := json.Unmarshal(raw, &f); err != nil {
				t.Fatalf("[%s] row_filter 解析: %v", r.SQL, err)
			}
			filters = append(filters, f)
		}
		var astDict map[string]any
		if err := json.Unmarshal([]byte(r.ASTJSON), &astDict); err != nil {
			t.Fatalf("[%s] ast_json: %v", r.SQL, err)
		}
		modified := NewRowFilterInjector().Inject(astDict, filters)
		got := NewReconstructor().ReconstructValue(modified)
		if got != *r.SQLOut {
			t.Errorf("[%s] rewrite SQL 不一致\n%s", r.SQL, firstDiff(got, *r.SQLOut))
			continue
		}
		pass++
	}
	t.Logf("row filter conformance: %d/%d pass", pass, len(corpus))
}
