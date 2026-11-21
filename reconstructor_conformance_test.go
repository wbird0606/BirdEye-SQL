package birdeye

import "testing"

// TestReconstructConformance：以 Python 產出的 ast_json 為輸入，Go Reconstruct
// 的 SQL 對照 Python from_json_str 的輸出，逐位元組比對（ADR 0002）。
func TestReconstructConformance(t *testing.T) {
	var total, pass, skip int
	fails := map[string]int{}

	for _, r := range allPipeFixtures(t) {
		if !r.Parse.OK {
			continue
		}
		total++

		want, wantOK := r.Reconstructed.Value.(string)
		got, gerr := safeReconstruct(r.Parse.ASTJSON)

		if !r.Reconstructed.OK {
			// Python reconstruct 出錯（含 KNOWN_DEVIATIONS A2 的 KeyError）
			if gerr == nil {
				fails["應報錯卻成功"]++
				t.Errorf("[%s] reconstruct 應失敗卻成功\nSQL: %q", r.ID, r.SQL)
			} else {
				pass++
			}
			continue
		}
		if !wantOK {
			skip++
			continue
		}
		if gerr != nil {
			fails["非預期錯誤"]++
			t.Errorf("[%s] reconstruct 非預期錯誤: %v\nSQL: %q", r.ID, gerr, r.SQL)
			continue
		}
		if got != want && knownReconstructDeviation[r.ID] {
			// 刻意偏離（KNOWN_DEVIATIONS A7、A8）：基準輸出含多餘 "AS 別名"、缺括號或遺失字面值別名，
			// 為不合法或語意改變之 SQL；現行輸出之合法性與穩定性由 rewrite_semantics_test.go 鎖定。
			pass++
			continue
		}
		if got != want {
			fails["SQL 不符"]++
			t.Errorf("[%s] reconstructed SQL 不一致\nSQL: %q\n%s", r.ID, r.SQL, firstDiff(got, want))
			continue
		}
		pass++
	}

	t.Logf("reconstruct conformance: %d/%d pass（skip %d）", pass, total, skip)
	if len(fails) > 0 {
		t.Errorf("失敗分類: %v", fails)
	}
}

func safeReconstruct(astJSON string) (sql string, err error) {
	defer func() {
		if r := recover(); r != nil {
			if be, ok := r.(engineBail); ok {
				err = be.err
				return
			}
			err = &Error{ErrSystem, panicMsg(r)}
		}
	}()
	return NewReconstructor().Reconstruct(astJSON)
}
