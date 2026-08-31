package birdeye

import (
	"slices"
	"testing"
)

// 對照 birdeye_1150831/tests/test_schema_registry_suite.py（binder 整合部分見 binder_test.go）

func mkReg(t *testing.T, csv string) *MetadataRegistry {
	t.Helper()
	r := NewMetadataRegistry()
	if err := r.LoadFromCSV(csv); err != nil {
		t.Fatalf("LoadFromCSV: %v", err)
	}
	return r
}

const csvWithSchemaHeader = "table_schema,table_name,column_name,data_type\n" +
	"SalesLT,Customer,CustomerID,int\n" +
	"SalesLT,Customer,FirstName,nvarchar\n" +
	"SalesLT,Customer,EmailAddress,nvarchar\n" +
	"SalesLT,Address,AddressID,int\n" +
	"SalesLT,Address,City,nvarchar\n"

const csvWithSchemaNoHeader = "SalesLT,Customer,CustomerID,int\n" +
	"SalesLT,Customer,FirstName,nvarchar\n" +
	"SalesLT,Address,AddressID,int\n" +
	"SalesLT,Address,City,nvarchar\n"

const csv3ColNoHeader = "Customer,CustomerID,int\nCustomer,FirstName,nvarchar\nAddress,AddressID,int\n"
const csv3ColHeader = "table_name,column_name,data_type\nCustomer,CustomerID,int\nCustomer,FirstName,nvarchar\n"
const csvMultiSchema = "table_schema,table_name,column_name,data_type\n" +
	"SalesLT,Customer,CustomerID,int\n" +
	"SalesLT,Customer,EmailAddress,nvarchar\n" +
	"HR,Customer,EmployeeID,int\n" +
	"HR,Customer,Department,nvarchar\n"

func TestRegistrySchemaSuite(t *testing.T) {
	t.Run("4col_header_has_table", func(t *testing.T) {
		r := mkReg(t, csvWithSchemaHeader)
		if !r.HasTable("SalesLT.Customer") || !r.HasTable("SalesLT.Address") {
			t.Fatal()
		}
	})
	t.Run("4col_header_columns", func(t *testing.T) {
		cols := mkReg(t, csvWithSchemaHeader).GetColumns("SalesLT.Customer")
		for _, want := range []string{"CUSTOMERID", "FIRSTNAME", "EMAILADDRESS"} {
			if !slices.Contains(cols, want) {
				t.Fatalf("%v missing %s", cols, want)
			}
		}
	})
	t.Run("4col_header_has_column", func(t *testing.T) {
		r := mkReg(t, csvWithSchemaHeader)
		if !r.HasColumn("SalesLT.Customer", "CustomerID") || r.GetColumnType("SalesLT.Customer", "CustomerID") != "INT" {
			t.Fatal()
		}
	})
	t.Run("4col_no_header_has_table", func(t *testing.T) {
		r := mkReg(t, csvWithSchemaNoHeader)
		if !r.HasTable("SalesLT.Customer") || !r.HasTable("SalesLT.Address") {
			t.Fatal()
		}
	})
	t.Run("4col_no_header_columns", func(t *testing.T) {
		cols := mkReg(t, csvWithSchemaNoHeader).GetColumns("SalesLT.Customer")
		if !slices.Contains(cols, "CUSTOMERID") || !slices.Contains(cols, "FIRSTNAME") {
			t.Fatal(cols)
		}
	})

	t.Run("3col_backward_compat", func(t *testing.T) {
		r := mkReg(t, csv3ColNoHeader)
		if !r.HasTable("Customer") || !r.HasColumn("Customer", "CustomerID") {
			t.Fatal()
		}
	})
	t.Run("3col_schema_qualified_fallback", func(t *testing.T) {
		r := mkReg(t, csv3ColNoHeader)
		if !r.HasTable("SalesLT.Customer") {
			t.Fatal("has_table fallback")
		}
		if !slices.Contains(r.GetColumns("SalesLT.Customer"), "CUSTOMERID") {
			t.Fatal("get_columns fallback")
		}
		if !r.HasColumn("SalesLT.Customer", "CustomerID") {
			t.Fatal("has_column fallback")
		}
	})
	t.Run("3col_with_header", func(t *testing.T) {
		r := mkReg(t, csv3ColHeader)
		if !r.HasTable("Customer") || r.GetColumnType("Customer", "CustomerID") != "INT" {
			t.Fatal()
		}
	})

	t.Run("4col_unqualified_single_schema", func(t *testing.T) {
		r := mkReg(t, csvWithSchemaHeader)
		if !r.HasTable("Customer") || !r.HasColumn("Customer", "CustomerID") ||
			r.GetColumnType("Customer", "CustomerID") != "INT" ||
			!slices.Contains(r.GetColumns("Customer"), "CUSTOMERID") {
			t.Fatal()
		}
	})
	t.Run("4col_unqualified_ambiguous", func(t *testing.T) {
		if mkReg(t, csvMultiSchema).HasTable("Customer") {
			t.Fatal("ambiguous 應不 fallback")
		}
	})

	t.Run("multi_schema_no_collision", func(t *testing.T) {
		r := mkReg(t, csvMultiSchema)
		if !r.HasTable("SalesLT.Customer") || !r.HasTable("HR.Customer") {
			t.Fatal()
		}
	})
	t.Run("multi_schema_columns_isolated", func(t *testing.T) {
		r := mkReg(t, csvMultiSchema)
		s := r.GetColumns("SalesLT.Customer")
		h := r.GetColumns("HR.Customer")
		if !slices.Contains(s, "CUSTOMERID") || !slices.Contains(s, "EMAILADDRESS") || slices.Contains(s, "EMPLOYEEID") {
			t.Fatal(s)
		}
		if !slices.Contains(h, "EMPLOYEEID") || !slices.Contains(h, "DEPARTMENT") || slices.Contains(h, "EMAILADDRESS") {
			t.Fatal(h)
		}
	})
	t.Run("multi_schema_type_isolated", func(t *testing.T) {
		r := mkReg(t, csvMultiSchema)
		if r.GetColumnType("SalesLT.Customer", "CustomerID") != "INT" ||
			!r.HasColumn("HR.Customer", "Department") || r.HasColumn("SalesLT.Customer", "Department") {
			t.Fatal()
		}
	})
	t.Run("multi_schema_column_count", func(t *testing.T) {
		r := mkReg(t, csvMultiSchema)
		if r.GetColumnCount("SalesLT.Customer") != 2 || r.GetColumnCount("HR.Customer") != 2 {
			t.Fatal()
		}
	})
}
