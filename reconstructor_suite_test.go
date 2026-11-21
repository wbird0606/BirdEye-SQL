package birdeye

import (
	"strings"
	"testing"
)

// 對照 birdeye_1150831/tests/test_reconstructor_suite.py（roundtrip 子字串斷言）。
// conformance 已驗 byte 一致；此處 1:1 鎖定行為。

func TestReconstructorSuite_Roundtrip(t *testing.T) {
	cases := []struct {
		sql  string
		want []string
	}{
		{"SELECT * FROM Address", []string{"SELECT", "*", "Address"}},
		{"SELECT AddressID, City FROM Address", []string{"AddressID", "City", "Address"}},
		{"SELECT AddressID AS ID FROM Address", []string{"AddressID", "AS", "ID"}},
		{"SELECT a.AddressID FROM Address a", []string{"AddressID", "Address"}},
		{"SELECT DISTINCT City FROM Address", []string{"DISTINCT", "City"}},
		{"SELECT TOP 10 AddressID FROM Address", []string{"TOP", "10"}},
		{"SELECT TOP 10 PERCENT AddressID FROM Address", []string{"TOP", "PERCENT"}},
		{"SELECT AddressID FROM Address WHERE AddressID > 0", []string{"WHERE", ">"}},
		{"SELECT AddressID FROM Address WHERE AddressID > 0 AND City = 'X'", []string{"AND"}},
		{"SELECT AddressID FROM Address WHERE City IS NULL", []string{"IS NULL"}},
		{"SELECT AddressID FROM Address WHERE City LIKE 'A%'", []string{"LIKE"}},
		{"SELECT AddressID FROM Address WHERE AddressID IN (1, 2, 3)", []string{"IN"}},
		{"SELECT a.AddressID FROM Address a JOIN StateProvince s ON a.StateProvinceID = s.StateProvinceID", []string{"JOIN", "ON"}},
		{"SELECT a.AddressID FROM Address a LEFT JOIN StateProvince s ON a.StateProvinceID = s.StateProvinceID", []string{"LEFT", "JOIN"}},
		{"SELECT StateProvinceID, COUNT(*) AS C FROM Address GROUP BY StateProvinceID", []string{"GROUP BY"}},
		{"SELECT StateProvinceID, COUNT(*) AS C FROM Address GROUP BY StateProvinceID HAVING COUNT(*) > 1", []string{"HAVING"}},
		{"SELECT AddressID FROM Address ORDER BY AddressID DESC", []string{"ORDER BY", "DESC"}},
		{"SELECT AddressID FROM Address ORDER BY AddressID OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY", []string{"OFFSET", "FETCH"}},
		{"SELECT CASE WHEN AddressID > 0 THEN 'Pos' ELSE 'Zero' END FROM Address", []string{"CASE", "WHEN", "THEN", "END"}},
		{"UPDATE Address SET City = 'X' WHERE AddressID = 1", []string{"UPDATE", "SET", "WHERE"}},
		{"DELETE FROM Address WHERE AddressID = 1", []string{"DELETE", "WHERE"}},
		{"INSERT INTO Address (AddressID, City) VALUES (1, 'X')", []string{"INSERT", "VALUES"}},
		{"TRUNCATE TABLE Address", []string{"TRUNCATE", "Address"}},
		{"SELECT AddressID FROM Address UNION SELECT AddressID FROM Address", []string{"UNION"}},
		{"SELECT AddressID FROM Address UNION ALL SELECT AddressID FROM Address", []string{"UNION ALL"}},
		{"SELECT AddressID FROM Address INTERSECT SELECT AddressID FROM Address", []string{"INTERSECT"}},
		{"SELECT AddressID FROM Address EXCEPT SELECT AddressID FROM Address", []string{"EXCEPT"}},
		{"WITH CTE AS (SELECT AddressID FROM Address) SELECT AddressID FROM CTE", []string{"WITH", "AS"}},
		{"SELECT CAST(AddressID AS VARCHAR) FROM Address", []string{"CAST", "AS"}},
		{"SELECT AddressID FROM Address WHERE AddressID BETWEEN 1 AND 100", []string{"BETWEEN", "AND"}},
		{"SELECT LEN(City) FROM Address", []string{"LEN"}},
		{"SELECT AddressID, ROW_NUMBER() OVER (ORDER BY AddressID) AS rn FROM Address", []string{"ROW_NUMBER", "OVER", "ORDER BY"}},
		{"SELECT AddressID, ROW_NUMBER() OVER (PARTITION BY PostalCode ORDER BY AddressID) AS rn FROM Address", []string{"PARTITION BY", "PostalCode"}},
		{"SELECT RANK() OVER (ORDER BY City) AS rnk FROM Address", []string{"RANK", "OVER"}},
		{"SELECT LAG(City) OVER (ORDER BY AddressID) FROM Address", []string{"LAG", "OVER"}},
	}
	for _, c := range cases {
		got := roundtrip(t, c.sql)
		for _, w := range c.want {
			if !strings.Contains(got, w) {
				t.Errorf("%q -> %q missing %q", c.sql, got, w)
			}
		}
	}
}

func TestReconstructor_FromJSONString(t *testing.T) {
	n := mustParse(t, "SELECT AddressID FROM Address")
	jsonStr := NewSerializer().ToJSON(n)
	sql, err := NewReconstructor().Reconstruct(jsonStr)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(sql, "SELECT") || !strings.Contains(sql, "AddressID") {
		t.Errorf("from_json_str -> %q", sql)
	}
}

func TestReconstructor_InvalidJSON(t *testing.T) {
	if _, err := NewReconstructor().Reconstruct("{not json"); err == nil {
		t.Fatal("invalid JSON 應回報錯誤")
	}
}
