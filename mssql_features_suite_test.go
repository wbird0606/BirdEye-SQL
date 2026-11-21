package birdeye

import (
	"strings"
	"testing"
)

// 對照 python-final:tests/test_mssql_features_suite.py
// （declare_go / temp_table / apply / advanced_types）

func TestMSSQLFeat_LexerAndDeclare(t *testing.T) {
	if mustTokens(t, "DECLARE @var INT")[0].Type != KwDeclare {
		t.Error("DECLARE keyword")
	}
	at := mustTokens(t, "@myVar")[0]
	if at.Type != Identifier || at.Value != "@myVar" {
		t.Errorf("@var: %v %q", at.Type, at.Value)
	}
	for _, s := range []string{"GO", "go", "Go", "gO"} {
		if mustTokens(t, s)[0].Type != KwGo {
			t.Errorf("GO keyword for %q", s)
		}
	}

	d1 := mustParse(t, "DECLARE @counter INT").(*DeclareStatement)
	if d1.VarName != "@counter" || d1.VarType != "INT" {
		t.Errorf("DECLARE simple: %+v", d1)
	}
	d2 := mustParse(t, "DECLARE @name NVARCHAR(50)").(*DeclareStatement)
	if d2.VarName != "@name" || d2.VarType != "NVARCHAR" {
		t.Errorf("DECLARE size: %+v", d2)
	}
	d3 := mustParse(t, "DECLARE @count INT = 0").(*DeclareStatement)
	if d3.DefaultValue == nil {
		t.Error("DECLARE default value")
	}
	if _, ok := mustParse(t, "DECLARE @x INT;").(*DeclareStatement); !ok {
		t.Error("DECLARE trailing semicolon")
	}
}

func TestMSSQLFeat_DeclareBinding(t *testing.T) {
	aw := loadAdventureWorks(t)
	if _, err := NewRunner(aw).RunScript("DECLARE @id INT", nil); err != nil {
		t.Errorf("run_script DECLARE: %v", err)
	}
	if _, err := NewRunner(aw).RunScript("DECLARE @id INT\nSELECT AddressID FROM Address WHERE AddressID = @id", nil); err != nil {
		t.Errorf("var usable in WHERE: %v", err)
	}
	if _, err := NewRunner(aw).Run("SELECT AddressID FROM Address WHERE AddressID = @undeclared", nil); err != nil {
		t.Errorf("undeclared @param as external: %v", err)
	}
}

func TestMSSQLFeat_RunScript(t *testing.T) {
	aw := loadAdventureWorks(t)
	b1, err := NewRunner(aw).RunScript("SELECT AddressID FROM Address\nGO\nSELECT City FROM Address", nil)
	if err != nil || len(b1) != 2 {
		t.Errorf("GO splits: %v len=%d", err, len(b1))
	}
	b2, err := NewRunner(aw).RunScript("DECLARE @id INT; SELECT AddressID FROM Address WHERE AddressID = @id", nil)
	if err != nil || len(b2) != 1 || len(b2[0]) != 2 {
		t.Errorf("semicolon splits: %v %v", err, b2)
	}
	if _, err := NewRunner(aw).RunScript("DECLARE @id INT\nGO\nSELECT AddressID FROM Address WHERE AddressID = @id", nil); err != nil {
		t.Errorf("var scope across GO: %v", err)
	}
}

func TestMSSQLFeat_TempTable(t *testing.T) {
	aw := loadAdventureWorks(t)
	st := intgRun(t, aw, "SELECT AddressID, City INTO #MyTemp FROM Address").AST.(*SelectStatement)
	if st.IntoTable == nil || st.IntoTable.Name != "#MyTemp" || st.Table.(*IdentifierNode).Name != "Address" {
		t.Errorf("SELECT INTO: %+v", st)
	}
	hash := intgRun(t, aw, "SELECT * FROM #TempTable").AST.(*SelectStatement)
	if hash.Table.(*IdentifierNode).Name != "#TempTable" {
		t.Errorf("# prefix: %v", hash.Table)
	}
	// 連續語句：SELECT INTO 後臨時表可查（同一 RunScript）
	if _, err := NewRunner(aw).RunScript("SELECT AddressID, City INTO #T1 FROM Address\nGO\nSELECT AddressID FROM #T1", nil); err != nil {
		t.Errorf("temp table scope: %v", err)
	}
}

