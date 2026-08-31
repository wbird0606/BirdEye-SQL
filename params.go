package birdeye

import (
	"fmt"
	"strings"
)

// 對照 Python birdeye/runner.py 的 _rewrite_qmark_sql / _prepare_sql_and_params。

// ParamMode 是一次執行的參數傳入形式（見 CONTEXT.md「Parameter Input Mode」）。
type ParamMode string

const (
	ModeNone  ParamMode = "none"
	ModeNamed ParamMode = "named"
	ModeQmark ParamMode = "qmark"
)

// rewriteQmarkSQL 把字串／註解外的位置參數 ? 改寫成 @P1, @P2, ...。
// 回傳 (改寫後 SQL, ? 的數量)。以 rune 為單位處理（與 Python 一致）。
func rewriteQmarkSQL(sql string) (string, int) {
	src := []rune(sql)
	var out []rune
	n := len(src)
	pIdx := 0
	inString, inLine, inBlock := false, false, false

	at := func(i int) rune {
		if i >= 0 && i < n {
			return src[i]
		}
		return 0
	}

	for i := 0; i < n; i++ {
		ch := src[i]
		nx := at(i + 1)

		switch {
		case inLine:
			out = append(out, ch)
			if ch == '\n' {
				inLine = false
			}
		case inBlock:
			out = append(out, ch)
			if ch == '*' && nx == '/' {
				out = append(out, nx)
				i++
				inBlock = false
			}
		case inString:
			out = append(out, ch)
			if ch == '\'' {
				if nx == '\'' { // T-SQL '' 轉義
					out = append(out, nx)
					i++
					continue
				}
				inString = false
			}
		case ch == '-' && nx == '-':
			out = append(out, ch, nx)
			i++
			inLine = true
		case ch == '/' && nx == '*':
			out = append(out, ch, nx)
			i++
			inBlock = true
		case ch == '\'':
			out = append(out, ch)
			inString = true
		case ch == '?':
			pIdx++
			out = append(out, []rune(fmt.Sprintf("@P%d", pIdx))...)
		default:
			out = append(out, ch)
		}
	}
	return string(out), pIdx
}

// prepareSQL 對照 _prepare_sql_and_params：依 params 型別決定 mode 並在必要時
// 改寫 ? 佔位符。params 為 nil / []any / map[string]any。
// 回傳最終要送進 lexer 的 SQL、mode、以及依序的參數名清單（qmark 模式為 @P1..@Pn）。
func prepareSQL(sql string, params any) (outSQL string, mode ParamMode, orderedNames []string, err error) {
	rewritten, qmarkCount := rewriteQmarkSQL(sql)

	switch p := params.(type) {
	case nil:
		if qmarkCount > 0 {
			return "", "", nil, valueErr(fmt.Sprintf(
				"PARAM_MISSING: SQL has %d '?' placeholders but no params were provided", qmarkCount))
		}
		return sql, ModeNone, nil, nil

	case []any:
		if qmarkCount != len(p) {
			return "", "", nil, valueErr(fmt.Sprintf(
				"PARAM_COUNT_MISMATCH: SQL has %d '?' placeholders, but params has %d values",
				qmarkCount, len(p)))
		}
		names := make([]string, len(p))
		for i := range p {
			names[i] = fmt.Sprintf("@P%d", i+1)
		}
		return rewritten, ModeQmark, names, nil

	case map[string]any:
		if qmarkCount > 0 {
			return "", "", nil, valueErr("PARAM_MODE_MIXED: SQL uses '?' placeholders but params is an object")
		}
		names := make([]string, 0, len(p))
		for k := range p {
			key := k
			if !strings.HasPrefix(key, "@") {
				key = "@" + key
			}
			names = append(names, strings.ToUpper(key))
		}
		return sql, ModeNamed, names, nil
	}

	return "", "", nil, valueErr("PARAM_FORMAT_INVALID: params must be object, array, or null")
}
