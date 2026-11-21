package birdeye

import (
	"encoding/json"
	"testing"
)

// 對照 python-final:tests/test_intent_extractor_suite.py

const intentTestCSV = `table_name,column_name,data_type
Customer,CustomerID,int
Customer,FirstName,nvarchar
Customer,LastName,nvarchar
Customer,EmailAddress,nvarchar
Customer,Phone,nvarchar
Customer,SalesPerson,nvarchar
CustomerAddress,CustomerID,int
CustomerAddress,AddressID,int
Address,AddressID,int
Address,AddressLine1,nvarchar
Address,AddressLine2,nvarchar
Address,City,nvarchar
Address,StateProvince,nvarchar
Address,PostalCode,nvarchar
SalesOrderHeader,SalesOrderID,int
SalesOrderHeader,CustomerID,int
SalesOrderHeader,TotalDue,money
`

// intentsOf：完整 pipeline（含 binder）後萃取意圖，對照 Python intents_of。
func intentsOf(t *testing.T, reg *MetadataRegistry, sql string) []Intent {
	t.Helper()
	res, err := NewRunner(reg).Run(sql, nil)
	if err != nil {
		t.Fatalf("run %q: %v", sql, err)
	}
	var m any
	if err := json.Unmarshal([]byte(res.JSON), &m); err != nil {
		t.Fatalf("json: %v", err)
	}
	return NewIntentExtractor().Extract(m)
}

// hasIntent：schema 傳 "" 表示不比對 schema（對照 Python schema=None）。
func hasIntent(items []Intent, table, column, intent, schema string) bool {
	for _, i := range items {
		col := ""
		hasCol := i.Column != nil
		if hasCol {
			col = *i.Column
		}
		// column 傳 "\x00" 代表期望 nil（table-level）
		wantNil := column == "\x00"
		if wantNil {
			if hasCol || i.Table != table || i.Intent != intent {
				continue
			}
		} else if col != column || i.Table != table || i.Intent != intent {
			continue
		}
		if schema == "" || i.Schema == schema {
			return true
		}
	}
	return false
}

const tableLevel = "\x00"

