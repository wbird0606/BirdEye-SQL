package birdeye

import (
	"encoding/csv"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

// 對照 birdeye_1150831/tests/test_metadata_roundtrip_suite.py
// —— 由 metadata（testdata/output.csv）產生代表性查詢，驗證 SQL → JSON → SQL
//    往返後仍可再被解析成 AST/JSON。

func quoteIdent(name string) string {
	ok := name != "" && !strings.Contains(name, " ") && !strings.Contains(name, ".")
	for _, r := range name {
		if !(r == '_' || (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z') || (r >= '0' && r <= '9')) {
			ok = false
			break
		}
	}
	if ok {
		return name
	}
	return "[" + name + "]"
}

func loadMetaTables(t *testing.T) (cols map[string][]string, types map[string]map[string]string) {
	t.Helper()
	data, err := os.ReadFile(filepath.Join("testdata", "output.csv"))
	if err != nil {
		t.Skipf("缺少 testdata/output.csv: %v", err)
	}
	r := csv.NewReader(strings.NewReader(strings.TrimPrefix(string(data), "\ufeff")))
	r.FieldsPerRecord = -1
	rows, err := r.ReadAll()
	if err != nil {
		t.Fatalf("csv: %v", err)
	}
	cols = map[string][]string{}
	types = map[string]map[string]string{}
	for _, row := range rows {
		if len(row) < 4 || row[0] == "table_schema" {
			continue
		}
		schema, table, col, dt := row[0], row[1], row[2], row[3]
		key := schema + "." + table
		cols[key] = append(cols[key], col)
		if types[key] == nil {
			types[key] = map[string]string{}
		}
		types[key][col] = strings.ToLower(dt)
	}
	return cols, types
}

func splitTableKey(k string) (string, string) {
	i := strings.IndexByte(k, '.')
	return k[:i], k[i+1:]
}

// metaRoundtrip：SQL → AST → JSON → SQL，並再解析一次確認可用。
func metaRoundtrip(t *testing.T, sql string) string {
	t.Helper()
	n := mustParse(t, sql)
	js := NewSerializer().ToJSON(n)
	out, err := NewReconstructor().Reconstruct(js)
	if err != nil {
		t.Fatalf("reconstruct %q: %v", sql, err)
	}
	n2 := mustParse(t, out) // 重建後的 SQL 仍要能被解析
	_ = NewSerializer().ToJSON(n2)
	return out
}

func chosenColumns(all []string) []string {
	if len(all) >= 2 {
		return all[:2]
	}
	return all[:1]
}

func TestMetadataRoundtrip_Representative(t *testing.T) {
	tables, _ := loadMetaTables(t)
	samples := [][2]string{
		{"SalesLT", "Address"}, {"SalesLT", "Customer"}, {"SalesLT", "Product"},
		{"SalesLT", "SalesOrderHeader"}, {"SalesLT", "SalesOrderDetail"},
		{"SalesLT", "ProductCategory"}, {"SalesLT", "ProductModel"}, {"dbo", "BuildVersion"},
	}
	for _, s := range samples {
		key := s[0] + "." + s[1]
		columns := tables[key]
		if len(columns) == 0 {
			t.Fatalf("metadata 缺少表 %s", key)
		}
		chosen := chosenColumns(columns)
		var sel []string
		for _, c := range chosen {
			sel = append(sel, quoteIdent(c))
		}
		sql := "SELECT " + strings.Join(sel, ", ") + " FROM " + s[0] + "." + quoteIdent(s[1])
		got := metaRoundtrip(t, sql)
		if !strings.Contains(got, "SELECT") || !strings.Contains(got, "FROM") || !strings.Contains(got, s[1]) {
			t.Errorf("%q -> %q", sql, got)
		}
		for _, c := range chosen {
			if !strings.Contains(got, c) {
				t.Errorf("%q -> %q missing column %q", sql, got, c)
			}
		}
	}
}

func TestMetadataRoundtrip_AllTables(t *testing.T) {
	tables, _ := loadMetaTables(t)
	keys := make([]string, 0, len(tables))
	for k := range tables {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	for _, key := range keys {
		schema, table := splitTableKey(key)
		columns := tables[key]
		if len(columns) == 0 {
			t.Fatalf("metadata 缺少欄位：%s", key)
		}
		chosen := chosenColumns(columns)

		// 基本 roundtrip
		var sel []string
		for _, c := range chosen {
			sel = append(sel, quoteIdent(c))
		}
		basic := "SELECT " + strings.Join(sel, ", ") + " FROM " + schema + "." + quoteIdent(table)
		got := metaRoundtrip(t, basic)
		if !strings.Contains(got, "SELECT") || !strings.Contains(got, "FROM") || !strings.Contains(got, table) {
			t.Errorf("%q -> %q", basic, got)
		}
		for _, c := range chosen {
			if !strings.Contains(got, c) {
				t.Errorf("%q -> %q missing %q", basic, got, c)
			}
		}

		// alias + TOP + ORDER BY（僅限至少兩欄）
		if len(columns) >= 2 {
			var aliasSel []string
			for _, c := range chosen {
				aliasSel = append(aliasSel, "t."+quoteIdent(c))
			}
			aliased := "SELECT TOP 3 " + strings.Join(aliasSel, ", ") +
				" FROM " + schema + "." + quoteIdent(table) + " AS t" +
				" ORDER BY t." + quoteIdent(chosen[0])
			got := metaRoundtrip(t, aliased)
			if !strings.Contains(got, "TOP") || !strings.Contains(got, "ORDER BY") {
				t.Errorf("%q -> %q", aliased, got)
			}
			if !strings.Contains(got, "AS t") && !strings.Contains(got, "AS T") {
				t.Errorf("%q -> %q missing alias", aliased, got)
			}
		}
	}
}

func TestMetadataRoundtrip_ComplexQueries(t *testing.T) {
	cases := []string{
		"SELECT c.CustomerID, c.FirstName, c.LastName, a.City, a.PostalCode FROM SalesLT.Customer AS c JOIN SalesLT.CustomerAddress AS ca ON c.CustomerID = ca.CustomerID JOIN SalesLT.Address AS a ON ca.AddressID = a.AddressID",
		"SELECT c.CustomerID, ca.AddressID, a.City FROM SalesLT.Customer AS c JOIN SalesLT.CustomerAddress AS ca ON c.CustomerID = ca.CustomerID JOIN SalesLT.Address AS a ON ca.AddressID = a.AddressID ORDER BY c.CustomerID",
		"SELECT soh.CustomerID, COUNT(*) AS OrderCount FROM SalesLT.SalesOrderHeader AS soh JOIN SalesLT.SalesOrderDetail AS sod ON soh.SalesOrderID = sod.SalesOrderID GROUP BY soh.CustomerID HAVING COUNT(*) > 0 ORDER BY OrderCount DESC",
		"SELECT soh.SalesOrderID, soh.OrderDate, ROW_NUMBER() OVER (PARTITION BY soh.CustomerID ORDER BY soh.OrderDate) AS rn FROM SalesLT.SalesOrderHeader AS soh",
		"SELECT p.ProductID, p.Name, pc.Name AS CategoryName FROM SalesLT.Product AS p JOIN SalesLT.ProductCategory AS pc ON p.ProductCategoryID = pc.ProductCategoryID ORDER BY p.ProductID",
		"SELECT pmd.ProductID, pmd.Name, pmd.Description FROM SalesLT.vProductAndDescription AS pmd WHERE pmd.ProductID IN (SELECT ProductID FROM SalesLT.Product)",
		"SELECT p.ProductID, p.Name, ROW_NUMBER() OVER (PARTITION BY p.ProductCategoryID ORDER BY p.SellStartDate) AS rn FROM SalesLT.Product AS p",
		"SELECT p.ProductID, p.Name FROM SalesLT.Product AS p WHERE p.ProductID IN (SELECT ProductID FROM SalesLT.SalesOrderDetail)",
		"SELECT e.ErrorLogID, e.ErrorTime FROM dbo.ErrorLog AS e WHERE e.ErrorLogID IN (SELECT ErrorLogID FROM dbo.ErrorLog)",
		"SELECT soh.SalesOrderID, soh.CustomerID, ROW_NUMBER() OVER (PARTITION BY soh.CustomerID ORDER BY soh.OrderDate) AS rn FROM SalesLT.SalesOrderHeader AS soh",
	}
	for _, sql := range cases {
		got := metaRoundtrip(t, sql)
		if !strings.Contains(got, "SELECT") || !strings.Contains(got, "FROM") {
			t.Errorf("%q -> %q", sql, got)
		}
		for _, kw := range []string{"JOIN", "GROUP BY", "HAVING", "WHERE", "OVER"} {
			if strings.Contains(sql, kw) && !strings.Contains(got, kw) {
				t.Errorf("%q -> %q missing %q", sql, got, kw)
			}
		}
	}
}

func TestMetadataRoundtrip_DateWindowQueries(t *testing.T) {
	tables, types := loadMetaTables(t)
	dateTypes := map[string]bool{"date": true, "datetime": true, "smalldatetime": true, "timestamp": true}
	keys := make([]string, 0, len(tables))
	for k := range tables {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	for _, key := range keys {
		columns := tables[key]
		if len(columns) < 2 {
			continue
		}
		var dateCol string
		for _, c := range columns { // 依 CSV 順序取第一個日期欄
			if dateTypes[types[key][c]] {
				dateCol = c
				break
			}
		}
		if dateCol == "" {
			continue
		}
		schema, table := splitTableKey(key)
		wc := columns[:2]
		sql := "SELECT t." + quoteIdent(wc[0]) + ", t." + quoteIdent(wc[1]) +
			", ROW_NUMBER() OVER (PARTITION BY t." + quoteIdent(wc[0]) +
			" ORDER BY t." + quoteIdent(dateCol) + ") AS rn" +
			" FROM " + schema + "." + quoteIdent(table) + " AS t"
		got := metaRoundtrip(t, sql)
		for _, w := range []string{"ROW_NUMBER", "OVER", "PARTITION BY", "ORDER BY", dateCol} {
			if !strings.Contains(got, w) {
				t.Errorf("%q -> %q missing %q", sql, got, w)
			}
		}
	}
}

func TestMetadataRoundtrip_JoinCandidates(t *testing.T) {
	tables, _ := loadMetaTables(t)
	colToTables := map[string][]string{}
	keys := make([]string, 0, len(tables))
	for k := range tables {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		for _, c := range tables[k] {
			colToTables[c] = append(colToTables[c], k)
		}
	}
	preferred := []string{
		"CustomerID", "AddressID", "ProductID", "SalesOrderID", "ProductCategoryID",
		"ProductModelID", "ProductDescriptionID", "Description", "Culture", "Name",
	}
	for _, col := range preferred {
		tw := colToTables[col]
		sort.Strings(tw)
		tw = dedup(tw)
		if len(tw) < 2 {
			continue
		}
		for i := 0; i < len(tw); i++ {
			for j := i + 1; j < len(tw); j++ {
				lk, rk := tw[i], tw[j]
				ls, lt := splitTableKey(lk)
				rs, rt := splitTableKey(rk)
				lcols := tables[lk]
				if len(lcols) > 2 {
					lcols = lcols[:2]
				}
				var sel []string
				if !contains(lcols, col) {
					sel = append(sel, "l."+quoteIdent(col))
				}
				for _, c := range lcols {
					sel = append(sel, "l."+quoteIdent(c))
				}
				if len(sel) > 4 {
					sel = sel[:4]
				}
				sql := "SELECT " + strings.Join(sel, ", ") +
					" FROM " + ls + "." + quoteIdent(lt) + " AS l" +
					" JOIN " + rs + "." + quoteIdent(rt) + " AS r" +
					" ON l." + quoteIdent(col) + " = r." + quoteIdent(col)
				got := metaRoundtrip(t, sql)
				for _, w := range []string{"JOIN", col, "ON"} {
					if !strings.Contains(got, w) {
						t.Errorf("%q -> %q missing %q", sql, got, w)
					}
				}
			}
		}
	}
}

func dedup(s []string) []string {
	out := s[:0]
	var prev string
	for i, v := range s {
		if i == 0 || v != prev {
			out = append(out, v)
		}
		prev = v
	}
	return out
}

func contains(s []string, v string) bool {
	for _, x := range s {
		if x == v {
			return true
		}
	}
	return false
}
