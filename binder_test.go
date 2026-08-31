package birdeye

import (
	"strings"
	"testing"
)

// 對照 birdeye_1150831/tests/test_semantic_suite.py
// 註：檢查 result["tree"] 的斷言改為直接檢查 AST（visualizer 為里程碑 10）。

func bindWith(t *testing.T, sql string, reg *MetadataRegistry) (Node, error) {
	t.Helper()
	toks, err := NewLexer(sql).Tokenize()
	if err != nil {
		return nil, err
	}
	ast, err := NewParser(toks, sql).Parse()
	if err != nil {
		return nil, err
	}
	return NewBinder(reg).Bind(ast, nil)
}

func semReg(t *testing.T) *MetadataRegistry {
	return mkReg(t, "table_name,column_name,data_type\n"+
		"Users,UserID,INT\nUsers,UserName,VARCHAR\nOrders,OrderID,INT\nOrders,UserID,INT\n")
}

func scopeReg(t *testing.T) *MetadataRegistry {
	return mkReg(t, "table_name,column_name,data_type\n"+
		"Users,ID,INT\nUsers,UserID,INT\nUsers,UserName,NVARCHAR\n"+
		"Orders,OrderID,INT\nOrders,UserID,INT\nA,ID,INT\nB,ID,INT\n")
}

func mustSemErr(t *testing.T, err error, want string) {
	t.Helper()
	if err == nil {
		t.Fatalf("預期 semantic error 含 %q，卻成功", want)
	}
	be, ok := err.(*Error)
	if !ok || be.Kind != ErrSemantic {
		t.Fatalf("預期 semantic error，得到 %v", err)
	}
	if want != "" && !strings.Contains(be.Msg, want) {
		t.Fatalf("錯誤 %q 不含 %q", be.Msg, want)
	}
}

