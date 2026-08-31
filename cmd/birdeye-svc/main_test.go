package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	bird "github.com/1150513/birdeye-go"
)

// birdeye-svc 對照 Python birdeye-svc/app.py 的端點契約。

func svc(fetch bird.SchemaFetcher) http.Handler {
	return newService(bird.NewAnalyser(fetch, time.Minute))
}

func fakeFetch(cols ...bird.SchemaColumn) bird.SchemaFetcher {
	return func(_ context.Context, _ int, _, _ string) ([]bird.SchemaColumn, error) { return cols, nil }
}

func post(t *testing.T, h http.Handler, path, body string) (int, map[string]any) {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, path, strings.NewReader(body))
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	var m map[string]any
	json.Unmarshal(w.Body.Bytes(), &m)
	return w.Code, m
}

func TestSvc_Intents(t *testing.T) {
	h := svc(fakeFetch(
		bird.SchemaColumn{ColumnName: "AddressID", DataType: "int"},
		bird.SchemaColumn{ColumnName: "City", DataType: "nvarchar"},
	))
	code, m := post(t, h, "/intents",
		`{"sql":"SELECT AddressID FROM SalesLT.Address WHERE City = 'Seattle'","db_id":2}`)
	if code != 200 {
		t.Fatalf("code=%d m=%v", code, m)
	}
	if _, ok := m["ast_json"].(string); !ok {
		t.Errorf("缺 ast_json：%v", m)
	}
	intents, _ := m["intents"].([]any)
	if len(intents) == 0 {
		t.Fatalf("intents 空：%v", m)
	}
	seen := map[string]string{}
	for _, ii := range intents {
		x := ii.(map[string]any)
		col, _ := x["column"].(string)
		seen[x["table"].(string)+"."+col] = x["intent"].(string)
	}
	if seen["Address.AddressID"] != "READ" || seen["Address.City"] != "FILTER" {
		t.Errorf("意圖：%v", seen)
	}
}

func TestSvc_IntentsStarExpansion(t *testing.T) {
	h := svc(fakeFetch(
		bird.SchemaColumn{ColumnName: "AddressID", DataType: "int"},
		bird.SchemaColumn{ColumnName: "City", DataType: "nvarchar"},
	))
	code, m := post(t, h, "/intents", `{"sql":"SELECT COUNT(*) FROM SalesLT.Address","db_id":1}`)
	if code != 200 {
		t.Fatalf("code=%d", code)
	}
	cols := map[string]bool{}
	for _, ii := range m["intents"].([]any) {
		if c, ok := ii.(map[string]any)["column"].(string); ok {
			cols[c] = true
		}
	}
	if !cols["AddressID"] || !cols["City"] {
		t.Errorf("COUNT(*) 應展開全欄：%v", cols)
	}
}

func TestSvc_IntentsErrors(t *testing.T) {
	h := svc(fakeFetch())
	if code, _ := post(t, h, "/intents", `{}`); code != 400 {
		t.Errorf("missing sql: %d", code)
	}
	if code, m := post(t, h, "/intents", `{"sql":"SELECT * FROM"}`); code != 400 || !strings.Contains(m["error"].(string), "parse error") {
		t.Errorf("bad sql: %d %v", code, m)
	}
}

func TestSvc_Rewrite(t *testing.T) {
	h := svc(fakeFetch(
		bird.SchemaColumn{ColumnName: "AddressID", DataType: "int"},
		bird.SchemaColumn{ColumnName: "City", DataType: "nvarchar"},
	))
	_, im := post(t, h, "/intents", `{"sql":"SELECT AddressID FROM SalesLT.Address","db_id":1}`)
	astJSON := im["ast_json"].(string)

	// 無 filter
	astEsc, _ := json.Marshal(astJSON)
	code, m := post(t, h, "/rewrite", `{"ast_json":`+string(astEsc)+`,"row_filters":[]}`)
	if code != 200 || !strings.Contains(m["sql"].(string), "SELECT AddressID") {
		t.Fatalf("no-filter: %d %v", code, m)
	}
	// LITERAL filter
	code2, m2 := post(t, h, "/rewrite", `{"ast_json":`+string(astEsc)+`,"row_filters":[{"Schema":"SalesLT","Table":"Address","Column":"City","Operator":"=","ValueType":"LITERAL","Value":"Seattle"}]}`)
	if code2 != 200 || !strings.Contains(m2["sql"].(string), "City = 'Seattle'") {
		t.Fatalf("literal filter: %d %v", code2, m2)
	}
	// 缺 ast_json
	if code3, _ := post(t, h, "/rewrite", `{}`); code3 != 400 {
		t.Errorf("missing ast_json: %d", code3)
	}
}

func TestSvc_Health(t *testing.T) {
	h := svc(fakeFetch())
	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != 200 || !strings.Contains(w.Body.String(), `"ok"`) {
		t.Errorf("health: %d %s", w.Code, w.Body.String())
	}
}