func TestIntentExtractor_Suite(t *testing.T) {
	reg := mkReg(t, intentTestCSV)

	t.Run("select_columns_read", func(t *testing.T) {
		it := intentsOf(t, reg, "SELECT FirstName, LastName FROM SalesLT.Customer")
		if !hasIntent(it, "Customer", "FirstName", "READ", "SalesLT") ||
			!hasIntent(it, "Customer", "LastName", "READ", "SalesLT") {
			t.Errorf("%+v", it)
		}
	})

	t.Run("where_column_is_filter", func(t *testing.T) {
		it := intentsOf(t, reg, "SELECT FirstName FROM SalesLT.Customer WHERE CustomerID = 1")
		if !hasIntent(it, "Customer", "FirstName", "READ", "SalesLT") ||
			!hasIntent(it, "Customer", "CustomerID", "FILTER", "SalesLT") {
			t.Errorf("%+v", it)
		}
		if hasIntent(it, "Customer", "CustomerID", "READ", "") {
			t.Errorf("CustomerID 不應為 READ：%+v", it)
		}
	})

	t.Run("select_star_table_level_read", func(t *testing.T) {
		it := intentsOf(t, reg, "SELECT * FROM SalesLT.Customer")
		n := 0
		for _, i := range it {
			if i.Table == "Customer" && i.Intent == "READ" && i.Schema == "SalesLT" {
				n++
			}
		}
		if n == 0 {
			t.Errorf("SELECT * 應產生 Customer 欄位 READ：%+v", it)
		}
	})

	t.Run("join_on_is_filter", func(t *testing.T) {
		sql := `SELECT c.FirstName, a.AddressLine1
			FROM SalesLT.Customer AS c
			JOIN SalesLT.CustomerAddress AS ca ON c.CustomerID = ca.CustomerID
			JOIN SalesLT.Address AS a ON ca.AddressID = a.AddressID`
		it := intentsOf(t, reg, sql)
		checks := [][4]string{
			{"Customer", "FirstName", "READ", ""},
			{"Address", "AddressLine1", "READ", ""},
			{"Customer", "CustomerID", "FILTER", ""},
			{"CustomerAddress", "CustomerID", "FILTER", ""},
			{"CustomerAddress", "AddressID", "FILTER", ""},
			{"Address", "AddressID", "FILTER", ""},
		}
		for _, c := range checks {
			if !hasIntent(it, c[0], c[1], c[2], c[3]) {
				t.Errorf("缺少 %v\n%+v", c, it)
			}
		}
	})

	t.Run("group_by_having_is_filter", func(t *testing.T) {
		sql := "SELECT CustomerID FROM SalesLT.SalesOrderHeader GROUP BY CustomerID HAVING COUNT(*) > 1"
		it := intentsOf(t, reg, sql)
		if !hasIntent(it, "SalesOrderHeader", "CustomerID", "READ", "") ||
			!hasIntent(it, "SalesOrderHeader", "CustomerID", "FILTER", "") {
			t.Errorf("%+v", it)
		}
	})

	t.Run("order_by_is_filter", func(t *testing.T) {
		it := intentsOf(t, reg, "SELECT FirstName FROM SalesLT.Customer ORDER BY LastName")
		if !hasIntent(it, "Customer", "FirstName", "READ", "") ||
			!hasIntent(it, "Customer", "LastName", "FILTER", "") {
			t.Errorf("%+v", it)
		}
	})

	t.Run("insert_with_columns", func(t *testing.T) {
		it := intentsOf(t, reg, "INSERT INTO SalesLT.Address (AddressLine1, City) VALUES ('123 St', 'NYC')")
		if !hasIntent(it, "Address", "AddressLine1", "INSERT", "SalesLT") ||
			!hasIntent(it, "Address", "City", "INSERT", "SalesLT") {
			t.Errorf("%+v", it)
		}
	})

	t.Run("truncate_table_level_delete", func(t *testing.T) {
		it := intentsOf(t, reg, "TRUNCATE TABLE SalesLT.Address")
		if !hasIntent(it, "Address", tableLevel, "DELETE", "SalesLT") {
			t.Errorf("%+v", it)
		}
	})

	t.Run("update_set_update_where_filter", func(t *testing.T) {
		it := intentsOf(t, reg, "UPDATE SalesLT.Address SET City = 'Boston' WHERE AddressID = 5")
		if !hasIntent(it, "Address", "City", "UPDATE", "SalesLT") ||
			!hasIntent(it, "Address", "AddressID", "FILTER", "SalesLT") {
			t.Errorf("%+v", it)
		}
		if hasIntent(it, "Address", "City", "READ", "") {
			t.Errorf("City 不應為 READ：%+v", it)
		}
	})

	t.Run("delete_table_level_and_filter", func(t *testing.T) {
		it := intentsOf(t, reg, "DELETE FROM SalesLT.Address WHERE AddressID = 5")
		if !hasIntent(it, "Address", tableLevel, "DELETE", "SalesLT") ||
			!hasIntent(it, "Address", "AddressID", "FILTER", "SalesLT") {
			t.Errorf("%+v", it)
		}
	})

	t.Run("case_when_inherits_parent_intent", func(t *testing.T) {
		sql := "SELECT CASE WHEN SalesPerson IS NULL THEN 'Unknown' ELSE SalesPerson END FROM SalesLT.Customer"
		it := intentsOf(t, reg, sql)
		if !hasIntent(it, "Customer", "SalesPerson", "READ", "") {
			t.Errorf("%+v", it)
		}
	})

	t.Run("subquery_in_where", func(t *testing.T) {
		sql := `SELECT FirstName FROM SalesLT.Customer
			WHERE CustomerID IN (SELECT CustomerID FROM SalesLT.SalesOrderHeader WHERE TotalDue > 100)`
		it := intentsOf(t, reg, sql)
		checks := [][4]string{
			{"Customer", "FirstName", "READ", ""},
			{"Customer", "CustomerID", "FILTER", ""},
			{"SalesOrderHeader", "CustomerID", "READ", ""},
			{"SalesOrderHeader", "TotalDue", "FILTER", ""},
		}
		for _, c := range checks {
			if !hasIntent(it, c[0], c[1], c[2], c[3]) {
				t.Errorf("缺少 %v\n%+v", c, it)
			}
		}
	})

	t.Run("cte_inner_intents_extracted", func(t *testing.T) {
		sql := `WITH TopCustomers AS (SELECT CustomerID FROM SalesLT.Customer WHERE CustomerID < 100)
			SELECT CustomerID FROM TopCustomers`
		it := intentsOf(t, reg, sql)
		if !hasIntent(it, "Customer", "CustomerID", "READ", "") ||
			!hasIntent(it, "Customer", "CustomerID", "FILTER", "") {
			t.Errorf("%+v", it)
		}
		for _, i := range it {
			if i.Table == "TopCustomers" {
				t.Errorf("CTE 名稱不應被視為資料表：%+v", it)
			}
		}
	})

	t.Run("union_both_sides_extracted", func(t *testing.T) {
		sql := `SELECT FirstName FROM SalesLT.Customer
			UNION
			SELECT FirstName FROM SalesLT.Customer WHERE CustomerID = 1`
		it := intentsOf(t, reg, sql)
		if !hasIntent(it, "Customer", "FirstName", "READ", "") ||
			!hasIntent(it, "Customer", "CustomerID", "FILTER", "") {
			t.Errorf("%+v", it)
		}
	})

	t.Run("insert_select_read_and_insert", func(t *testing.T) {
		sql := `INSERT INTO SalesLT.Address (AddressLine1, City)
			SELECT AddressLine1, City FROM SalesLT.Address WHERE StateProvince = 'WA'`
		it := intentsOf(t, reg, sql)
		checks := [][4]string{
			{"Address", "AddressLine1", "INSERT", ""},
			{"Address", "City", "INSERT", ""},
			{"Address", "AddressLine1", "READ", ""},
			{"Address", "City", "READ", ""},
			{"Address", "StateProvince", "FILTER", ""},
		}
		for _, c := range checks {
			if !hasIntent(it, c[0], c[1], c[2], c[3]) {
				t.Errorf("缺少 %v\n%+v", c, it)
			}
		}
	})

	t.Run("alias_resolves_to_real_schema_table", func(t *testing.T) {
		it := intentsOf(t, reg, "SELECT c.FirstName FROM SalesLT.Customer AS c WHERE c.CustomerID = 1")
		if !hasIntent(it, "Customer", "FirstName", "READ", "SalesLT") ||
			!hasIntent(it, "Customer", "CustomerID", "FILTER", "SalesLT") {
			t.Errorf("%+v", it)
		}
	})
}