func TestBinderSemanticSuite(t *testing.T) {
	aw := loadAdventureWorks(t)

	t.Run("zta_enforcement_real_meta", func(t *testing.T) {
		if _, err := NewRunner(aw).Run("SELECT c.FirstName FROM Customer AS c", nil); err != nil {
			t.Fatalf("valid case failed: %v", err)
		}
		_, err := NewRunner(aw).Run("SELECT Customer.FirstName FROM Customer AS c", nil)
		mustSemErr(t, err, "Original table name 'Customer' cannot be used when alias 'c' is defined")
		_, err = NewRunner(aw).Run("SELECT * FROM GhostTable", nil)
		mustSemErr(t, err, "Table 'GhostTable' not found")
	})

	t.Run("star_expansion_count", func(t *testing.T) {
		for _, sql := range []string{"SELECT * FROM Address", "SELECT a.* FROM Address a"} {
			res, err := NewRunner(aw).Run(sql, nil)
			if err != nil {
				t.Fatalf("%q: %v", sql, err)
			}
			if n := len(res.AST.(*SelectStatement).Columns); n != 9 {
				t.Errorf("%q: 展開 %d 欄，預期 9", sql, n)
			}
		}
	})

	t.Run("star_alias_conflict", func(t *testing.T) {
		_, err := NewRunner(aw).Run("SELECT Address.* FROM Address a", nil)
		mustSemErr(t, err, "Unknown qualifier 'Address' in star expansion")
	})

	t.Run("complex_identifiers_and_aliases", func(t *testing.T) {
		reg := semReg(t)
		cases := []struct{ sql, col, qual, alias string }{
			{"SELECT dbo.Users.UserID FROM Users", "UserID", "dbo.Users", ""},
			{"SELECT [Database].[dbo].[Users].[UserID] FROM [Users]", "UserID", "Database.dbo.Users", ""},
			{"SELECT u . UserID FROM Users AS u", "UserID", "u", "u"},
		}
		for _, c := range cases {
			n, err := bindWith(t, c.sql, reg)
			if err != nil {
				t.Fatalf("%q: %v", c.sql, err)
			}
			st := n.(*SelectStatement)
			id := st.Columns[0].(*IdentifierNode)
			if id.Name != c.col || id.Qualifier() != c.qual {
				t.Errorf("%q: got name=%q qual=%q want %q/%q", c.sql, id.Name, id.Qualifier(), c.col, c.qual)
			}
			if c.alias != "" && st.TableAlias != c.alias {
				t.Errorf("%q: alias got %q want %q", c.sql, st.TableAlias, c.alias)
			}
		}
	})

	t.Run("alias_invalidation_deep", func(t *testing.T) {
		_, err := bindWith(t, "SELECT Users.UserID FROM Users u", semReg(t))
		mustSemErr(t, err, "Original table name 'Users' cannot be used")
	})

	t.Run("external_param_type_inference", func(t *testing.T) {
		res, err := NewRunner(aw).Run(
			"SELECT AddressID FROM Address WHERE AddressID = @customerId",
			&OrderedParams{Keys: []string{"customerId"}, Vals: map[string]any{"customerId": 123}})
		if err != nil {
			t.Fatal(err)
		}
		w := res.AST.(*SelectStatement).Where.(*BinaryExpressionNode)
		if it := exprOf(w.Right).InferredType; it != "INT" {
			t.Errorf("@customerId inferred %q, want INT", it)
		}
		if m := metaOf(res.AST); m == nil || len(m.Params) != 1 || m.Params[0].Name != "@CUSTOMERID" || m.Params[0].Type != "INT" {
			t.Errorf("bound params: %+v", m)
		}
	})

	t.Run("structural_param_success", func(t *testing.T) {
		res, err := NewRunner(aw).Run(
			"SELECT TOP 5 ProductID FROM @tableName ORDER BY @sortCol",
			&OrderedParams{Keys: []string{"tableName", "sortCol"},
				Vals: map[string]any{"tableName": "Product", "sortCol": "ProductID"}})
		if err != nil {
			t.Fatal(err)
		}
		st := res.AST.(*SelectStatement)
		if st.Table.(*IdentifierNode).Name != "Product" {
			t.Errorf("table %q", st.Table.(*IdentifierNode).Name)
		}
		if st.OrderBy[0].Column.(*IdentifierNode).Name != "ProductID" {
			t.Errorf("order col %q", st.OrderBy[0].Column.(*IdentifierNode).Name)
		}
	})

	t.Run("structural_param_blocks_missing_value", func(t *testing.T) {
		_, err := NewRunner(aw).Run("SELECT TOP 1 * FROM @tableName", nil)
		mustSemErr(t, err, "requires a runtime parameter value")
	})

	t.Run("structural_param_blocks_unsafe", func(t *testing.T) {
		_, err := NewRunner(aw).Run("SELECT TOP 5 ProductID FROM Product ORDER BY @sortCol",
			&OrderedParams{Keys: []string{"sortCol"}, Vals: map[string]any{"sortCol": "ProductID; DROP TABLE Users;--"}})
		mustSemErr(t, err, "unsafe identifier")
	})

	t.Run("structural_param_blocks_unknown_table", func(t *testing.T) {
		_, err := NewRunner(aw).Run("SELECT TOP 1 * FROM @tableName",
			&OrderedParams{Keys: []string{"tableName"}, Vals: map[string]any{"tableName": "GhostTable"}})
		mustSemErr(t, err, "Table 'GhostTable' not found")
	})

	t.Run("structural_param_changes_json", func(t *testing.T) {
		sql := "SELECT ProductID, Name, ListPrice FROM Product ORDER BY @sortCol"
		a, _ := NewRunner(aw).Run(sql, &OrderedParams{Keys: []string{"sortCol"}, Vals: map[string]any{"sortCol": "ProductID"}})
		b, _ := NewRunner(aw).Run(sql, &OrderedParams{Keys: []string{"sortCol"}, Vals: map[string]any{"sortCol": "Name"}})
		if a == nil || b == nil || a.JSON == b.JSON {
			t.Errorf("不同結構參數應產生不同 JSON")
		}
	})

	t.Run("qmark_count_mismatch", func(t *testing.T) {
		_, err := NewRunner(aw).Run("SELECT ProductID FROM Product WHERE ProductID = ? AND Name = ?", []any{1})
		if be, ok := err.(*Error); !ok || be.Kind != ErrValue || !strings.Contains(be.Msg, "PARAM_COUNT_MISMATCH") {
			t.Errorf("got %v", err)
		}
	})

	t.Run("qmark_mixed_mode", func(t *testing.T) {
		_, err := NewRunner(aw).Run("SELECT ProductID FROM Product WHERE ProductID = ?",
			&OrderedParams{Keys: []string{"productId"}, Vals: map[string]any{"productId": 1}})
		if be, ok := err.(*Error); !ok || be.Kind != ErrValue || !strings.Contains(be.Msg, "PARAM_MODE_MIXED") {
			t.Errorf("got %v", err)
		}
	})

	t.Run("type_checks", func(t *testing.T) {
		_, err := NewRunner(aw).Run("SELECT UPPER(ProductID) FROM Product", nil)
		mustSemErr(t, err, "Function 'UPPER' expects NVARCHAR")
		_, err = NewRunner(aw).Run("SELECT Name + 100 FROM Product", nil)
		mustSemErr(t, err, "Operator '+' cannot be applied to")
		_, err = NewRunner(aw).Run("SELECT CASE WHEN ProductID = 1 THEN 'Admin' ELSE 999 END FROM Product", nil)
		mustSemErr(t, err, "CASE branches have incompatible types")
		_, err = NewRunner(aw).Run("SELECT Name / 2 FROM Product", nil)
		mustSemErr(t, err, "Operator '/' cannot be applied")
	})

	t.Run("subquery_in_where_parsing", func(t *testing.T) {
		n := mustParse(t, "SELECT UserName FROM Users WHERE UserID IN (SELECT UserID FROM Orders)")
		w := n.(*SelectStatement).Where.(*BinaryExpressionNode)
		if nodeTypeName(w.Right) != "SelectStatement" {
			t.Errorf("IN 右側 %s", nodeTypeName(w.Right))
		}
	})

	t.Run("subquery_scope_isolation", func(t *testing.T) {
		_, err := bindWith(t,
			"SELECT * FROM Users u WHERE UserID IN (SELECT UserID FROM Orders o) AND o.OrderID > 0", scopeReg(t))
		mustSemErr(t, err, "Unknown qualifier 'o'")
	})

	t.Run("correlated_subquery_binding", func(t *testing.T) {
		n, err := bindWith(t, `
			SELECT UserName FROM Users u
			WHERE EXISTS ( SELECT 1 FROM Orders o WHERE o.UserID = u.UserID )`, scopeReg(t))
		if err != nil {
			t.Fatal(err)
		}
		innerSel := n.(*SelectStatement).Where.(*FunctionCallNode).Args[0].(*SelectStatement)
		innerWhere := innerSel.Where.(*BinaryExpressionNode)
		if q := innerWhere.Right.(*IdentifierNode).Qualifier(); q != "u" {
			t.Errorf("correlated qualifier %q, want u", q)
		}
	})

	t.Run("triple_nested_scopes", func(t *testing.T) {
		_, err := bindWith(t,
			"SELECT * FROM Users WHERE ID IN (SELECT ID FROM A WHERE ID IN (SELECT ID FROM B))", scopeReg(t))
		if err != nil {
			if be, ok := err.(*Error); ok && be.Kind == ErrSemantic && strings.Contains(be.Msg, "Table 'A' not found") {
				return
			}
			t.Fatalf("非預期錯誤: %v", err)
		}
	})
}
