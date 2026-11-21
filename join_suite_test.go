package birdeye

import (
	"encoding/json"
	"strings"
	"testing"
)

// 對照 python-final:tests/test_join_suite.py（+ multi_table / nullable / not_pagination）

func TestJoin_BasicSyntax(t *testing.T) {
	aw := loadAdventureWorks(t)
	for _, sql := range []string{
		"SELECT h.SalesOrderID FROM SalesOrderHeader h JOIN SalesOrderDetail d ON h.SalesOrderID = d.SalesOrderID",
		"SELECT h.SalesOrderID FROM SalesOrderHeader h LEFT JOIN Address a ON h.ShipToAddressID = a.AddressID",
	} {
		st := intgRun(t, aw, sql).AST.(*SelectStatement)
		if len(st.Joins) != 1 {
			t.Errorf("%q joins %d", sql, len(st.Joins))
		}
	}
}

func TestJoin_ZTADefenses(t *testing.T) {
	aw := loadAdventureWorks(t)
	intgErr(t, aw, "SELECT SalesOrderID FROM SalesOrderHeader h JOIN SalesOrderDetail d ON h.SalesOrderID = d.SalesOrderID", "Column 'SalesOrderID' is ambiguous")
	intgErr(t, aw, "SELECT ModifiedDate FROM Address a JOIN SalesOrderHeader h ON a.AddressID = h.ShipToAddressID", "Column 'ModifiedDate' is ambiguous")
	intgErr(t, aw, "SELECT SalesOrderHeader.SalesOrderID FROM SalesOrderHeader h JOIN SalesOrderDetail d ON h.SalesOrderID = d.SalesOrderID", "Original table name 'SalesOrderHeader' cannot be used when alias 'h' is defined")
	intgErr(t, aw, "SELECT ProductID FROM SalesOrderDetail d JOIN Product p ON d.ProductID = p.ProductID", "Column 'ProductID' is ambiguous")
	intgErr(t, aw, "SELECT Address.City FROM Address AS a JOIN Customer AS c ON a.AddressID = c.CustomerID", "Original table name 'Address' cannot be used")
	intgErr(t, aw, "SELECT d.SalesOrderID, p.GhostCol FROM SalesOrderDetail d JOIN Product p ON d.ProductID = p.ProductID", "Column 'GhostCol' not found")
	// 逗號 join 禁止
	if _, err := NewRunner(aw).Run("SELECT * FROM SalesOrderHeader, SalesOrderDetail", nil); err == nil || !strings.Contains(err.Error(), "Expected FROM") {
		t.Errorf("comma join -> %v", err)
	}
}

func TestJoin_OnScope(t *testing.T) {
	aw := loadAdventureWorks(t)
	jn := intgRun(t, aw, "SELECT h.SalesOrderID FROM SalesOrderHeader h JOIN SalesOrderDetail d ON h.SalesOrderID = d.SalesOrderID").AST.(*SelectStatement).Joins[0]
	if jn.OnLeft.(*IdentifierNode).Qualifiers[0] != "h" || jn.OnRight.(*IdentifierNode).Qualifiers[0] != "d" {
		t.Errorf("ON scope: %+v / %+v", jn.OnLeft, jn.OnRight)
	}
}

