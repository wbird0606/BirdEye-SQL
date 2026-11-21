package birdeye

import (
	"context"
	"encoding/json"
	"reflect"
	"sort"
	"strings"
	"testing"
	"time"
)

// rewrite_dml_test.go：INSERT／MERGE／UPDATE／DELETE 內部查詢之列過濾，以及「注入後 AST 結構不亂」之保護。

func astOf(t *testing.T, sql string) (string, *Analyser) {
	t.Helper()
	a := NewAnalyser(tableFetch, time.Minute)
	res, err := a.GetIntents(context.Background(), sql, 2, nil)
	if err != nil {
		t.Fatalf("GetIntents(%q): %v", sql, err)
	}
	return res.ASTJSON, a
}

// ── DML 行為 ─────────────────────────────────────────────────────────────────

func TestRewrite_InsertSelectFiltersSourceOnly(t *testing.T) {
	out := rewriteWith(t,
		"INSERT INTO "+tC+" (ProductCategoryID, Name) SELECT SalesOrderID, 'x' FROM "+tD, fD)
	if !strings.HasPrefix(out, "INSERT INTO "+tC+" (ProductCategoryID, Name) SELECT") {
		t.Errorf("INSERT 本體（目標表／欄位）不得被改動：%s", out)
	}
	if !strings.Contains(out, "OrderQty >= 5") {
		t.Errorf("來源 SELECT 應被過濾：%s", out)
	}
	if strings.Count(out, "WHERE") != 1 {
		t.Errorf("INSERT 本身不得出現額外 WHERE：%s", out)
	}
}

func TestRewrite_InsertValuesUnchanged(t *testing.T) {
	sql := "INSERT INTO " + tC + " (ProductCategoryID, Name) VALUES (99, 'x')"
	ast, a := astOf(t, sql)
	plain, _ := a.Rewrite(ast, nil)
	filtered, err := a.Rewrite(ast, []RowFilter{rf("ProductCategory", "ProductCategoryID", "<=", "30")})
	if err != nil || filtered != plain {
		t.Errorf("INSERT … VALUES 不應被列過濾改變（寫入由 GRANT 決定）：\n %s\n %s (err=%v)", plain, filtered, err)
	}
}

func TestRewrite_MergeSourceTableBecomesFilteredDerived(t *testing.T) {
	out := rewriteWith(t,
		"MERGE "+tC+" AS t USING "+tD+" AS s ON t.ProductCategoryID = s.SalesOrderID WHEN MATCHED THEN UPDATE SET Name = 'x'", fD)
	if !strings.Contains(out, "USING (SELECT * FROM "+tD+" WHERE ") || !strings.Contains(out, ") AS s ON") {
		t.Errorf("MERGE 來源資料表應以過濾後衍生資料表取代並保留別名：%s", out)
	}
}

func TestRewrite_MergeSourceWithoutAliasGetsTableNameAlias(t *testing.T) {
	out := rewriteWith(t,
		"MERGE "+tC+" AS t USING "+tD+" ON t.ProductCategoryID = SalesOrderDetail.SalesOrderID WHEN MATCHED THEN UPDATE SET Name = 'x'", fD)
	if !strings.Contains(out, ") AS SalesOrderDetail ON") {
		t.Errorf("無別名來源改衍生資料表後，須以表名作別名，外層引用才不致失效：%s", out)
	}
}

func TestRewrite_MergeSourceSubqueryFiltered(t *testing.T) {
	out := rewriteWith(t,
		"MERGE "+tC+" AS t USING (SELECT SalesOrderID FROM "+tD+") AS s ON t.ProductCategoryID = s.SalesOrderID WHEN MATCHED THEN UPDATE SET Name = 'x'", fD)
	if !strings.Contains(out, "OrderQty >= 5") {
		t.Errorf("MERGE 來源子查詢應被過濾：%s", out)
	}
}

func TestRewrite_MergeTargetWithRowFilterRejected(t *testing.T) {
	ast, a := astOf(t,
		"MERGE "+tC+" AS t USING "+tD+" AS s ON t.ProductCategoryID = s.SalesOrderID WHEN MATCHED THEN UPDATE SET Name = 'x'")
	_, err := a.Rewrite(ast, []RowFilter{rf("ProductCategory", "ProductCategoryID", "<=", "30")})
	if err == nil {
		t.Fatal("MERGE 目標表具列過濾時應 Fail-Closed 拒絕，而非產生語意不完整之改寫")
	}
}

