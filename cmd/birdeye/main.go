// Command birdeye 是 birdeye-go 的指令列介面，對照 Python 版 main.py。
//
//	birdeye -sql "SELECT * FROM Address" -format all
//	birdeye -file query.sql -csv data/output.csv -format json
//	birdeye -ast '{"node_type":"SelectStatement",...}'
//	birdeye -ast-file ast.json
//	birdeye -sql "SELECT @p AS x" -params '{"@p": 30}'
//	birdeye -sql "SELECT ?, ?" -params '["Taipei", 30]'
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	bird "github.com/1150513/birdeye-go"
)

func main() { os.Exit(run(os.Args[1:], os.Stdout, os.Stderr)) }

func run(args []string, stdout, stderr io.Writer) int {
	fs := flag.NewFlagSet("birdeye", flag.ContinueOnError)
	fs.SetOutput(stderr)
	sql := fs.String("sql", "", "[SQL→AST] 直接輸入 SQL 查詢字串")
	file := fs.String("file", "", "[SQL→AST] 從檔案讀取 SQL 查詢")
	ast := fs.String("ast", "", "[AST→SQL] 直接輸入 AST JSON 字串")
	astFile := fs.String("ast-file", "", "[AST→SQL] 從檔案讀取 AST JSON")
	csv := fs.String("csv", "data/output.csv", "元數據 CSV 檔案路徑")
	format := fs.String("format", "tree", "[SQL→AST] 輸出格式：tree | mermaid | json | all")
	params := fs.String("params", "", "[SQL→AST] 參數 JSON：具名 {\"@city\":\"Taipei\"} 或位置 [\"Taipei\",30]")
	paramsFile := fs.String("params-file", "", "[SQL→AST] 從檔案讀取參數 JSON")
	if err := fs.Parse(args); err != nil {
		return 2
	}

	// 輸入來源二擇一（SQL→AST 或 AST→SQL）
	nInputs := 0
	for _, s := range []string{*sql, *file, *ast, *astFile} {
		if s != "" {
			nInputs++
		}
	}
	if nInputs == 0 {
		fmt.Fprintln(stderr, "❌ 錯誤：the following arguments are required: 需指定 -sql / -file / -ast / -ast-file 其中之一")
		fs.Usage()
		return 2
	}
	if nInputs > 1 {
		fmt.Fprintln(stderr, "❌ 錯誤：-sql / -file / -ast / -ast-file 互斥，只能指定一個")
		return 2
	}

	// ── AST → SQL 模式 ──────────────────────────────
	if *ast != "" || *astFile != "" {
		jsonStr := *ast
		if *astFile != "" {
			b, err := os.ReadFile(*astFile)
			if err != nil {
				fmt.Fprintf(stderr, "❌ 錯誤：找不到 AST 檔案 '%s'\n", *astFile)
				return 1
			}
			jsonStr = string(b)
		}
		out, err := bird.NewReconstructor().Reconstruct(jsonStr)
		if err != nil {
			fmt.Fprintf(stderr, "\n💥 [AST→SQL 錯誤] %v\n", err)
			return 1
		}
		fmt.Fprintln(stdout, out)
		return 0
	}

	// ── SQL → AST 模式 ──────────────────────────────
	if *format != "tree" && *format != "mermaid" && *format != "json" && *format != "all" {
		fmt.Fprintf(stderr, "❌ 錯誤：未知格式 '%s'（tree | mermaid | json | all）\n", *format)
		return 2
	}

	query := *sql
	if *file != "" {
		b, err := os.ReadFile(*file)
		if err != nil {
			fmt.Fprintf(stderr, "❌ 錯誤：找不到 SQL 檔案 '%s'\n", *file)
			return 1
		}
		query = string(b)
	}

	runner := bird.NewRunner(nil)
	if b, err := os.ReadFile(*csv); err != nil {
		fmt.Fprintf(stderr, "⚠️ 警告：找不到元數據檔案 '%s'，將在無元數據下解析（語意綁定可能失敗）。\n", *csv)
	} else if err := runner.LoadMetadataFromCSV(string(b)); err != nil {
		fmt.Fprintf(stderr, "❌ 錯誤：元數據載入失敗：%v\n", err)
		return 1
	}

	// 解析參數
	var p any
	raw := *params
	if *paramsFile != "" {
		b, err := os.ReadFile(*paramsFile)
		if err != nil {
			fmt.Fprintf(stderr, "❌ 錯誤：找不到參數檔案 '%s'\n", *paramsFile)
			return 1
		}
		raw = string(b)
	}
	if strings.TrimSpace(raw) != "" {
		parsed, err := parseParams(raw)
		if err != nil {
			fmt.Fprintf(stderr, "❌ 錯誤：-params 解析失敗：%v\n", err)
			return 1
		}
		p = parsed
	}

	res, err := runner.Run(query, p)
	if err != nil {
		be, _ := err.(*bird.Error)
		switch {
		case be != nil && be.Kind == bird.ErrSemantic:
			fmt.Fprintf(stderr, "\n🛡️ [資安/語意攔截 Semantic Error] %v\n", err)
		case be != nil && (be.Kind == bird.ErrSyntax || be.Kind == bird.ErrValue):
			fmt.Fprintf(stderr, "\n❌ [語法錯誤 Syntax Error] %v\n", err)
		default:
			fmt.Fprintf(stderr, "\n💥 [未預期錯誤 System Error] %v\n", err)
		}
		return 1
	}

	all := *format == "all"
	if *format == "tree" || all {
		if all {
			fmt.Fprintln(stdout, "\n=== AST Tree ===")
		}
		fmt.Fprintln(stdout, res.Tree)
	}
	if *format == "mermaid" || all {
		if all {
			fmt.Fprintln(stdout, "\n=== Mermaid Chart ===")
		}
		fmt.Fprintln(stdout, res.Mermaid)
	}
	if *format == "json" || all {
		if all {
			fmt.Fprintln(stdout, "\n=== AST JSON ===")
		}
		fmt.Fprintln(stdout, res.JSON)
	}
	return 0
}

// parseParams 解析 -params：JSON 物件 → 具名（保留 key 順序）；JSON 陣列 → 位置參數。
func parseParams(raw string) (any, error) {
	dec := json.NewDecoder(strings.NewReader(strings.TrimSpace(raw)))
	dec.UseNumber()
	tok, err := dec.Token()
	if err != nil {
		return nil, err
	}
	delim, ok := tok.(json.Delim)
	if !ok {
		return nil, fmt.Errorf("參數必須是 JSON 物件或陣列")
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
	return nil, fmt.Errorf("參數必須是 JSON 物件或陣列")
}

// normNumbers 把 json.Number 轉成 int（整數）或 float64，讓 binder 的型別推導正確。
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
