package birdeye

import "testing"

// A19：詞法階段剝除方括號，重建時須對「非單純識別字」補回方括號，
// 否則重建後之 SQL（會被執行）語意改變：[First Name] 會變成別名寫法 First Name。
func TestReconstructQuotesNonPlainIdentifiers(t *testing.T) {
	cases := map[string]string{
		"SELECT [First Name] FROM Users":      "SELECT [First Name] FROM Users",
		"SELECT [2019] FROM Users":            "SELECT [2019] FROM Users",
		"SELECT u.[2019] FROM Users u":        "SELECT u.[2019] FROM Users AS u",
		"SELECT [a-b], c FROM Users":          "SELECT [a-b], c FROM Users",
		"SELECT name, #t.x FROM Users, #t":    "", // 逗號 JOIN 不支援，僅確認不 panic
		"SELECT * FROM Users WHERE @id = 1":   "SELECT * FROM Users WHERE @id = 1",
		"SELECT Name FROM Users WHERE Id = 1": "SELECT Name FROM Users WHERE Id = 1",
	}
	for sql, want := range cases {
		n, err := NewRunner(nil).ParseOnly(sql, nil)
		if want == "" {
			continue
		}
		if err != nil {
			t.Errorf("%q：%v", sql, err)
			continue
		}
		got, err := NewReconstructor().Reconstruct(NewSerializer().ToJSON(n))
		if err != nil || got != want {
			t.Errorf("%q\n got  %q (%v)\n want %q", sql, got, err, want)
		}
	}
}
