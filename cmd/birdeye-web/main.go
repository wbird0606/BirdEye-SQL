// Command birdeye-web 是 birdeye-go 的網頁儀表板，對照 Python 版 web/app.py。
//
//	birdeye-web              # 監聽 :5000
//	birdeye-web -addr :8080  # 自訂位址
//	birdeye-web -csv path/to/output.csv
//
// 端點（與 Python web/app.py 相容，前端 index.html 直接沿用）：
//
//	GET  /                 儀表板
//	POST /api/parse        {sql, params?} → {status, result:{tree,mermaid,json}} | {status,error_type,message}
//	POST /api/reconstruct  {ast}          → {status, sql} | {status,error_type,message}
//	POST /api/upload_csv   multipart file → {status, message}
//	GET  /health           → {status:"ok"}
package main

import (
	_ "embed"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"sync"

	bird "github.com/1150513/birdeye-go"
)

//go:embed index.html
var indexHTML []byte

// server 持有可熱替換的 registry（透過 /api/upload_csv）。
type server struct {
	mu  sync.RWMutex
	reg *bird.MetadataRegistry
}

func newServer(reg *bird.MetadataRegistry) *server {
	if reg == nil {
		reg = bird.NewMetadataRegistry()
	}
	return &server{reg: reg}
}

func (s *server) registry() *bird.MetadataRegistry {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.reg
}

// routes 回傳完整的 http.Handler（供 main 與測試共用）。
func (s *server) routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/", s.handleIndex)
	mux.HandleFunc("/api/parse", s.handleParse)
	mux.HandleFunc("/api/reconstruct", s.handleReconstruct)
	mux.HandleFunc("/api/upload_csv", s.handleUploadCSV)
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]any{"status": "ok"})
	})
	return noCache(mux)
}

func main() {
	addr := flag.String("addr", ":5000", "監聽位址")
	csv := flag.String("csv", "data/output.csv", "預設元數據 CSV 路徑")
	flag.Parse()

	reg := bird.NewMetadataRegistry()
	if b, err := os.ReadFile(*csv); err != nil {
		log.Printf("⚠️  找不到 %s，將以無元數據啟動（可在網頁上傳 CSV）", *csv)
	} else if err := reg.LoadFromCSV(string(b)); err != nil {
		log.Fatalf("元數據載入失敗：%v", err)
	} else {
		log.Printf("已載入元數據：%s", *csv)
	}

	srv := newServer(reg)
	fmt.Printf("🦅 BirdEye-SQL Visualizer → http://127.0.0.1%s\n", strings.TrimPrefix(*addr, "0.0.0.0"))
	log.Fatal(http.ListenAndServe(*addr, srv.routes()))
}

func noCache(h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
		h.ServeHTTP(w, r)
	})
}

func (s *server) handleIndex(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Write(indexHTML)
}

