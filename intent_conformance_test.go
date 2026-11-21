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
		if knownMergeSourceDeviation[r.ID] || knownCTENameDeviation[r.ID] {
			// 刻意偏離 Python 基準（KNOWN_DEVIATIONS A4）：MERGE 來源為資料表時，
			// Go 將來源欄位意圖歸屬於真實資料表，而非別名。行為由 recursive_merge_test.go 鎖定。
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

// knownMergeSourceDeviation：Python 基準將 MERGE 來源表之欄位意圖掛在別名下（等於授權時查無此表）；
// Go 修正為真實資料表。見 KNOWN_DEVIATIONS.md A4。
var knownMergeSourceDeviation = map[string]bool{
	"test_new_syntax_suite:af30b8ca76d3":      true,
	"test_new_syntax_suite:ddd0bbcc542c":      true,
	"test_parser_coverage_suite:4bc89461e867": true,
	"test_parser_coverage_suite:94f24aadebe4": true,
	"test_parser_coverage_suite:d1680cbb752c": true,
}

// knownCTENameDeviation：Python 基準把「經由 CTE 讀取之欄位」以 CTE 名稱當資料表列為意圖（schema 為空）；
// 權限服務對無權限列之資料表一律拒絕，導致所有 CTE 查詢被 403。Go 修正為不輸出 CTE 名稱，
// CTE 內部讀取之真實資料表意圖不變。見 KNOWN_DEVIATIONS.md A5。
var knownCTENameDeviation = map[string]bool{
	"test_binder_runner_coverage_suite:adf1b8433d9a": true,
	"test_binder_runner_coverage_suite:d320d5035834": true,
	"test_cte_suite:1bf50d9a6608":                    true,
	"test_cte_suite:4db965af6c05":                    true,
	"test_cte_suite:b465ad685cc7":                    true,
	"test_cte_suite:ba0d20f5c1ad":                    true,
	"test_cte_suite:c21c04ef609c":                    true,
	"test_cte_suite:d5b1c18bf0d5":                    true,
	"test_final_coverage_suite:61f6ff8e8ef4":         true,
	"test_intent_coverage_extra:71ac188cd38d":        true,
	"test_intent_coverage_extra:999cc4bddee2":        true,
	"test_intent_extractor_suite:ab330e6516f0":       true,
	"test_intent_extractor_suite:ef8c46b2752b":       true,
	"test_reconstructor_suite:01ac0604946a":          true,
	"test_reconstructor_suite:d6cb0900e2f4":          true,
	"test_serializer_suite:6e30fdc3467e":             true,
	"test_serializer_suite:ff72d1edc73a":             true,
	"test_visualizer_suite:85af018587e2":             true,
	"test_visualizer_suite:d131b6d9ff74":             true,
}

// knownAliasASTDeviation：Python 基準於序列化時遺失字面值欄位別名與子查詢運算式別名；Go 保留。見 KNOWN_DEVIATIONS.md A8。
var knownAliasASTDeviation = map[string]bool{
	"_extra:d82708eefc36":                            true,
	"test_cte_suite:1bf50d9a6608":                    true,
	"test_cte_suite:bd266cf23d22":                    true,
	"test_cte_suite:c21c04ef609c":                    true,
	"test_intent_coverage_extra:50c454e569c6":        true,
	"test_intent_coverage_extra:6a3cc3b0dce4":        true,
	"test_intent_coverage_extra:8d37da29b61e":        true,
	"test_intent_edge_cases_suite:12f7c517c82e":      true,
	"test_intent_edge_cases_suite:e0baafaa8380":      true,
	"test_intent_edge_cases_suite:ef42491aa1f8":      true,
	"test_mssql_boundary_suite:3da07e0c9e01":         true,
	"test_mssql_boundary_suite:58dadbabebd0":         true,
	"test_mssql_boundary_suite:5f2c89d7dce4":         true,
	"test_mssql_boundary_suite:8c58b4ae06b4":         true,
	"test_mssql_boundary_suite:ef0ceea439a8":         true,
	"test_mssql_boundary_suite:f136407c4a2f":         true,
	"test_reconstructor_coverage_suite:22018fa1e404": true,
	"test_reconstructor_coverage_suite:3f00eff43556": true,
	"test_reconstructor_coverage_suite:8db2df26e277": true,
	"test_reconstructor_coverage_suite:9758635b7683": true,
	"test_reconstructor_coverage_suite:e45c7fbc7b5c": true,
	"test_reconstructor_coverage_suite:fe84acefab7a": true,
	"test_select_features_suite:7a6181c0ff4a":        true,
	"test_select_features_suite:8b2da13e7f2f":        true,
	"test_select_features_suite:e8deba43540d":        true,
	"test_serializer_suite:6e30fdc3467e":             true,
	"test_serializer_suite:dd11453e2b2b":             true,
	"test_serializer_suite:ff72d1edc73a":             true,
	"test_visualizer_suite:596b5aa1dd4f":             true,
	"test_visualizer_suite:5f2c89d7dce4":             true,
	"test_visualizer_suite:85af018587e2":             true,
	"test_visualizer_suite:d131b6d9ff74":             true,
	"test_visualizer_suite:ef0ceea439a8":             true,
	"test_visualizer_suite:f136407c4a2f":             true,
}

// knownReconstructDeviation：基準之重建輸出於子查詢運算式尾端多出內層資料表別名、缺括號，或遺失字面值別名；Go 修正。見 KNOWN_DEVIATIONS.md A7、A8。
var knownReconstructDeviation = map[string]bool{
	"test_binder_runner_coverage_suite:31fb4a9740c9": true,
	"test_binder_runner_coverage_suite:930378adae24": true,
	"test_binder_runner_coverage_suite:bcb72fc06b36": true,
	"test_intent_edge_cases_2_suite:249d6aa0f608":    true,
	"test_intent_edge_cases_2_suite:2bda1da6cda0":    true,
	"test_intent_edge_cases_2_suite:52e12240d5de":    true,
	"test_intent_edge_cases_2_suite:8e9d03f85fc1":    true,
	"test_intent_edge_cases_2_suite:ae522ab2ee6f":    true,
	"test_intent_edge_cases_2_suite:f9e4d23ac700":    true,
	"test_intent_edge_cases_suite:12f7c517c82e":      true,
	"test_intent_edge_cases_suite:e0baafaa8380":      true,
	"test_intent_edge_cases_suite:ef42491aa1f8":      true,
	"test_join_suite:1a2a12332bde":                   true,
	"test_join_suite:1b0d4e955268":                   true,
	"test_join_suite:ab214675f097":                   true,
	"test_mssql_boundary_suite:3da07e0c9e01":         true,
	"test_mssql_boundary_suite:532cd8b855de":         true,
	"test_mssql_boundary_suite:58dadbabebd0":         true,
	"test_mssql_boundary_suite:5d36d3f79ca0":         true,
	"test_mssql_boundary_suite:5f2c89d7dce4":         true,
	"test_mssql_boundary_suite:8c58b4ae06b4":         true,
	"test_mssql_boundary_suite:d9576391b03c":         true,
	"test_mssql_boundary_suite:ef0ceea439a8":         true,
	"test_mssql_boundary_suite:f136407c4a2f":         true,
	"test_reconstructor_coverage_suite:33cf45561406": true,
	"test_reconstructor_coverage_suite:654fc1f8d9af": true,
	"test_reconstructor_coverage_suite:88d06266db48": true,
	"test_semantic_suite:359050b5d8b9":               true,
	"test_semantic_suite:8c8d02e2d55b":               true,
	"test_visualizer_suite:5f2c89d7dce4":             true,
	"test_visualizer_suite:ef0ceea439a8":             true,
	"test_visualizer_suite:f136407c4a2f":             true,
}
