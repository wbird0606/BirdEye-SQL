package birdeye

import "fmt"

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
func rewriteQmarkSQL(sql string) (string, int) { return rewriteQmarkWith(sql, "@P") }

// QmarkToPositional 把字串／註解外的位置參數 ? 改寫成 @p1, @p2, ...（小寫，對應 SQL Server 驅動
// 之位置參數命名），供代理送交資料庫執行；字串字面值與註解內之 ? 不受影響。
func QmarkToPositional(sql string) string {
	out, _ := rewriteQmarkWith(sql, "@p")
	return out
}

func rewriteQmarkWith(sql, prefix string) (string, int) {
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
			out = append(out, []rune(fmt.Sprintf("%s%d", prefix, pIdx))...)
		default:
			out = append(out, ch)
		}
	}
	return string(out), pIdx
}

// OrderedParams 是保留 key 順序的具名參數（byte-parity 需要）。
type OrderedParams struct {
	Keys []string
	Vals map[string]any
}

// prepareSQL 對照 _prepare_sql_and_params：依 params 型別決定 mode 並在必要時
// 改寫 ? 佔位符。params 為 nil / []any / map[string]any / *OrderedParams。
// 回傳最終要送進 lexer 的 SQL、mode、以及給 binder 的依序參數。
func prepareSQL(sql string, params any) (outSQL string, mode ParamMode, in *ParamInput, err error) {
	rewritten, qmarkCount := rewriteQmarkSQL(sql)

	switch p := params.(type) {
	case nil:
		if qmarkCount > 0 {
			return "", "", nil, valueErr(fmt.Sprintf(
				"PARAM_MISSING: SQL has %d '?' placeholders but no params were provided", qmarkCount))
		}
		return sql, ModeNone, nil, nil

	case []any:
		if qmarkCount == 0 && len(p) > 0 {
			// 原生位置參數 @p1…@pN（Go database/sql 之 SQL Server 驅動慣用寫法）：
			// 以依序之具名參數交給 binder，SQL 維持原樣。
			pi := &ParamInput{}
			for i, v := range p {
				pi.Ordered = append(pi.Ordered, ParamKV{Name: fmt.Sprintf("@p%d", i+1), Raw: v})
			}
			return sql, ModeNamed, pi, nil
		}
		if qmarkCount != len(p) {
			return "", "", nil, valueErr(fmt.Sprintf(
				"PARAM_COUNT_MISMATCH: SQL has %d '?' placeholders, but params has %d values",
				qmarkCount, len(p)))
		}
		pi := &ParamInput{}
		for i, v := range p {
			pi.Ordered = append(pi.Ordered, ParamKV{Name: fmt.Sprintf("@P%d", i+1), Raw: v})
		}
		return rewritten, ModeQmark, pi, nil

	case *OrderedParams:
		if qmarkCount > 0 {
			return "", "", nil, valueErr("PARAM_MODE_MIXED: SQL uses '?' placeholders but params is an object")
		}
		pi := &ParamInput{}
		for _, k := range p.Keys {
			pi.Ordered = append(pi.Ordered, ParamKV{Name: k, Raw: p.Vals[k]})
		}
		return sql, ModeNamed, pi, nil

	case map[string]any:
		if qmarkCount > 0 {
			return "", "", nil, valueErr("PARAM_MODE_MIXED: SQL uses '?' placeholders but params is an object")
		}
		pi := &ParamInput{}
		for k, v := range p {
			pi.Ordered = append(pi.Ordered, ParamKV{Name: k, Raw: v})
		}
		return sql, ModeNamed, pi, nil
	}

	return "", "", nil, valueErr("PARAM_FORMAT_INVALID: params must be object, array, or null")
}
