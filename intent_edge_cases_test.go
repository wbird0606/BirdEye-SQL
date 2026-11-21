package birdeye

import "testing"

// 對照 tests/test_intent_edge_cases_suite.py（#67~#70）與
//       tests/test_intent_edge_cases_2_suite.py（#71~#73）。

const intentEdgeCSV = `table_name,column_name,data_type
Customer,CustomerID,int
Customer,FirstName,nvarchar
Customer,LastName,nvarchar
Customer,SalesPerson,nvarchar
Address,AddressID,int
Address,AddressLine1,nvarchar
Address,City,nvarchar
CustomerAddress,CustomerID,int
CustomerAddress,AddressID,int
SalesOrderHeader,SalesOrderID,int
SalesOrderHeader,CustomerID,int
SalesOrderHeader,TotalDue,money
`

func TestIntent_EdgeCases_67to70(t *testing.T) {
	reg := mkReg(t, intentEdgeCSV)

	t.Run("67_unqualified_where_filter", func(t *testing.T) {
		it := intentsOf(t, reg, "SELECT c.FirstName FROM SalesLT.Customer c "+
			"JOIN SalesLT.Address a ON c.CustomerID = a.AddressID WHERE City = 'Seattle'")
		if !hasIntent(it, "Address", "City", "FILTER", "SalesLT") {
			t.Errorf("City 應解析到 Address.City FILTER\n%+v", it)
		}
	})

	t.Run("67_unqualified_select_read", func(t *testing.T) {
		it := intentsOf(t, reg, "SELECT FirstName FROM SalesLT.Customer c "+
			"JOIN SalesLT.Address a ON c.CustomerID = a.AddressID")
		if !hasIntent(it, "Customer", "FirstName", "READ", "SalesLT") {
			t.Errorf("%+v", it)
		}
	})

	t.Run("68_select_star_multi_join", func(t *testing.T) {
		it := intentsOf(t, reg, "SELECT * FROM SalesLT.Customer c "+
			"JOIN SalesLT.Address a ON c.CustomerID = a.AddressID")
		if !countReads(it, "Customer", "SalesLT") || !countReads(it, "Address", "SalesLT") {
			t.Errorf("兩表都應有 READ\n%+v", it)
		}
	})

	t.Run("68_select_star_three_way_join", func(t *testing.T) {
		it := intentsOf(t, reg, "SELECT * FROM SalesLT.Customer c "+
			"JOIN SalesLT.Address a ON c.CustomerID = a.AddressID "+
			"JOIN SalesLT.SalesOrderHeader s ON c.CustomerID = s.CustomerID")
		for _, tb := range []string{"Customer", "Address", "SalesOrderHeader"} {
			if !countReads(it, tb, "SalesLT") {
				t.Errorf("%s 應有 READ\n%+v", tb, it)
			}
		}
	})

	correlated := "SELECT c.FirstName, " +
		"(SELECT COUNT(*) FROM SalesLT.SalesOrderHeader soh WHERE soh.CustomerID = c.CustomerID) AS order_count " +
		"FROM SalesLT.Customer c"

	t.Run("69_correlated_subquery_outer_alias_filter", func(t *testing.T) {
		it := intentsOf(t, reg, correlated)
		if !hasIntent(it, "Customer", "CustomerID", "FILTER", "SalesLT") {
			t.Errorf("%+v", it)
		}
	})

	t.Run("69_correlated_subquery_inner_extracted", func(t *testing.T) {
		it := intentsOf(t, reg, correlated)
		if !hasIntent(it, "SalesOrderHeader", "CustomerID", "FILTER", "SalesLT") {
			t.Errorf("%+v", it)
		}
	})

	apply := "SELECT c.FirstName, sub.SalesOrderID FROM SalesLT.Customer c " +
		"CROSS APPLY (SELECT TOP 1 SalesOrderID FROM SalesLT.SalesOrderHeader soh WHERE soh.CustomerID = c.CustomerID) sub"

	t.Run("70_cross_apply_outer_alias_filter", func(t *testing.T) {
		it := intentsOf(t, reg, apply)
		if !hasIntent(it, "Customer", "CustomerID", "FILTER", "SalesLT") {
			t.Errorf("%+v", it)
		}
	})

	t.Run("70_cross_apply_inner_columns", func(t *testing.T) {
		it := intentsOf(t, reg, apply)
		if !hasIntent(it, "SalesOrderHeader", "CustomerID", "FILTER", "SalesLT") ||
			!hasIntent(it, "SalesOrderHeader", "SalesOrderID", "READ", "SalesLT") {
			t.Errorf("%+v", it)
		}
	})
}

