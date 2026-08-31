package birdeye

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// conformance 測試共用工具：讀取 testdata/conformance/ 下的 JSONL golden fixture。
// 由 tools/gen_fixtures.py 從 Python baseline 產生（見 ADR 0005）。

const conformanceDir = "testdata/conformance"

// errRec 對照 fixture 的 error 欄位。
type errRec struct {
	Category string `json:"category"`
	Type     string `json:"type"`
	Message  string `json:"message"`
}

// readJSONL 逐行解析 testdata/conformance/<name>；檔案不存在時 Skip 整個測試。
func readJSONL[T any](t *testing.T, name string) []T {
	t.Helper()
	f, err := os.Open(filepath.Join(conformanceDir, name))
	if err != nil {
		t.Skipf("缺少 golden fixture %s（跑 tools/gen_fixtures.py 產生）: %v", name, err)
	}
	defer f.Close()

	var out []T
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 0, 64*1024), 8*1024*1024)
	for ln := 1; sc.Scan(); ln++ {
		line := sc.Bytes()
		if len(line) == 0 {
			continue
		}
		var rec T
		if err := json.Unmarshal(line, &rec); err != nil {
			t.Fatalf("%s:%d JSON 解析失敗: %v", name, ln, err)
		}
		out = append(out, rec)
	}
	if err := sc.Err(); err != nil {
		t.Fatalf("%s 讀取失敗: %v", name, err)
	}
	return out
}
