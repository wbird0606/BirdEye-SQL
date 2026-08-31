package main

import (
	"bytes"
	"encoding/json"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	bird "github.com/1150513/birdeye-go"
)

// 對照 birdeye_1150831/tests/test_web_api_suite.py

func testServer(t *testing.T) http.Handler {
	t.Helper()
	b, err := os.ReadFile("../../data/output.csv")
	if err != nil {
		t.Skipf("缺少 data/output.csv: %v", err)
	}
	reg := bird.NewMetadataRegistry()
	if err := reg.LoadFromCSV(string(b)); err != nil {
		t.Fatal(err)
	}
	return newServer(reg).routes()
}

func postJSON(t *testing.T, h http.Handler, path, body string) (int, map[string]any) {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, path, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	var m map[string]any
	json.Unmarshal(w.Body.Bytes(), &m)
	return w.Code, m
}

func result(m map[string]any) map[string]any {
	r, _ := m["result"].(map[string]any)
	return r
}

func TestWeb_ParseSuccess(t *testing.T) {
	h := testServer(t)
	code, m := postJSON(t, h, "/api/parse", `{"sql":"SELECT AddressID, City FROM Address"}`)
	if code != 200 || m["status"] != "success" {
		t.Fatalf("code=%d m=%v", code, m)
	}
	r := result(m)
	if !strings.Contains(r["tree"].(string), "SELECT_STATEMENT") ||
		!strings.Contains(r["mermaid"].(string), "flowchart TD") {
		t.Errorf("result: %v", r)
	}
}

func TestWeb_ParseWithNamedParams(t *testing.T) {
	h := testServer(t)
	code, m := postJSON(t, h, "/api/parse",
		`{"sql":"SELECT AddressID FROM Address WHERE AddressID = @customerId","params":{"customerId":123}}`)
	if code != 200 || m["status"] != "success" {
		t.Fatalf("code=%d m=%v", code, m)
	}
}

func TestWeb_ParseStructuralParamOrderBy(t *testing.T) {
	h := testServer(t)
	code, m := postJSON(t, h, "/api/parse",
		`{"sql":"SELECT ProductID, Name, ListPrice FROM Product ORDER BY @sortCol","params":{"sortCol":"ProductID"}}`)
	if code != 200 || m["status"] != "success" || !strings.Contains(result(m)["json"].(string), "ProductID") {
		t.Fatalf("code=%d m=%v", code, m)
	}
}

func TestWeb_ParseStructuralParamUnsafeBlocked(t *testing.T) {
	h := testServer(t)
	code, m := postJSON(t, h, "/api/parse",
		`{"sql":"SELECT ProductID, Name, ListPrice FROM Product ORDER BY @sortCol","params":{"sortCol":"ProductID;X"}}`)
	if code != 400 || m["status"] != "error" ||
		!strings.Contains(m["error_type"].(string), "Semantic Error") ||
		!strings.Contains(m["message"].(string), "unsafe identifier") {
		t.Fatalf("code=%d m=%v", code, m)
	}
}

func TestWeb_ParseStructuralParamMissingValueBlocked(t *testing.T) {
	h := testServer(t)
	code, m := postJSON(t, h, "/api/parse", `{"sql":"SELECT TOP 1 * FROM @tableName","params":{}}`)
	if code != 400 || m["status"] != "error" ||
		!strings.Contains(m["error_type"].(string), "Semantic Error") ||
		!strings.Contains(m["message"].(string), "requires a runtime parameter value") {
		t.Fatalf("code=%d m=%v", code, m)
	}
}

func TestWeb_ParseQmarkParams(t *testing.T) {
	h := testServer(t)
	code, m := postJSON(t, h, "/api/parse",
		`{"sql":"SELECT ProductID FROM Product WHERE ProductID = ? AND Name = ?","params":[1,"Adjustable Race"]}`)
	if code != 200 || m["status"] != "success" {
		t.Fatalf("code=%d m=%v", code, m)
	}
	if !strings.Contains(result(m)["tree"].(string), "?") {
		t.Errorf("tree 應顯示 ?：%v", result(m)["tree"])
	}
}

func TestWeb_ParseQmarkCountMismatch(t *testing.T) {
	h := testServer(t)
	code, m := postJSON(t, h, "/api/parse",
		`{"sql":"SELECT ProductID FROM Product WHERE ProductID = ? AND Name = ?","params":[1]}`)
	if code != 400 || m["status"] != "error" || !strings.Contains(m["message"].(string), "PARAM_COUNT_MISMATCH") {
		t.Fatalf("code=%d m=%v", code, m)
	}
}

func TestWeb_ParseSemanticError(t *testing.T) {
	h := testServer(t)
	code, m := postJSON(t, h, "/api/parse", `{"sql":"SELECT * FROM GhostTable"}`)
	if code != 400 || m["status"] != "error" ||
		!strings.Contains(m["error_type"].(string), "Semantic Error") ||
		!strings.Contains(m["message"].(string), "Table 'GhostTable' not found") {
		t.Fatalf("code=%d m=%v", code, m)
	}
}

func TestWeb_ParseSyntaxError(t *testing.T) {
	h := testServer(t)
	code, m := postJSON(t, h, "/api/parse", `{"sql":"SELECT FROM Users"}`)
	if code != 400 || m["status"] != "error" || !strings.Contains(m["error_type"].(string), "Syntax Error") {
		t.Fatalf("code=%d m=%v", code, m)
	}
}

func TestWeb_MissingSQL(t *testing.T) {
	h := testServer(t)
	code, m := postJSON(t, h, "/api/parse", `{}`)
	if code != 400 || m["status"] != "error" {
		t.Fatalf("code=%d m=%v", code, m)
	}
}