func TestJoin_Nullability(t *testing.T) {
	aw := loadAdventureWorks(t)
	for _, sql := range []string{
		"SELECT a.City, c.FirstName FROM Address a LEFT JOIN Customer c ON a.AddressID = c.CustomerID",
		"SELECT a.City, c.FirstName FROM Address a RIGHT JOIN Customer c ON a.AddressID = c.CustomerID",
	} {
		if _, err := NewRunner(aw).Run(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
	res, _ := NewRunner(aw).Run("SELECT a.AddressID FROM Address a FULL OUTER JOIN Address b ON a.AddressID = b.AddressID", nil)
	if !res.Binder.LastRootNullables()["B"] {
		t.Errorf("FULL OUTER JOIN B nullable: %v", res.Binder.LastRootNullables())
	}
}

func TestJoin_NotInNotExists(t *testing.T) {
	aw := loadAdventureWorks(t)
	oks := []string{
		"SELECT AddressID FROM Address WHERE AddressID NOT IN (1, 2, 3)",
		"SELECT AddressID FROM Address WHERE AddressID NOT IN (SELECT AddressID FROM Address WHERE AddressID = 1)",
		"SELECT AddressID FROM Address WHERE NOT EXISTS (SELECT 1 FROM Address WHERE AddressID = 0)",
		"SELECT a.AddressID FROM Address a WHERE NOT EXISTS (SELECT 1 FROM Address b WHERE b.AddressID = a.AddressID AND b.AddressID < 0)",
	}
	for _, sql := range oks {
		if _, err := NewRunner(aw).Run(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
	if _, err := NewRunner(aw).Run("SELECT AddressID FROM Address WHERE AddressID NOT IN ('X', 'Y')", nil); err == nil {
		t.Error("NOT IN 型別不符應報錯")
	}

	notIn := mustParse(t, "SELECT A FROM T WHERE A NOT IN (1, 2)").(*SelectStatement).Where.(*BinaryExpressionNode)
	if notIn.Operator != "NOT IN" {
		t.Errorf("NOT IN operator: %q", notIn.Operator)
	}
	notEx := mustParse(t, "SELECT A FROM T WHERE NOT EXISTS (SELECT 1 FROM T)").(*SelectStatement).Where.(*FunctionCallNode)
	if notEx.Name != "NOT EXISTS" {
		t.Errorf("NOT EXISTS name: %q", notEx.Name)
	}
}

func TestJoin_CrossFullOuter(t *testing.T) {
	aw := loadAdventureWorks(t)

	if has := tokenPresent(t, "SELECT A FROM T CROSS JOIN T2", KwCross); !has {
		t.Error("CROSS token")
	}
	if has := tokenPresent(t, "SELECT A FROM T FULL OUTER JOIN T2 ON T.A = T2.A", KwFull); !has {
		t.Error("FULL token")
	}

	cj := mustParse(t, "SELECT A FROM T CROSS JOIN T2").(*SelectStatement)
	if len(cj.Joins) != 1 || cj.Joins[0].Type != "CROSS" || cj.Joins[0].OnCondition != nil {
		t.Errorf("CROSS JOIN: %+v", cj.Joins[0])
	}
	fj := mustParse(t, "SELECT A FROM T FULL OUTER JOIN T2 ON T.A = T2.A").(*SelectStatement)
	if fj.Joins[0].Type != "FULL" {
		t.Errorf("FULL JOIN type: %q", fj.Joins[0].Type)
	}

	for _, sql := range []string{
		"SELECT a.AddressID FROM Address a CROSS JOIN Address b",
		"SELECT a.AddressID FROM Address a CROSS JOIN Address b WHERE a.AddressID = 1",
		"SELECT a.AddressID FROM Address a FULL OUTER JOIN Address b ON a.AddressID = b.AddressID",
	} {
		if _, err := NewRunner(aw).Run(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
}

func tokenPresent(t *testing.T, sql string, want TokenType) bool {
	t.Helper()
	for _, tk := range mustTokens(t, sql) {
		if tk.Type == want {
			return true
		}
	}
	return false
}

func TestJoin_OffsetFetch(t *testing.T) {
	aw := loadAdventureWorks(t)
	if !tokenPresent(t, "SELECT A FROM T ORDER BY A OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY", KwOffset) ||
		!tokenPresent(t, "SELECT A FROM T ORDER BY A OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY", KwFetch) {
		t.Error("OFFSET/FETCH tokens")
	}
	st := mustParse(t, "SELECT A FROM T ORDER BY A OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY").(*SelectStatement)
	if st.OffsetCount == nil || *st.OffsetCount != 10 || st.FetchCount == nil || *st.FetchCount != 5 {
		t.Errorf("offset/fetch: %v %v", st.OffsetCount, st.FetchCount)
	}
	data := map[string]any{}
	json.Unmarshal([]byte(NewSerializer().ToJSON(st)), &data)
	if data["offset_count"].(float64) != 10 || data["fetch_count"].(float64) != 5 {
		t.Errorf("serialize offset/fetch: %v", data)
	}
	out := NewVisualizer().Dump(st)
	if !strings.Contains(out, "OFFSET: 10") || !strings.Contains(out, "FETCH NEXT: 5") {
		t.Errorf("viz offset/fetch: %s", out)
	}
	for _, sql := range []string{
		"SELECT AddressID FROM Address ORDER BY AddressID OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY",
		"SELECT AddressID FROM Address ORDER BY AddressID OFFSET 5 ROWS",
	} {
		if _, err := NewRunner(aw).Run(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
}