func (s *server) handleParse(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var body struct {
		SQL    string          `json:"sql"`
		Params json.RawMessage `json:"params"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || strings.TrimSpace(body.SQL) == "" {
		writeErr(w, 400, "Request Error", "Missing 'sql' in payload")
		return
	}
	params, err := parseParams(body.Params)
	if err != nil {
		writeErr(w, 400, "Syntax Error", "params: "+err.Error())
		return
	}
	res, err := bird.NewRunner(s.registry()).RunMulti(body.SQL, params)
	if err != nil {
		be, _ := err.(*bird.Error)
		status, kind := 400, "Syntax Error"
		if be != nil && be.Kind == bird.ErrSemantic {
			kind = "Semantic Error"
		} else if be != nil && be.Kind == bird.ErrSystem {
			status, kind = 500, "System Error"
		}
		writeErr(w, status, kind, err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{
		"status": "success",
		"result": map[string]any{"tree": res.Tree, "mermaid": res.Mermaid, "json": res.JSON},
	})
}

func (s *server) handleReconstruct(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var body struct {
		AST json.RawMessage `json:"ast"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || len(body.AST) == 0 {
		writeErr(w, 400, "Request Error", "Missing 'ast' in payload")
		return
	}
	// ast 可為 JSON 字串或 JSON 物件；字串 → 取內層值，物件 → 直接用原始 bytes
	astJSON := string(body.AST)
	var asStr string
	if json.Unmarshal(body.AST, &asStr) == nil {
		astJSON = asStr
	}
	sql, err := bird.NewReconstructor().Reconstruct(astJSON)
	if err != nil {
		writeErr(w, 400, "Reconstruct Error", err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"status": "success", "sql": sql})
}

func (s *server) handleUploadCSV(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	if err := r.ParseMultipartForm(8 << 20); err != nil {
		writeJSON(w, 400, map[string]any{"status": "error", "message": "No file part"})
		return
	}
	f, hdr, err := r.FormFile("file")
	if err != nil {
		writeJSON(w, 400, map[string]any{"status": "error", "message": "No file part"})
		return
	}
	defer f.Close()
	if hdr.Filename == "" || !strings.HasSuffix(strings.ToLower(hdr.Filename), ".csv") {
		writeJSON(w, 400, map[string]any{"status": "error", "message": "File must be a .csv"})
		return
	}
	content, err := io.ReadAll(f)
	if err != nil {
		writeJSON(w, 400, map[string]any{"status": "error", "message": "Failed to read file"})
		return
	}
	reg := bird.NewMetadataRegistry()
	if err := reg.LoadFromCSV(string(content)); err != nil {
		writeJSON(w, 400, map[string]any{"status": "error", "message": "Failed to parse CSV: " + err.Error()})
		return
	}
	s.mu.Lock()
	s.reg = reg
	s.mu.Unlock()
	writeJSON(w, 200, map[string]any{
		"status": "success", "message": "Successfully loaded metadata from " + hdr.Filename + ".",
	})
}

// ── helpers ────────────────────────────────────────────────────────────────

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, code int, kind, msg string) {
	writeJSON(w, code, map[string]any{"status": "error", "error_type": kind, "message": msg})
}

// parseParams：nil/空 → nil；JSON 物件 → *OrderedParams（保留 key 順序）；JSON 陣列 → []any。
func parseParams(raw json.RawMessage) (any, error) {
	s := strings.TrimSpace(string(raw))
	if s == "" || s == "null" {
		return nil, nil
	}
	dec := json.NewDecoder(strings.NewReader(s))
	dec.UseNumber()
	tok, err := dec.Token()
	if err != nil {
		return nil, err
	}
	delim, ok := tok.(json.Delim)
	if !ok {
		return nil, fmt.Errorf("must be a JSON object or array")
	}
	switch delim {
	case '[':
		var arr []any
		for dec.More() {
			var v any
			if err := dec.Decode(&v); err != nil {
				return nil, err
			}
			arr = append(arr, normNumbers(v))
		}
		return arr, nil
	case '{':
		op := &bird.OrderedParams{Vals: map[string]any{}}
		for dec.More() {
			kt, err := dec.Token()
			if err != nil {
				return nil, err
			}
			key := kt.(string)
			var v any
			if err := dec.Decode(&v); err != nil {
				return nil, err
			}
			op.Keys = append(op.Keys, key)
			op.Vals[key] = normNumbers(v)
		}
		return op, nil
	}
	return nil, fmt.Errorf("must be a JSON object or array")
}

func normNumbers(v any) any {
	switch x := v.(type) {
	case json.Number:
		if i, err := x.Int64(); err == nil {
			return int(i)
		}
		f, _ := x.Float64()
		return f
	case map[string]any:
		for k, val := range x {
			x[k] = normNumbers(val)
		}
		return x
	case []any:
		for i, val := range x {
			x[i] = normNumbers(val)
		}
		return x
	}
	return v
}
