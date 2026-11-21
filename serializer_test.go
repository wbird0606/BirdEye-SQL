package birdeye

import (
	"encoding/json"
	"strings"
	"testing"
)

// 對照 python-final:tests/test_serializer_suite.py

func serDict(t *testing.T, sql string) map[string]any {
	t.Helper()
	m := map[string]any{}
	if err := json.Unmarshal([]byte(NewSerializer().ToJSON(mustParse(t, sql))), &m); err != nil {
		t.Fatalf("serialize %q: %v", sql, err)
	}
	return m
}

func idx(v any, i int) any    { return v.([]any)[i] }
func key(v any, k string) any { return v.(map[string]any)[k] }

func TestSerializerSuite(t *testing.T) {
	t.Run("basic_select", func(t *testing.T) {
		d := serDict(t, "SELECT UserID FROM Users")
		if d["node_type"] != "SelectStatement" {
			t.Fatal(d["node_type"])
		}
		if strings.ToUpper(key(d["table"], "name").(string)) != "USERS" {
			t.Fatal(d["table"])
		}
		if len(d["columns"].([]any)) != 1 {
			t.Fatal(d["columns"])
		}
		if strings.ToUpper(key(idx(d["columns"], 0), "name").(string)) != "USERID" {
			t.Fatal(d["columns"])
		}
	})

	t.Run("case_when", func(t *testing.T) {
		d := serDict(t, "SELECT CASE WHEN A=1 THEN 'Y' ELSE 'N' END FROM T")
		c := idx(d["columns"], 0)
		if key(c, "node_type") != "CaseExpressionNode" {
			t.Fatal(c)
		}
		if len(key(c, "branches").([]any)) != 1 {
			t.Fatal(c)
		}
		if key(key(idx(key(c, "branches"), 0), "when"), "op") != "=" {
			t.Fatal(c)
		}
		if key(key(c, "else"), "value") != "N" {
			t.Fatal(c)
		}
	})

	t.Run("null_handling", func(t *testing.T) {
		d := serDict(t, "SELECT 1")
		if d["where"] != nil || d["table"] != nil {
			t.Fatalf("where=%v table=%v", d["where"], d["table"])
		}
	})

	t.Run("function_call", func(t *testing.T) {
		d := serDict(t, "SELECT LEN(UserName) FROM Users")
		f := idx(d["columns"], 0)
		if key(f, "node_type") != "FunctionCallNode" || strings.ToUpper(key(f, "name").(string)) != "LEN" {
			t.Fatal(f)
		}
		if strings.ToUpper(key(idx(key(f, "args"), 0), "name").(string)) != "USERNAME" {
			t.Fatal(f)
		}
	})

	t.Run("cte", func(t *testing.T) {
		d := serDict(t, "WITH CTE1 AS (SELECT 1 AS A) SELECT A FROM CTE1")
		if len(d["ctes"].([]any)) != 1 {
			t.Fatal(d["ctes"])
		}
		if key(idx(d["ctes"], 0), "name") != "CTE1" {
			t.Fatal(d["ctes"])
		}
		if key(key(idx(d["ctes"], 0), "query"), "node_type") != "SelectStatement" {
			t.Fatal(d["ctes"])
		}
	})

	t.Run("union", func(t *testing.T) {
		d := serDict(t, "SELECT 1 UNION SELECT 2")
		if d["node_type"] != "UnionStatement" || d["op"] != "UNION" {
			t.Fatal(d)
		}
		if key(d["left"], "node_type") != "SelectStatement" || key(d["right"], "node_type") != "SelectStatement" {
			t.Fatal(d)
		}
	})

	t.Run("between_cast", func(t *testing.T) {
		d := serDict(t, "SELECT CAST(Price AS INT) FROM T WHERE Price BETWEEN 1 AND 10")
		c := idx(d["columns"], 0)
		if key(c, "node_type") != "CastExpressionNode" || key(c, "target") != "INT" {
			t.Fatal(c)
		}
		w := d["where"]
		if key(w, "node_type") != "BetweenExpressionNode" {
			t.Fatal(w)
		}
		if key(key(w, "low"), "value") != "1" || key(key(w, "high"), "value") != "10" {
			t.Fatal(w)
		}
	})

	t.Run("declare", func(t *testing.T) {
		d := serDict(t, "DECLARE @counter INT")
		if d["node_type"] != "DeclareStatement" || d["var_name"] != "@counter" || d["var_type"] != "INT" || d["default_value"] != nil {
			t.Fatal(d)
		}
	})

	t.Run("declare_with_default", func(t *testing.T) {
		d := serDict(t, "DECLARE @x INT = 0")
		dv := d["default_value"]
		if dv == nil || key(dv, "node_type") != "LiteralNode" || key(dv, "value") != "0" {
			t.Fatal(dv)
		}
	})

	t.Run("select_into", func(t *testing.T) {
		d := serDict(t, "SELECT A INTO #Temp FROM T")
		if d["into_table"] == nil || key(d["into_table"], "name") != "#Temp" {
			t.Fatal(d["into_table"])
		}
	})

	t.Run("select_without_into", func(t *testing.T) {
		if serDict(t, "SELECT A FROM T")["into_table"] != nil {
			t.Fatal("expected null into_table")
		}
	})

	t.Run("apply", func(t *testing.T) {
		d := serDict(t, "SELECT A FROM T CROSS APPLY (SELECT B FROM T2) sub")
		a := idx(d["applies"], 0)
		if key(a, "node_type") != "ApplyNode" || key(a, "apply_type") != "CROSS" || key(a, "alias") != "sub" {
			t.Fatal(a)
		}
		if key(key(a, "subquery"), "node_type") != "SelectStatement" {
			t.Fatal(a)
		}
	})

	t.Run("outer_apply", func(t *testing.T) {
		d := serDict(t, "SELECT A FROM T OUTER APPLY (SELECT B FROM T2) sub")
		if key(idx(d["applies"], 0), "apply_type") != "OUTER" {
			t.Fatal(d["applies"])
		}
	})

	t.Run("derived_table", func(t *testing.T) {
		d := serDict(t, "SELECT sub.City FROM (SELECT City FROM T) sub")
		if key(d["table"], "node_type") != "SelectStatement" || d["alias"] != "sub" {
			t.Fatal(d)
		}
	})

	t.Run("not_in", func(t *testing.T) {
		if key(serDict(t, "SELECT A FROM T WHERE A NOT IN (1, 2)")["where"], "op") != "NOT IN" {
			t.Fatal("expected NOT IN")
		}
	})

	t.Run("offset_fetch", func(t *testing.T) {
		d := serDict(t, "SELECT A FROM T ORDER BY A OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY")
		if d["offset_count"].(float64) != 10 || d["fetch_count"].(float64) != 5 {
			t.Fatal(d)
		}
	})

	t.Run("top_percent", func(t *testing.T) {
		d := serDict(t, "SELECT TOP 10 PERCENT A FROM T")
		if d["top"].(float64) != 10 || d["top_percent"] != true {
			t.Fatal(d)
		}
	})

	t.Run("top_without_percent", func(t *testing.T) {
		d := serDict(t, "SELECT TOP 5 A FROM T")
		if d["top"].(float64) != 5 || d["top_percent"] != false {
			t.Fatal(d)
		}
	})

	t.Run("insert_select", func(t *testing.T) {
		d := serDict(t, "INSERT INTO Address (AddressID) SELECT AddressID FROM Address")
		if d["source"] == nil || key(d["source"], "node_type") != "SelectStatement" || d["values"] != nil {
			t.Fatal(d)
		}
	})

	t.Run("multirow_values", func(t *testing.T) {
		d := serDict(t, "INSERT INTO Address (AddressID, City) VALUES (1, 'A'), (2, 'B')")
		if len(d["value_rows"].([]any)) != 2 {
			t.Fatal(d["value_rows"])
		}
	})

	t.Run("distinct", func(t *testing.T) {
		if serDict(t, "SELECT DISTINCT City FROM T")["is_distinct"] != true {
			t.Fatal("expected is_distinct true")
		}
		if serDict(t, "SELECT City FROM T")["is_distinct"] != false {
			t.Fatal("expected is_distinct false")
		}
	})

	t.Run("null_literal", func(t *testing.T) {
		c := idx(serDict(t, "SELECT NULL")["columns"], 0)
		if key(c, "node_type") != "LiteralNode" || key(c, "value") != "NULL" {
			t.Fatal(c)
		}
	})

	t.Run("modulo_bitwise", func(t *testing.T) {
		if key(idx(serDict(t, "SELECT AddressID % 2 FROM T")["columns"], 0), "op") != "%" {
			t.Fatal("expected %")
		}
		if key(idx(serDict(t, "SELECT AddressID & 1 FROM T")["columns"], 0), "op") != "&" {
			t.Fatal("expected &")
		}
	})

	t.Run("concat_cast_setops", func(t *testing.T) {
		if key(idx(serDict(t, "SELECT CONCAT(City, ', ') FROM T")["columns"], 0), "name") != "CONCAT" {
			t.Fatal("CONCAT")
		}
		if key(idx(serDict(t, "SELECT CAST(A AS VARCHAR(10)) FROM T")["columns"], 0), "target") != "VARCHAR" {
			t.Fatal("VARCHAR")
		}
		if serDict(t, "SELECT A FROM T INTERSECT SELECT A FROM T")["op"] != "INTERSECT" {
			t.Fatal("INTERSECT")
		}
		if serDict(t, "SELECT A FROM T EXCEPT SELECT A FROM T")["op"] != "EXCEPT" {
			t.Fatal("EXCEPT")
		}
	})
}
