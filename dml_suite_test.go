package birdeye

import (
	"encoding/json"
	"strings"
	"testing"
)

// 對照 python-final:tests/test_dml_suite.py

func awRunErr(t *testing.T, aw *MetadataRegistry, sql string) error {
	t.Helper()
	_, err := NewRunner(aw).Run(sql, nil)
	return err
}

func TestDML_ParsingSuccess(t *testing.T) {
	cases := []struct {
		sql      string
		typ      string
		table    string
		setCount int
	}{
		{"UPDATE Product SET Name = 'Bird' WHERE ProductID = 1", "UpdateStatement", "PRODUCT", 1},
		{"UPDATE Product SET Name = 'New', Color = 'Blue' WHERE ProductID = 1", "UpdateStatement", "PRODUCT", 2},
		{"DELETE FROM Product WHERE ProductID = 1", "DeleteStatement", "PRODUCT", 0},
	}
	for _, c := range cases {
		n := mustParse(t, c.sql)
		if nodeTypeName(n) != c.typ {
			t.Errorf("%q -> %s want %s", c.sql, nodeTypeName(n), c.typ)
		}
		switch st := n.(type) {
		case *UpdateStatement:
			if strings.ToUpper(st.Table.Name) != c.table {
				t.Errorf("%q table %s", c.sql, st.Table.Name)
			}
			if len(st.SetClauses) != c.setCount {
				t.Errorf("%q set count %d want %d", c.sql, len(st.SetClauses), c.setCount)
			}
			if st.Where == nil {
				t.Errorf("%q where nil", c.sql)
			}
		case *DeleteStatement:
			if strings.ToUpper(st.Table.Name) != c.table {
				t.Errorf("%q table %s", c.sql, st.Table.Name)
			}
			if st.Where == nil {
				t.Errorf("%q where nil", c.sql)
			}
		}
	}
}

func TestDML_SemanticErrors(t *testing.T) {
	aw := loadAdventureWorks(t)
	cases := []struct{ sql, want string }{
		{"UPDATE Product SET GhostColumn = 1 WHERE ProductID = 1", "Column 'GhostColumn' not found in 'Product'"},
		{"DELETE FROM Product WHERE UnknownCol = 99", "Column 'UnknownCol' not found in 'Product'"},
		{"UPDATE Product SET ListPrice = 'Free' WHERE ProductID = 1", "Cannot compare MONEY with NVARCHAR"},
	}
	for _, c := range cases {
		err := awRunErr(t, aw, c.sql)
		if err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%q -> err %v，want 含 %q", c.sql, err, c.want)
		}
	}
}

func TestDML_InsertParsingSuccess(t *testing.T) {
	aw := loadAdventureWorks(t)
	cases := []struct {
		sql              string
		table            string
		colCount, valCnt int
	}{
		{"INSERT INTO Product (ProductID, Name) VALUES (1, 'Bird')", "PRODUCT", 2, 2},
		{"INSERT INTO Product (ProductID, Name, SellStartDate) VALUES (1, 'A', GETDATE())", "PRODUCT", 3, 3},
	}
	for _, c := range cases {
		res, err := NewRunner(aw).Run(c.sql, nil)
		if err != nil {
			t.Fatalf("%q: %v", c.sql, err)
		}
		ins, ok := res.AST.(*InsertStatement)
		if !ok {
			t.Fatalf("%q -> %s", c.sql, nodeTypeName(res.AST))
		}
		if strings.ToUpper(ins.Table.Name) != c.table {
			t.Errorf("%q table %s", c.sql, ins.Table.Name)
		}
		if len(ins.Columns) != c.colCount {
			t.Errorf("%q col count %d want %d", c.sql, len(ins.Columns), c.colCount)
		}
		if len(ins.Values) != c.valCnt {
			t.Errorf("%q val count %d want %d", c.sql, len(ins.Values), c.valCnt)
		}
	}
}

func TestDML_InsertSemanticErrors(t *testing.T) {
	aw := loadAdventureWorks(t)
	cases := []struct{ sql, want string }{
		{"INSERT INTO Product (ProductID, Name) VALUES (1)", "Column count mismatch: Expected 2, got 1"},
		{"INSERT INTO Product (GhostColumn) VALUES (1)", "Column 'GhostColumn' not found in 'Product'"},
		{"INSERT INTO Product (StandardCost) VALUES ('High')", "Cannot compare MONEY with NVARCHAR"},
		{"INSERT INTO Product VALUES (1, 'A')", "Column count mismatch: Expected 17, got 2"},
	}
	for _, c := range cases {
		err := awRunErr(t, aw, c.sql)
		if err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%q -> err %v，want 含 %q", c.sql, err, c.want)
		}
	}
}

func TestDML_BulkCopy(t *testing.T) {
	n := mustParse(t, "BULK INSERT INTO Product")
	bc, ok := n.(*SqlBulkCopyStatement)
	if !ok {
		t.Fatalf("-> %s", nodeTypeName(n))
	}
	if strings.ToUpper(bc.Table.Name) != "PRODUCT" {
		t.Errorf("table %s", bc.Table.Name)
	}
	aw := loadAdventureWorks(t)
	if err := awRunErr(t, aw, "BULK INSERT INTO NonExistentTable"); err == nil ||
		!strings.Contains(err.Error(), "Table 'NonExistentTable' not found") {
		t.Errorf("-> %v", err)
	}
}