func TestRewrite_UpdateDeleteSubqueriesFiltered(t *testing.T) {
	del := rewriteWith(t, "DELETE FROM "+tC+" WHERE ProductCategoryID IN (SELECT SalesOrderID FROM "+tD+")", fD)
	if !strings.Contains(del, "OrderQty >= 5") {
		t.Errorf("DELETE 之 WHERE 子查詢應被過濾：%s", del)
	}
	upd := rewriteWith(t, "UPDATE "+tC+" SET Name = 'x' WHERE ProductCategoryID IN (SELECT SalesOrderID FROM "+tD+")", fD)
	if !strings.Contains(upd, "OrderQty >= 5") {
		t.Errorf("UPDATE 之 WHERE 子查詢應被過濾：%s", upd)
	}
	both := rewriteWith(t, "DELETE FROM "+tC+" WHERE ProductCategoryID IN (SELECT SalesOrderID FROM "+tD+")",
		fD, rf("ProductCategory", "ProductCategoryID", "<=", "30"))
	if !strings.Contains(both, "OrderQty >= 5") || !strings.Contains(both, "ProductCategoryID <= 30") {
		t.Errorf("目標表與子查詢之過濾應同時存在：%s", both)
	}
}

func TestRewrite_DeleteWhereWithoutColumnStillGetsFilter(t *testing.T) {
	// 只要權限服務取回了列過濾，WHERE 1=1 亦會被 AND（取回與否取決於權限服務，見 ZtaPermissionService）
	out := rewriteWith(t, "DELETE FROM "+tC+" WHERE 1 = 1", rf("ProductCategory", "ProductCategoryID", "<=", "30"))
	if !strings.Contains(out, "WHERE (1 = 1 AND ProductCategory.ProductCategoryID <= 30)") {
		t.Errorf("實得：%s", out)
	}
}

func TestIntents_IfBlockTablesDiscovered(t *testing.T) {
	_, got := rmIntents(t, "IF 1 = 1 BEGIN SELECT SalesOrderID FROM "+tD+" END")
	if !got["SalesOrderDetail.SalesOrderID:READ"] {
		t.Errorf("IF 區塊內之資料表應被探索：%v", got)
	}
}

// ── AST 結構完整性 ───────────────────────────────────────────────────────────

func keysOf(m map[string]any) []string {
	var ks []string
	for k := range m {
		if k == "inferred_type" { // 僅在型別已推導時才出現，注入節點不帶
			continue
		}
		ks = append(ks, k)
	}
	sort.Strings(ks)
	return ks
}

func firstStatement(t *testing.T, sql string) map[string]any {
	t.Helper()
	node, err := NewRunner(nil).ParseOnlyMulti(sql, nil)
	if err != nil {
		t.Fatalf("parse %q: %v", sql, err)
	}
	var m map[string]any
	if err := json.Unmarshal([]byte(NewSerializer().ToJSON(node)), &m); err != nil {
		t.Fatal(err)
	}
	if st := dslice(m, "statements"); len(st) > 0 {
		return node2map(st[0])
	}
	return m
}

func TestAST_InjectedDerivedTableHasSameShapeAsParserOutput(t *testing.T) {
	// 注入器手工組裝之節點，其欄位集合必須與解析器對相同語法實際產生者一致，
	// 否則重建／後續處理可能對「形狀不同之節點」行為不一致。
	// 注入器以「表名.欄位」限定條件欄位，故以語意相同之寫法比對
	parsed := firstStatement(t, "SELECT * FROM "+tD+" WHERE SalesOrderDetail.OrderQty >= 5")
	conds := []any{makeCondition(fD, []aliasEntry{{"SALESLT", "SALESORDERDETAIL", "SalesOrderDetail"}})}
	built := newFilteredDerived(parsed["table"], conds)

	if got, want := keysOf(built), keysOf(parsed); !reflect.DeepEqual(got, want) {
		t.Errorf("衍生資料表節點欄位集合與解析器不一致：\n 注入：%v\n 解析：%v", got, want)
	}
	pw, bw := node2map(parsed["where"]), node2map(built["where"])
	// 條件節點沿用基準版之組裝方式：與解析器輸出相比，僅允許（1）多一個空的 "alias"、
	// （2）少 binder 推導才有之 resolved_table／internal_param_name；其餘不得有未知欄位，且須具備重建器所需欄位。
	assertCompatible := func(name string, injected, parsedNode map[string]any, required ...string) {
		allowedExtra := map[string]bool{"alias": true}
		pk := map[string]bool{}
		for _, k := range keysOf(parsedNode) {
			pk[k] = true
		}
		for _, k := range keysOf(injected) {
			if !pk[k] && !allowedExtra[k] {
				t.Errorf("%s：注入節點含解析器不存在之未知欄位 %q", name, k)
			}
		}
		for _, k := range required {
			if _, ok := injected[k]; !ok {
				t.Errorf("%s：注入節點缺少必要欄位 %q", name, k)
			}
		}
	}
	assertCompatible("條件節點", bw, pw, "node_type", "op", "left", "right")
	assertCompatible("條件左側（識別字）", node2map(bw["left"]), node2map(pw["left"]), "node_type", "name", "qualifiers")
	assertCompatible("條件右側（字面值）", node2map(bw["right"]), node2map(pw["right"]), "node_type", "type", "value")

	// 多出之 "alias": null 不得影響重建結果：以解析器原生節點與注入節點各自重建，須得相同 SQL。
	rc := NewReconstructor()
	if got, want := rc.ReconstructValue(bw), rc.ReconstructValue(pw); got != want {
		t.Errorf("注入之條件節點與解析器原生節點重建結果不同：%s ≠ %s", got, want)
	}
}