func TestWeb_Reconstruct(t *testing.T) {
	h := testServer(t)
	// object 形式
	code, m := postJSON(t, h, "/api/reconstruct",
		`{"ast":{"node_type":"SelectStatement","is_star":true,"table":{"node_type":"IdentifierNode","name":"Address","qualifiers":[]}}}`)
	if code != 200 || m["status"] != "success" || m["sql"] != "SELECT * FROM Address" {
		t.Fatalf("object: code=%d m=%v", code, m)
	}
	// string 形式
	code2, m2 := postJSON(t, h, "/api/reconstruct",
		`{"ast":"{\"node_type\":\"SelectStatement\",\"is_star\":true,\"table\":{\"node_type\":\"IdentifierNode\",\"name\":\"Address\",\"qualifiers\":[]}}"}`)
	if code2 != 200 || m2["sql"] != "SELECT * FROM Address" {
		t.Fatalf("string: code=%d m=%v", code2, m2)
	}
	// 錯誤
	code3, m3 := postJSON(t, h, "/api/reconstruct", `{"ast":"{bad json"}`)
	if code3 != 400 || m3["status"] != "error" {
		t.Fatalf("bad: code=%d m=%v", code3, m3)
	}
}

func TestWeb_UploadCSVAndHotSwap(t *testing.T) {
	h := testServer(t)
	var body bytes.Buffer
	mw := multipart.NewWriter(&body)
	fw, _ := mw.CreateFormFile("file", "custom.csv")
	fw.Write([]byte("table_schema,table_name,column_name,data_type\nMy,Foo,Bar,int\n"))
	mw.Close()

	req := httptest.NewRequest(http.MethodPost, "/api/upload_csv", &body)
	req.Header.Set("Content-Type", mw.FormDataContentType())
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	var m map[string]any
	json.Unmarshal(w.Body.Bytes(), &m)
	if w.Code != 200 || m["status"] != "success" {
		t.Fatalf("upload: code=%d m=%v", w.Code, m)
	}

	// 上傳後應可查新 schema
	code, pm := postJSON(t, h, "/api/parse", `{"sql":"SELECT Bar FROM My.Foo"}`)
	if code != 200 || pm["status"] != "success" {
		t.Fatalf("post-upload parse: code=%d m=%v", code, pm)
	}
	// 非 .csv 應拒絕
	var b2 bytes.Buffer
	mw2 := multipart.NewWriter(&b2)
	fw2, _ := mw2.CreateFormFile("file", "x.txt")
	fw2.Write([]byte("x"))
	mw2.Close()
	req2 := httptest.NewRequest(http.MethodPost, "/api/upload_csv", &b2)
	req2.Header.Set("Content-Type", mw2.FormDataContentType())
	w2 := httptest.NewRecorder()
	h.ServeHTTP(w2, req2)
	if w2.Code != 400 {
		t.Errorf("non-csv should 400, got %d", w2.Code)
	}
}

// 對照 test_intent_api.py / test_intent_zta_flow.py / test_denied_intent.py
// （ZTA proxy 整合部分為 skipif，此處只測 /api/intent 本身）。
func TestWeb_IntentAPI(t *testing.T) {
	h := testServer(t)

	code, m := postJSON(t, h, "/api/intent",
		`{"sql":"SELECT AddressID, City FROM SalesLT.Address WHERE City = 'Seattle'"}`)
	if code != 200 || m["status"] != "success" {
		t.Fatalf("code=%d m=%v", code, m)
	}
	intents, _ := m["intents"].([]any)
	if len(intents) == 0 {
		t.Fatalf("intents 空")
	}
	var hasAddr, hasRead bool
	for _, ii := range intents {
		x := ii.(map[string]any)
		if x["table"] == "Address" {
			hasAddr = true
		}
		if x["intent"] == "READ" {
			hasRead = true
		}
	}
	if !hasAddr || !hasRead {
		t.Errorf("Address/READ 缺：%v", intents)
	}
	if _, ok := m["reconstructed_sql"].(string); !ok {
		t.Errorf("缺 reconstructed_sql")
	}

	// missing sql → 400
	if code, _ := postJSON(t, h, "/api/intent", `{}`); code != 400 {
		t.Errorf("missing sql: %d", code)
	}

	// 禁止欄位仍會出現在意圖中（權限判斷由 proxy 做）
	code2, m2 := postJSON(t, h, "/api/intent",
		`{"sql":"SELECT CustomerID, EmailAddress, Phone FROM SalesLT.Customer WHERE CustomerID = 1"}`)
	if code2 != 200 {
		t.Fatalf("denied-sql code=%d", code2)
	}
	cols := map[string]bool{}
	for _, ii := range m2["intents"].([]any) {
		if c, ok := ii.(map[string]any)["column"].(string); ok {
			cols[c] = true
		}
	}
	if !cols["EmailAddress"] && !cols["Phone"] {
		t.Errorf("EmailAddress/Phone 應在意圖中：%v", cols)
	}
}

func TestWeb_Health(t *testing.T) {
	h := testServer(t)
	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != 200 || !strings.Contains(w.Body.String(), `"ok"`) {
		t.Errorf("health: %d %s", w.Code, w.Body.String())
	}
}

func TestWeb_Index(t *testing.T) {
	h := testServer(t)
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	if w.Code != 200 || !strings.Contains(w.Body.String(), "BirdEye-SQL Visualizer") {
		t.Errorf("index: %d", w.Code)
	}
}
