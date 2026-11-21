package birdeye

import (
	"encoding/json"
	"strings"
	"testing"
)

// 對照 tests/test_74_star_intent_suite.py 與 tests/test_all_cases_intent_suite.py

func expandedIntentsOf(t *testing.T, reg *MetadataRegistry, sql string) []Intent {
	t.Helper()
	res, err := NewRunner(reg).Run(sql, nil)
	if err != nil {
		t.Fatalf("run %q: %v", sql, err)
	}
	var m any
	if err := json.Unmarshal([]byte(res.JSON), &m); err != nil {
		t.Fatalf("json: %v", err)
	}
	ie := NewIntentExtractor()
	return ie.ExpandStarIntents(ie.Extract(m), reg)
}

func hasIntentCI(items []Intent, table, column, intent string) bool {
	for _, i := range items {
		col := ""
		if i.Column != nil {
			col = *i.Column
		}
		if strings.EqualFold(i.Table, table) &&
			strings.EqualFold(col, column) &&
			i.Intent == intent {
			return true
		}
	}
	return false
}

func TestIntent74_StarExpansion(t *testing.T) {
	reg := mkReg(t, `table_name,column_name,data_type
Customer,CustomerID,int
Customer,FirstName,nvarchar
Customer,LastName,nvarchar
Customer,EmailAddress,nvarchar
Customer,Phone,nvarchar
Address,AddressID,int
Address,City,nvarchar
`)

	t.Run("count_star_expands_all_columns", func(t *testing.T) {
		it := expandedIntentsOf(t, reg, "SELECT COUNT(*) AS Total FROM SalesLT.Customer")
		for _, c := range []string{"CustomerID", "FirstName", "EmailAddress", "Phone"} {
			if !hasIntentCI(it, "Customer", c, "READ") {
				t.Errorf("缺少 Customer.%s READ\n%+v", c, it)
			}
		}
	})

	t.Run("count_star_no_none_column", func(t *testing.T) {
		it := expandedIntentsOf(t, reg, "SELECT COUNT(*) AS Total FROM SalesLT.Customer")
		for _, i := range it {
			if i.Table == "Customer" && i.Intent == "READ" && i.Column == nil {
				t.Errorf("展開後不應有 column=nil READ：%+v", it)
			}
		}
	})

	t.Run("select_star_expands_all_columns", func(t *testing.T) {
		it := expandedIntentsOf(t, reg, "SELECT * FROM SalesLT.Customer")
		for _, c := range []string{"CustomerID", "FirstName", "EmailAddress", "Phone"} {
			if !hasIntentCI(it, "Customer", c, "READ") {
				t.Errorf("缺少 Customer.%s READ\n%+v", c, it)
			}
		}
	})

	t.Run("specific_column_select_unchanged", func(t *testing.T) {
		it := expandedIntentsOf(t, reg, "SELECT FirstName, LastName FROM SalesLT.Customer")
		if !hasIntentCI(it, "Customer", "FirstName", "READ") || !hasIntentCI(it, "Customer", "LastName", "READ") {
			t.Errorf("%+v", it)
		}
		if hasIntentCI(it, "Customer", "EmailAddress", "READ") {
			t.Errorf("指定欄位 SELECT 不應出現 EmailAddress：%+v", it)
		}
	})

	t.Run("count_star_with_join_expands_both_tables", func(t *testing.T) {
		it := expandedIntentsOf(t, reg,
			"SELECT COUNT(*) FROM SalesLT.Customer c JOIN SalesLT.Address a ON c.CustomerID = a.AddressID")
		if !hasIntentCI(it, "Customer", "EmailAddress", "READ") || !hasIntentCI(it, "Address", "City", "READ") {
			t.Errorf("%+v", it)
		}
	})
}

