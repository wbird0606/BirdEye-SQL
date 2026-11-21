// Command birdeye-svc 是 birdeye 引擎的獨立 HTTP 服務，對照 Python birdeye-svc/app.py。
// zta-proxy 以 BIRDEYE_MODE=http 指向本服務。
//
// 端點：
//
//	POST /intents  {sql, db_id, params, trace_id} → {intents:[{schema,table,column,intent}], ast_json}
//	POST /rewrite  {ast_json, row_filters}        → {sql}
//	GET  /health   → {status:"ok"}
//
// 環境變數（與 Python birdeye-svc 一致）：
//
//	PORT                監聽埠（預設 8001）
//	PERMISSION_API_URL  欄位 schema 來源（預設 http://localhost:50010）
//	ZTA_API_KEY         X-ZTA-ApiKey header
//	HTTP_TIMEOUT        向 Permission API 的逾時秒數（預設 10）
//	BIRDEYE_CACHE_TTL   意圖結果快取秒數（預設 300）
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"time"

	bird "github.com/wbird0606/BirdEye-SQL"
)

func main() {
	port := getenv("PORT", "8001")
	permURL := getenv("PERMISSION_API_URL", "http://localhost:50010")
	apiKey := os.Getenv("ZTA_API_KEY")
	httpTimeout := time.Duration(getenvInt("HTTP_TIMEOUT", 10)) * time.Second
	cacheTTL := time.Duration(getenvInt("BIRDEYE_CACHE_TTL", 300)) * time.Second

	fetch := httpSchemaFetcher(permURL, apiKey, httpTimeout)
	h := newService(bird.NewAnalyser(fetch, cacheTTL))

	addr := ":" + port
	log.Printf("birdeye-svc → %s  (permission API: %s)", addr, permURL)
	log.Fatal(http.ListenAndServe(addr, h))
}

// newService 回傳完整的 http.Handler（供 main 與測試共用）。
func newService(a *bird.Analyser) http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("/intents", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			w.WriteHeader(405)
			return
		}
		var body struct {
			SQL    string `json:"sql"`
			DbID   int    `json:"db_id"`
			Params []any  `json:"params"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			writeErr(w, 400, "invalid JSON")
			return
		}
		if body.SQL == "" {
			writeErr(w, 400, "sql is required")
			return
		}
		res, err := a.GetIntents(r.Context(), body.SQL, body.DbID, body.Params)
		if err != nil {
			var be *bird.Error
			if errors.As(err, &be) && be.Kind != bird.ErrSystem {
				writeErr(w, 400, "BirdEye parse error: "+err.Error())
			} else {
				writeErr(w, 500, "BirdEye intent error: "+err.Error())
			}
			return
		}
		writeJSON(w, 200, map[string]any{"intents": res.Intents, "ast_json": res.ASTJSON})
	})

	mux.HandleFunc("/rewrite", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			w.WriteHeader(405)
			return
		}
		var body struct {
			ASTJSON    string           `json:"ast_json"`
			RowFilters []bird.RowFilter `json:"row_filters"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			writeErr(w, 400, "invalid JSON")
			return
		}
		if body.ASTJSON == "" {
			writeErr(w, 400, "ast_json is required")
			return
		}
		sql, err := a.Rewrite(body.ASTJSON, body.RowFilters)
		if err != nil {
			writeErr(w, 400, err.Error())
			return
		}
		writeJSON(w, 200, map[string]any{"sql": sql})
	})

	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]any{"status": "ok"})
	})

	return mux
}

// httpSchemaFetcher 向 Permission API 的 GET /api/zta/columns 查欄位。
func httpSchemaFetcher(permURL, apiKey string, timeout time.Duration) bird.SchemaFetcher {
	hc := &http.Client{Timeout: timeout}
	return func(ctx context.Context, dbID int, schema, table string) ([]bird.SchemaColumn, error) {
		q := url.Values{}
		q.Set("dbId", strconv.Itoa(dbID))
		q.Set("schema", schema)
		q.Set("table", table)
		req, _ := http.NewRequestWithContext(ctx, http.MethodGet, permURL+"/api/zta/columns?"+q.Encode(), nil)
		if apiKey != "" {
			req.Header.Set("X-ZTA-ApiKey", apiKey)
		}
		resp, err := hc.Do(req)
		if err != nil {
			return nil, err
		}
		defer resp.Body.Close()
		var env struct {
			Success bool `json:"success"`
			Data    []struct {
				ColumnName string `json:"ColumnName"`
				DataType   string `json:"DataType"`
			} `json:"data"`
		}
		if err := json.NewDecoder(resp.Body).Decode(&env); err != nil {
			return nil, err
		}
		if resp.StatusCode != http.StatusOK || !env.Success {
			return nil, fmt.Errorf("columns API %d", resp.StatusCode)
		}
		out := make([]bird.SchemaColumn, len(env.Data))
		for i, c := range env.Data {
			out[i] = bird.SchemaColumn{ColumnName: c.ColumnName, DataType: c.DataType}
		}
		return out, nil
	}
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, code int, msg string) {
	writeJSON(w, code, map[string]any{"error": msg})
}

func getenv(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func getenvInt(k string, def int) int {
	if v := os.Getenv(k); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}
