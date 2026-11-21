package birdeye

import "testing"

// 對照 python-final:tests/test_reconstructor_suite.py 的 roundtrip 概念。
// conformance（1796/1796）已涵蓋 byte 一致性；此處針對代表案例做精確斷言。

func roundtrip(t *testing.T, sql string) string {
	t.Helper()
	n := mustParse(t, sql)
	astJSON := NewSerializer().ToJSON(n)
	out, err := NewReconstructor().Reconstruct(astJSON)
	if err != nil {
		t.Fatalf("reconstruct %q: %v", sql, err)
	}
	return out
}

func TestReconstructorRoundtrip(t *testing.T) {
	cases := []struct{ in, want string }{
		{"SELECT * FROM Address", "SELECT * FROM Address"},
		{"SELECT AddressID, City FROM Address", "SELECT AddressID, City FROM Address"},
		{"SELECT AddressID AS ID FROM Address", "SELECT AddressID AS ID FROM Address"},
		{"SELECT a.AddressID FROM Address a", "SELECT a.AddressID FROM Address AS a"},
		{"SELECT DISTINCT City FROM Address", "SELECT DISTINCT City FROM Address"},
		{"SELECT TOP 10 AddressID FROM Address", "SELECT TOP 10 AddressID FROM Address"},
		{"SELECT TOP 10 PERCENT AddressID FROM Address", "SELECT TOP 10 PERCENT AddressID FROM Address"},
		{"SELECT AddressID FROM Address WHERE AddressID > 0", "SELECT AddressID FROM Address WHERE AddressID > 0"},
		{"SELECT AddressID FROM Address WHERE City IS NULL", "SELECT AddressID FROM Address WHERE City IS NULL"},
		{"SELECT A FROM T WHERE A IN (1, 2, 3)", "SELECT A FROM T WHERE A IN (1, 2, 3)"},
		{"SELECT A FROM T WHERE A NOT IN (1, 2)", "SELECT A FROM T WHERE A NOT IN (1, 2)"},
		{"SELECT 1 UNION SELECT 2", "SELECT 1 UNION SELECT 2"},
		{"SELECT A FROM T INTERSECT SELECT A FROM T", "SELECT A FROM T INTERSECT SELECT A FROM T"},
		{"SELECT CAST(Price AS INT) FROM T", "SELECT CAST(Price AS INT) FROM T"},
		{"UPDATE T SET A = 1 WHERE B = 2", "UPDATE T SET A = 1 WHERE B = 2"},
		{"DELETE FROM T WHERE A = 1", "DELETE FROM T WHERE A = 1"},
		{"INSERT INTO T (A, B) VALUES (1, 'x')", "INSERT INTO T (A, B) VALUES (1, 'x')"},
		{"INSERT INTO T (A) VALUES (1), (2)", "INSERT INTO T (A) VALUES (1), (2)"},
		{"TRUNCATE TABLE T", "TRUNCATE TABLE T"},
		{"WITH c AS (SELECT 1 AS A) SELECT A FROM c", "WITH C AS (SELECT 1 AS A) SELECT A FROM c"},
		{"SELECT A FROM T ORDER BY A OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY",
			"SELECT A FROM T ORDER BY A ASC OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY"},
	}
	for _, c := range cases {
		if got := roundtrip(t, c.in); got != c.want {
			t.Errorf("%q\n got %q\nwant %q", c.in, got, c.want)
		}
	}
}