func TestDML_InsertSelect(t *testing.T) {
	aw := loadAdventureWorks(t)

	ast := mustParse(t, "INSERT INTO Address (AddressID, City) SELECT AddressID, City FROM Address")
	ins := ast.(*InsertStatement)
	if _, ok := ins.Source.(*SelectStatement); !ok {
		t.Fatalf("source %s", nodeTypeName(ins.Source))
	}
	if _, ok := mustParse(t, "INSERT INTO Address SELECT AddressID, City FROM Address").(*InsertStatement); !ok {
		t.Errorf("no-columns INSERT-SELECT 解析失敗")
	}

	if _, err := NewRunner(aw).Run("INSERT INTO Address (AddressID, City) SELECT AddressID, City FROM Address WHERE AddressID = 1", nil); err != nil {
		t.Errorf("basic INSERT-SELECT: %v", err)
	}
	if err := awRunErr(t, aw, "INSERT INTO Address (AddressID, City) SELECT City, AddressID FROM Address"); err == nil {
		t.Errorf("型別不符應報錯")
	}
	if err := awRunErr(t, aw, "INSERT INTO Address (AddressID) SELECT AddressID, City FROM Address"); err == nil {
		t.Errorf("欄位數不符應報錯")
	}

	// 序列化
	data := map[string]any{}
	json.Unmarshal([]byte(NewSerializer().ToJSON(mustParse(t, "INSERT INTO Address (AddressID) SELECT AddressID FROM Address"))), &data)
	if data["node_type"] != "InsertStatement" || data["source"] == nil || data["values"] != nil {
		t.Errorf("序列化: %v", data)
	}
	src := data["source"].(map[string]any)
	if src["node_type"] != "SelectStatement" {
		t.Errorf("source node_type: %v", src["node_type"])
	}

	// 視覺化
	out := NewVisualizer().Dump(mustParse(t, "INSERT INTO Address (AddressID) SELECT AddressID FROM Address"))
	if !strings.Contains(out, "INSERT_STATEMENT") || !strings.Contains(out, "SOURCE") {
		t.Errorf("視覺化: %s", out)
	}
}

func TestDML_MultiRowValues(t *testing.T) {
	aw := loadAdventureWorks(t)

	ast := mustParse(t, "INSERT INTO Address (AddressID, City) VALUES (1, 'A'), (2, 'B'), (3, 'C')").(*InsertStatement)
	if len(ast.ValueRows) != 3 {
		t.Errorf("value_rows %d", len(ast.ValueRows))
	}
	single := mustParse(t, "INSERT INTO Address (AddressID, City) VALUES (1, 'Taipei')").(*InsertStatement)
	if len(single.ValueRows) != 1 {
		t.Errorf("single value_rows %d", len(single.ValueRows))
	}

	if _, err := NewRunner(aw).Run("INSERT INTO Address (AddressID, City) VALUES (1, 'A'), (2, 'B')", nil); err != nil {
		t.Errorf("multi-row: %v", err)
	}
	if _, err := NewRunner(aw).Run("INSERT INTO Address (AddressID, City) VALUES (10, 'X'), (20, 'Y'), (30, 'Z')", nil); err != nil {
		t.Errorf("multi-row type check: %v", err)
	}
	if err := awRunErr(t, aw, "INSERT INTO Address (AddressID, City) VALUES (1, 'A'), ('bad', 2)"); err == nil {
		t.Errorf("其中一列型別錯誤應報錯")
	}

	data := map[string]any{}
	json.Unmarshal([]byte(NewSerializer().ToJSON(mustParse(t, "INSERT INTO Address (AddressID, City) VALUES (1, 'A'), (2, 'B')"))), &data)
	rows, ok := data["value_rows"].([]any)
	if !ok || len(rows) != 2 {
		t.Errorf("value_rows 序列化: %v", data["value_rows"])
	}

	out := NewVisualizer().Dump(mustParse(t, "INSERT INTO Address (AddressID, City) VALUES (1, 'A'), (2, 'B')"))
	if !strings.Contains(out, "VALUES ROW #1") || !strings.Contains(out, "VALUES ROW #2") {
		t.Errorf("視覺化: %s", out)
	}
}

func TestDML_Truncate(t *testing.T) {
	for _, c := range []struct{ sql, table string }{
		{"TRUNCATE TABLE Address", "Address"},
		{"TRUNCATE TABLE [Address]", "Address"},
		{"TRUNCATE TABLE dbo.Address", "Address"},
		{"TRUNCATE TABLE [dbo].[Address]", "Address"},
	} {
		n := mustParse(t, c.sql)
		tr, ok := n.(*TruncateStatement)
		if !ok {
			t.Fatalf("%q -> %s", c.sql, nodeTypeName(n))
		}
		if tr.Table.Name != c.table {
			t.Errorf("%q table %q", c.sql, tr.Table.Name)
		}
	}

	reg := mkReg(t, "table_name,column_name,data_type\nAddress,AddressID,INT\nAddress,City,VARCHAR\n")
	if _, err := NewRunner(reg).Run("TRUNCATE TABLE Address", nil); err != nil {
		t.Errorf("existing table: %v", err)
	}
	if _, err := NewRunner(reg).Run("TRUNCATE TABLE NonExistentTable", nil); err == nil ||
		!strings.Contains(err.Error(), "Table 'NonExistentTable' not found") {
		t.Errorf("-> %v", err)
	}

	for _, bad := range []string{"TRUNCATE Users", "TRUNCATE TABLE", "TRUNCATE TABLE Users ExtraStuff"} {
		err := parseErr(t, bad)
		if e, ok := err.(*Error); !ok || e.Kind != ErrSyntax {
			t.Errorf("%q -> %v（want syntax error）", bad, err)
		}
	}
}