func TestMSSQLFeat_Apply(t *testing.T) {
	aw := loadAdventureWorks(t)

	if mustTokens(t, "CROSS APPLY")[0].Type != KwCross || mustTokens(t, "CROSS APPLY")[1].Type != KwApply {
		t.Error("CROSS APPLY keywords")
	}
	if mustTokens(t, "OUTER APPLY")[0].Type != KwOuter {
		t.Error("OUTER keyword")
	}

	ca := mustParse(t, "SELECT a.AddressID, sub.City FROM Address a CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub").(*SelectStatement)
	if len(ca.Applies) != 1 || ca.Applies[0].Type != "CROSS" || ca.Applies[0].Alias != "sub" {
		t.Errorf("CROSS APPLY node: %+v", ca.Applies)
	}
	if _, ok := ca.Applies[0].Subquery.(*SelectStatement); !ok {
		t.Errorf("apply subquery type: %T", ca.Applies[0].Subquery)
	}
	oa := mustParse(t, "SELECT a.AddressID, sub.City FROM Address a OUTER APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub").(*SelectStatement)
	if oa.Applies[0].Type != "OUTER" {
		t.Errorf("OUTER APPLY type: %q", oa.Applies[0].Type)
	}
	coex := mustParse(t, "SELECT a.AddressID, b.City, sub.City FROM Address a INNER JOIN Address b ON a.AddressID = b.AddressID CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub").(*SelectStatement)
	if len(coex.Joins) != 1 || len(coex.Applies) != 1 {
		t.Errorf("JOIN + APPLY coexist: joins=%d applies=%d", len(coex.Joins), len(coex.Applies))
	}

	for _, sql := range []string{
		"SELECT a.AddressID, sub.City FROM Address a CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub",
		"SELECT a.AddressID, sub.City FROM Address a OUTER APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub",
	} {
		if _, err := NewRunner(aw).Run(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
	res, _ := NewRunner(aw).Run("SELECT a.AddressID, sub.City FROM Address a OUTER APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub", nil)
	if !res.Binder.NullableScopes()["SUB"] {
		t.Errorf("OUTER APPLY nullable: %v", res.Binder.NullableScopes())
	}
	cols := intgRun(t, aw, "SELECT a.AddressID, sub.City FROM Address a CROSS APPLY (SELECT City FROM Address WHERE AddressID = a.AddressID) sub").AST.(*SelectStatement).Columns
	names := map[string]bool{}
	for _, c := range cols {
		names[strings.ToUpper(columnOutputName(c))] = true
	}
	if !names["CITY"] {
		t.Errorf("apply col accessible: %v", names)
	}
	intgErr(t, aw, "SELECT a.AddressID FROM Address a CROSS APPLY (SELECT NonExistentCol FROM Address WHERE AddressID = a.AddressID) sub", "")
}

func TestMSSQLFeat_AdvancedTypes(t *testing.T) {
	advCSV := `table_name,column_name,data_type
T,geo_col,geography
T,uid_col,uniqueidentifier
T,bin_col,varbinary
T,img_col,image
T,xml_col,xml
T,str_col,nvarchar
T,int_col,int
`
	reg := mkReg(t, advCSV)
	ok := func(sql string) {
		if _, err := NewBinder(reg).Bind(mustParse(t, sql), nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
	bad := func(sql string) {
		if _, err := NewBinder(reg).Bind(mustParse(t, sql), nil); err == nil {
			t.Errorf("%q 應報型別錯誤", sql)
		}
	}
	ok("SELECT geo_col FROM T WHERE geo_col = geo_col")
	bad("SELECT geo_col FROM T WHERE geo_col = str_col")
	bad("SELECT geo_col FROM T WHERE geo_col = int_col")
	ok("SELECT bin_col FROM T WHERE bin_col = bin_col")
	ok("SELECT bin_col FROM T WHERE bin_col = img_col")
	bad("SELECT bin_col FROM T WHERE bin_col = str_col")
	ok("SELECT xml_col FROM T WHERE xml_col = xml_col")
	bad("SELECT xml_col FROM T WHERE xml_col = str_col")
	ok("SELECT uid_col FROM T WHERE uid_col = uid_col")
	ok("SELECT uid_col FROM T WHERE uid_col = str_col")
	bad("SELECT uid_col FROM T WHERE uid_col = int_col")
}

func TestMSSQLFeat_TypeInferenceFunctions(t *testing.T) {
	aw := loadAdventureWorks(t)
	cty := func(sql string) string {
		return colType(intgRun(t, aw, sql).AST.(*SelectStatement).Columns[0])
	}
	if cty("SELECT NEWID() FROM Address") != "UNIQUEIDENTIFIER" {
		t.Error("NEWID -> UNIQUEIDENTIFIER")
	}
	if _, err := NewRunner(aw).Run("SELECT rowguid FROM Address WHERE rowguid = NEWID()", nil); err != nil {
		t.Errorf("NEWID comparable: %v", err)
	}
	if cty("SELECT JSON_VALUE(Name, '$.key') FROM ProductModel") != "NVARCHAR" {
		t.Error("JSON_VALUE -> NVARCHAR")
	}
	if cty("SELECT ISJSON(Name) FROM ProductModel") != "BIT" {
		t.Error("ISJSON -> BIT")
	}
	if cty("SELECT JSON_QUERY(Name, '$.key') FROM ProductModel") != "NVARCHAR" {
		t.Error("JSON_QUERY -> NVARCHAR")
	}
	if cty("SELECT JSON_MODIFY(Name, '$.key', 'val') FROM ProductModel") != "NVARCHAR" {
		t.Error("JSON_MODIFY -> NVARCHAR")
	}

	for _, sql := range []string{
		"SELECT CatalogDescription FROM ProductModel",
		"SELECT ThumbNailPhoto FROM Product",
	} {
		if _, err := NewRunner(aw).Run(sql, nil); err != nil {
			t.Errorf("%q: %v", sql, err)
		}
	}
	intgErr(t, aw, "SELECT AddressID FROM Address WHERE SpatialLocation = AddressLine1", "")
}