func countReads(items []Intent, table, schema string) bool {
	for _, i := range items {
		if i.Table == table && i.Intent == "READ" && i.Schema == schema {
			return true
		}
	}
	return false
}

func TestIntent_EdgeCases_71to73(t *testing.T) {
	reg := mkReg(t, intentEdgeCSV)

	derived := "SELECT c.FirstName FROM SalesLT.Customer c " +
		"JOIN (SELECT CustomerID, COUNT(*) AS OrderCount FROM SalesLT.SalesOrderHeader GROUP BY CustomerID) AS d " +
		"ON c.CustomerID = d.CustomerID WHERE d.OrderCount > 5"

	t.Run("71_derived_where_traced_to_source", func(t *testing.T) {
		it := intentsOf(t, reg, derived)
		if !hasIntent(it, "SalesOrderHeader", "CustomerID", "FILTER", "SalesLT") {
			t.Errorf("%+v", it)
		}
	})
	t.Run("71_derived_join_on_filter", func(t *testing.T) {
		it := intentsOf(t, reg, derived)
		if !hasIntent(it, "Customer", "CustomerID", "FILTER", "SalesLT") {
			t.Errorf("%+v", it)
		}
	})
	t.Run("71_derived_inner_columns", func(t *testing.T) {
		it := intentsOf(t, reg, derived)
		if !hasIntent(it, "SalesOrderHeader", "CustomerID", "FILTER", "SalesLT") {
			t.Errorf("%+v", it)
		}
	})

	del := "DELETE FROM SalesLT.Address WHERE AddressID IN (" +
		"SELECT AddressID FROM SalesLT.CustomerAddress ca WHERE ca.AddressID = Address.AddressID)"

	t.Run("72_delete_correlated_outer_ref_filter", func(t *testing.T) {
		it := intentsOf(t, reg, del)
		if !hasIntent(it, "Address", "AddressID", "FILTER", "SalesLT") {
			t.Errorf("%+v", it)
		}
	})
	t.Run("72_delete_correlated_inner_filter", func(t *testing.T) {
		it := intentsOf(t, reg, del)
		if !hasIntent(it, "CustomerAddress", "AddressID", "FILTER", "SalesLT") {
			t.Errorf("%+v", it)
		}
	})
	t.Run("72_delete_outer_where_extracted", func(t *testing.T) {
		it := intentsOf(t, reg, del)
		if !hasIntent(it, "Address", "AddressID", "FILTER", "SalesLT") {
			t.Errorf("%+v", it)
		}
	})

	upd := "UPDATE SalesLT.Customer SET SalesPerson = (" +
		"SELECT TOP 1 SalesPerson FROM SalesLT.Customer c2 WHERE c2.CustomerID < 100) WHERE CustomerID = 10"

	t.Run("73_update_set_rhs_subquery_inner_filter", func(t *testing.T) {
		it := intentsOf(t, reg, upd)
		if !hasIntent(it, "Customer", "CustomerID", "FILTER", "SalesLT") {
			t.Errorf("%+v", it)
		}
	})
	t.Run("73_update_set_column_is_update", func(t *testing.T) {
		it := intentsOf(t, reg, upd)
		if !hasIntent(it, "Customer", "SalesPerson", "UPDATE", "SalesLT") {
			t.Errorf("%+v", it)
		}
	})
	t.Run("73_update_outer_where_filter", func(t *testing.T) {
		it := intentsOf(t, reg, upd)
		if !hasIntent(it, "Customer", "CustomerID", "FILTER", "SalesLT") {
			t.Errorf("%+v", it)
		}
	})
}