func TestAST_InjectDoesNotMutateInputAndIsRepeatable(t *testing.T) {
	// 快取中之原始 AST 不得被改寫污染；同一份 AST 以不同過濾條件重複改寫須可重現。
	sqls := []string{
		"SELECT h.SalesOrderID, d.OrderQty FROM " + tH + " h LEFT JOIN " + tD + " d ON h.SalesOrderID = d.SalesOrderID",
		"DELETE FROM " + tC + " WHERE ProductCategoryID IN (SELECT SalesOrderID FROM " + tD + ")",
		"MERGE " + tC + " AS t USING " + tD + " AS s ON t.ProductCategoryID = s.SalesOrderID WHEN MATCHED THEN UPDATE SET Name = 'x'",
		"INSERT INTO " + tC + " (ProductCategoryID, Name) SELECT SalesOrderID, 'x' FROM " + tD,
	}
	for _, sql := range sqls {
		astJSON, a := astOf(t, sql)
		var m map[string]any
		if err := json.Unmarshal([]byte(astJSON), &m); err != nil {
			t.Fatal(err)
		}
		before, _ := json.Marshal(m)
		inj := NewRowFilterInjector()
		_ = func() (r map[string]any) { defer func() { recover() }(); return inj.Inject(m, []RowFilter{fD, fH}) }()
		after, _ := json.Marshal(m)
		if string(before) != string(after) {
			t.Errorf("Inject 改動了輸入 AST（會污染快取）：%s", sql)
		}
		plain1, _ := a.Rewrite(astJSON, nil)
		r1, e1 := a.Rewrite(astJSON, []RowFilter{fD})
		r2, e2 := a.Rewrite(astJSON, []RowFilter{fD})
		plain2, _ := a.Rewrite(astJSON, nil)
		if plain1 != plain2 || r1 != r2 || (e1 == nil) != (e2 == nil) {
			t.Errorf("同一份 AST 重複改寫結果不一致（隱含狀態污染）：%s", sql)
		}
	}
}

func TestAST_RewrittenSQLRoundTripsToStableAST(t *testing.T) {
	// 改寫後 SQL → 解析 → 序列化 → 重建，必須回到同一個 SQL（fixed point），
	// 代表注入後之結構是引擎自己認得、且可穩定往返的合法 AST。
	cases := []struct {
		sql string
		f   []RowFilter
	}{
		{"SELECT h.SalesOrderID FROM " + tH + " h JOIN " + tD + " d ON h.SalesOrderID = d.SalesOrderID", []RowFilter{fH, fD}},
		{"SELECT h.SalesOrderID, d.OrderQty FROM " + tH + " h LEFT JOIN " + tD + " d ON h.SalesOrderID = d.SalesOrderID", []RowFilter{fD}},
		{"SELECT h.SalesOrderID, d.SalesOrderDetailID FROM " + tH + " h FULL JOIN " + tD + " d ON h.SalesOrderID = d.SalesOrderID", []RowFilter{fH, fD}},
		{"SELECT a.ProductCategoryID FROM " + tC + " a JOIN " + tC + " b ON b.ParentProductCategoryID = a.ProductCategoryID", []RowFilter{rf("ProductCategory", "ProductCategoryID", "<=", "30")}},
		{"INSERT INTO " + tC + " (ProductCategoryID, Name) SELECT SalesOrderID, 'x' FROM " + tD, []RowFilter{fD}},
		{"MERGE " + tC + " AS t USING " + tD + " AS s ON t.ProductCategoryID = s.SalesOrderID WHEN MATCHED THEN UPDATE SET Name = 'x'", []RowFilter{fD}},
		{"DELETE FROM " + tC + " WHERE ProductCategoryID IN (SELECT SalesOrderID FROM " + tD + ")", []RowFilter{fD}},
		{"UPDATE " + tC + " SET Name = 'x' WHERE ProductCategoryID IN (SELECT SalesOrderID FROM " + tD + ")", []RowFilter{fD}},
	}
	for _, c := range cases {
		out1 := rewriteWith(t, c.sql, c.f...)
		node, err := NewRunner(nil).ParseOnlyMulti(out1, nil)
		if err != nil {
			t.Fatalf("改寫結果無法解析：%v\n%s", err, out1)
		}
		out2, err := NewReconstructor().Reconstruct(NewSerializer().ToJSON(node))
		if err != nil || out2 != out1 {
			t.Errorf("改寫結果非 fixed point：\n 1: %s\n 2: %s (err=%v)", out1, out2, err)
		}
	}
}