func TestIntent_AllCases(t *testing.T) {
	aw := loadAdventureWorks(t)
	// 對照 Python DENIED：展開後欄位名為大寫，故兩種大小寫都列入。
	denied := map[[3]string]bool{
		{"SalesLT", "Customer", "EmailAddress"}: true,
		{"SalesLT", "Customer", "Phone"}:        true,
		{"SalesLT", "Customer", "EMAILADDRESS"}: true,
		{"SalesLT", "Customer", "PHONE"}:        true,
	}
	hasDenied := func(items []Intent) bool {
		for _, i := range items {
			col := ""
			if i.Column != nil {
				col = *i.Column
			}
			if denied[[3]string{i.Schema, i.Table, col}] {
				return true
			}
		}
		return false
	}

	cases := []struct {
		name string
		sql  string
		http int
	}{
		{"C1-01", "SELECT CustomerID, FirstName, LastName FROM SalesLT.Customer", 200},
		{"C1-02", "SELECT EmailAddress FROM SalesLT.Customer", 403},
		{"C1-03", "SELECT Phone FROM SalesLT.Customer", 403},
		{"C1-04", "SELECT CustomerID, FirstName, EmailAddress FROM SalesLT.Customer", 403},
		{"C1-05", "SELECT CustomerID, FirstName, Phone FROM SalesLT.Customer", 403},
		{"C1-06", "SELECT EmailAddress, Phone FROM SalesLT.Customer", 403},
		{"C1-07", "SELECT * FROM SalesLT.Customer", 403},
		{"C2-01", "SELECT AddressID, AddressLine1, City FROM SalesLT.Address", 200},
		{"C2-02", "SELECT * FROM SalesLT.Address", 200},
		{"C3-01", "SELECT TOP 5 CustomerID, FirstName FROM SalesLT.Customer", 200},
		{"C3-02", "SELECT TOP 5 CustomerID, EmailAddress FROM SalesLT.Customer", 403},
		{"C3-03", "SELECT TOP 3 AddressID, City FROM SalesLT.Address", 200},
		{"C4-01", "SELECT CustomerID, FirstName FROM SalesLT.Customer WHERE CustomerID > 10", 200},
		{"C4-02", "SELECT CustomerID, EmailAddress FROM SalesLT.Customer WHERE CustomerID > 10", 403},
		{"C4-03", "SELECT CustomerID, FirstName FROM SalesLT.Customer WHERE CustomerID = 1", 200},
		{"C4-04", "SELECT CustomerID, EmailAddress FROM SalesLT.Customer WHERE CustomerID = 1", 403},
		{"C4-05", "SELECT CustomerID, FirstName FROM SalesLT.Customer WHERE FirstName = 'Keith'", 200},
		{"C4-06", "SELECT CustomerID, FirstName FROM SalesLT.Customer WHERE CustomerID > 1 AND CustomerID < 100", 200},
		{"C5-01", "SELECT COUNT(*) AS Total FROM SalesLT.Customer", 403},
		{"C5-02", "SELECT COUNT(*) AS Total FROM SalesLT.Address", 200},
		{"C5-03", "SELECT COUNT(CustomerID) AS Total FROM SalesLT.Customer", 200},
		{"C5-04", "SELECT COUNT(EmailAddress) AS Total FROM SalesLT.Customer", 403},
		{"C5-05", "SELECT COUNT(*) AS Total FROM SalesLT.Customer WHERE CustomerID > 10", 403},
		{"C5-06", "SELECT COUNT(*) AS Total FROM SalesLT.Address WHERE City = 'Seattle'", 200},
		{"C6-01", "SELECT c.FirstName, a.City FROM SalesLT.Customer c JOIN SalesLT.CustomerAddress ca ON c.CustomerID = ca.CustomerID JOIN SalesLT.Address a ON ca.AddressID = a.AddressID", 200},
		{"C6-02", "SELECT c.EmailAddress, a.City FROM SalesLT.Customer c JOIN SalesLT.CustomerAddress ca ON c.CustomerID = ca.CustomerID JOIN SalesLT.Address a ON ca.AddressID = a.AddressID", 403},
		{"C6-03", "SELECT a.AddressID, a.City, a.StateProvince FROM SalesLT.Customer c JOIN SalesLT.CustomerAddress ca ON c.CustomerID = ca.CustomerID JOIN SalesLT.Address a ON ca.AddressID = a.AddressID", 200},
		{"C6-04", "SELECT TOP 3 c.FirstName, a.City FROM SalesLT.Customer c JOIN SalesLT.CustomerAddress ca ON c.CustomerID = ca.CustomerID JOIN SalesLT.Address a ON ca.AddressID = a.AddressID", 200},
		{"C7-01", "SELECT CustomerID, FirstName FROM SalesLT.Customer ORDER BY FirstName", 200},
		{"C7-02", "SELECT CustomerID, EmailAddress FROM SalesLT.Customer ORDER BY EmailAddress", 403},
		{"C7-03", "SELECT DISTINCT City FROM SalesLT.Address", 200},
		{"C7-04", "SELECT DISTINCT EmailAddress FROM SalesLT.Customer", 403},
		{"C7-05", "SELECT City, COUNT(*) AS Total FROM SalesLT.Address GROUP BY City", 200},
		{"C7-06", "SELECT CompanyName, COUNT(*) AS Total FROM SalesLT.Customer GROUP BY CompanyName", 403},
		{"C7-07", "SELECT EmailAddress, COUNT(*) AS Total FROM SalesLT.Customer GROUP BY EmailAddress", 403},
	}

	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			it := expandedIntentsOf(t, aw, c.sql)
			got := hasDenied(it)
			want := c.http == 403
			if got != want {
				t.Errorf("SQL %q\n  期望禁止=%v 實際含禁止=%v\n  %+v", c.sql, want, got, it)
			}
		})
	}
}
