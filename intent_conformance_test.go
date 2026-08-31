package birdeye

import (
	"encoding/json"
	"testing"
)

// TestIntentConformance：以 Python 的 ast_json 為輸入，Go IntentExtractor
// （+ ExpandStarIntents）對照 Python 的 intents 清單，逐筆結構比對。
func TestIntentConformance(t *testing.T) {
	reg := loadAdventureWorks(t)
	var total, pass int
	fails := map[string]int{}

	for _, r := range allPipeFixtures(t) {
		if !r.Parse.OK || !r.Intents.OK {
			continue
		}
		want, ok := r.Intents.Value.([]any)
		if !ok && r.Intents.Value != nil {
			continue
		}
		total++

		parsed, err := parseAny(r.Parse.ASTJSON)
		if err != nil {
			fails["JSON 解析"]++
			continue
		}
		ie := NewIntentExtractor()
		got := ie.ExpandStarIntents(ie.Extract(parsed), reg)

		if len(got) != len(want) {
			fails["intent 數量"]++
			t.Errorf("[%s] intent 數 got %d want %d\nSQL: %q\ngot=%s", r.ID, len(got), len(want), r.SQL, dumpIntents(got))
			continue
		}
		mismatch := false
		for i := range got {
			w := want[i].(map[string]any)
			if !intentEq(got[i], w) {
				mismatch = true
				t.Errorf("[%s] intent[%d] got %+v want %v\nSQL: %q", r.ID, i, got[i], w, r.SQL)
			}
		}
		if mismatch {
			fails["intent 內容"]++
		} else {
			pass++
		}
	}

	t.Logf("intent conformance: %d/%d pass", pass, total)
	if len(fails) > 0 {
		t.Errorf("失敗分類: %v", fails)
	}
}

func intentEq(g Intent, w map[string]any) bool {
	if g.Schema != str(w["schema"]) || g.Table != str(w["table"]) || g.Intent != str(w["intent"]) {
		return false
	}
	wc := w["column"]
	if g.Column == nil {
		return wc == nil
	}
	s, ok := wc.(string)
	return ok && s == *g.Column
}

func parseAny(s string) (any, error) {
	var v any
	err := json.Unmarshal([]byte(s), &v)
	return v, err
}

func dumpIntents(is []Intent) string {
	b, _ := json.Marshal(is)
	return string(b)
}
