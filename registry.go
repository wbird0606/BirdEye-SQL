package birdeye

import (
	"encoding/csv"
	"strings"
)

// utf8BOM 對照 Python .lstrip(BOM)：去除 CSV 首欄殘留的 UTF-8 BOM。
const utf8BOM = "\uFEFF"

// FunctionMetadata 對照 Python birdeye/registry.py 的 FunctionMetadata。
type FunctionMetadata struct {
	Name          string
	FuncType      string // "SCALAR" / "AGGREGATE" / "WINDOW"
	MinArgs       int
	MaxArgs       int
	ExpectedTypes []string
	ReturnType    string
}

// MetadataRegistry 是資料表 schema 與內建函數元數據的唯一事實來源。
type MetadataRegistry struct {
	// tables: TABLE_KEY（大寫，"SCHEMA.TABLE" 或 "TABLE"）→ COL（大寫）→ TYPE（大寫）
	tables map[string]map[string]string
	// colOrder: TABLE_KEY → 欄位名（大寫）依 CSV 插入順序（對照 Python dict.keys()）
	colOrder            map[string][]string
	functions           map[string]*FunctionMetadata
	restrictedFunctions map[string]bool
}

// NewMetadataRegistry 建立空 registry 並註冊內建函數。
func NewMetadataRegistry() *MetadataRegistry {
	r := &MetadataRegistry{
		tables:    map[string]map[string]string{},
		colOrder:  map[string][]string{},
		functions: map[string]*FunctionMetadata{},
		restrictedFunctions: map[string]bool{
			"OPENROWSET": true, "OPENDATASOURCE": true, "OPENXML": true,
			"IS_SRVROLEMEMBER": true, "HAS_PERMS_BY_NAME": true,
		},
	}
	r.setupBuiltins()
	return r
}

func (r *MetadataRegistry) RegisterFunction(name, funcType string, minArgs, maxArgs int, expectedTypes []string, returnType string) {
	up := strings.ToUpper(name)
	if expectedTypes == nil {
		expectedTypes = []string{}
	}
	if returnType == "" { // 對照 Python register_function 的 return_type="UNKNOWN" 預設
		returnType = "UNKNOWN"
	}
	r.functions[up] = &FunctionMetadata{
		Name: up, FuncType: strings.ToUpper(funcType),
		MinArgs: minArgs, MaxArgs: maxArgs,
		ExpectedTypes: expectedTypes, ReturnType: strings.ToUpper(returnType),
	}
}

func (r *MetadataRegistry) setupBuiltins() {
	reg := r.RegisterFunction
	any1 := []string{"ANY"}
	nv := []string{"NVARCHAR"}

	// 聚合
	reg("SUM", "AGGREGATE", 1, 1, any1, "INT")
	reg("COUNT", "AGGREGATE", 0, 1, any1, "INT")
	reg("AVG", "AGGREGATE", 1, 1, any1, "INT")
	reg("MAX", "AGGREGATE", 1, 1, any1, "ANY")
	reg("MIN", "AGGREGATE", 1, 1, any1, "ANY")

	// 字串
	reg("LEN", "SCALAR", 1, 1, nv, "INT")
	reg("UPPER", "SCALAR", 1, 1, nv, "NVARCHAR")
	reg("LOWER", "SCALAR", 1, 1, nv, "NVARCHAR")
	reg("SUBSTRING", "SCALAR", 3, 3, []string{"NVARCHAR", "INT", "INT"}, "NVARCHAR")
	reg("REPLACE", "SCALAR", 3, 3, []string{"NVARCHAR", "NVARCHAR", "NVARCHAR"}, "NVARCHAR")
	reg("LTRIM", "SCALAR", 1, 1, nv, "NVARCHAR")
	reg("RTRIM", "SCALAR", 1, 1, nv, "NVARCHAR")
	reg("TRIM", "SCALAR", 1, 1, nv, "NVARCHAR")
	reg("CHARINDEX", "SCALAR", 2, 3, []string{"NVARCHAR", "NVARCHAR"}, "INT")
	reg("PATINDEX", "SCALAR", 2, 2, []string{"NVARCHAR", "NVARCHAR"}, "INT")
	reg("STUFF", "SCALAR", 4, 4, []string{"NVARCHAR", "INT", "INT", "NVARCHAR"}, "NVARCHAR")
	reg("LEFT", "SCALAR", 2, 2, []string{"NVARCHAR", "INT"}, "NVARCHAR")
	reg("RIGHT", "SCALAR", 2, 2, []string{"NVARCHAR", "INT"}, "NVARCHAR")
	reg("REPLICATE", "SCALAR", 2, 2, []string{"NVARCHAR", "INT"}, "NVARCHAR")
	reg("REVERSE", "SCALAR", 1, 1, nv, "NVARCHAR")
	reg("STR", "SCALAR", 1, 3, any1, "NVARCHAR")
	reg("STRING_AGG", "AGGREGATE", 2, 2, []string{"ANY", "NVARCHAR"}, "NVARCHAR")
	reg("CONCAT", "SCALAR", 1, 99, any1, "NVARCHAR")
	reg("CONCAT_WS", "SCALAR", 2, 99, nv, "NVARCHAR")
	reg("FORMAT", "SCALAR", 2, 3, []string{"ANY", "NVARCHAR"}, "NVARCHAR")
	reg("SPACE", "SCALAR", 1, 1, []string{"INT"}, "NVARCHAR")
	reg("UNICODE", "SCALAR", 1, 1, nv, "INT")
	reg("CHAR", "SCALAR", 1, 1, []string{"INT"}, "NVARCHAR")
	reg("ASCII", "SCALAR", 1, 1, nv, "INT")
	reg("NCHAR", "SCALAR", 1, 1, []string{"INT"}, "NVARCHAR")

	// 數值
	reg("ABS", "SCALAR", 1, 1, any1, "INT")
	reg("CEILING", "SCALAR", 1, 1, any1, "INT")
	reg("FLOOR", "SCALAR", 1, 1, any1, "INT")
	reg("ROUND", "SCALAR", 2, 3, []string{"ANY", "INT"}, "DECIMAL")
	reg("POWER", "SCALAR", 2, 2, []string{"ANY", "ANY"}, "DECIMAL")
	reg("SQRT", "SCALAR", 1, 1, any1, "DECIMAL")
	reg("SQUARE", "SCALAR", 1, 1, any1, "DECIMAL")
	reg("LOG", "SCALAR", 1, 2, any1, "DECIMAL")
	reg("EXP", "SCALAR", 1, 1, any1, "DECIMAL")
	reg("SIGN", "SCALAR", 1, 1, any1, "INT")
	reg("RAND", "SCALAR", 0, 1, any1, "DECIMAL")

	// 日期
	reg("GETDATE", "SCALAR", 0, 0, []string{}, "DATETIME")
	reg("GETUTCDATE", "SCALAR", 0, 0, []string{}, "DATETIME")
	reg("SYSDATETIME", "SCALAR", 0, 0, []string{}, "DATETIME")
	reg("DATEDIFF", "SCALAR", 3, 3, []string{"ANY", "ANY", "ANY"}, "INT")
	reg("DATEADD", "SCALAR", 3, 3, []string{"ANY", "INT", "ANY"}, "DATETIME")
	reg("DATEPART", "SCALAR", 2, 2, []string{"ANY", "ANY"}, "INT")
	reg("DATENAME", "SCALAR", 2, 2, []string{"ANY", "ANY"}, "NVARCHAR")
	reg("YEAR", "SCALAR", 1, 1, any1, "INT")
	reg("MONTH", "SCALAR", 1, 1, any1, "INT")
	reg("DAY", "SCALAR", 1, 1, any1, "INT")
	reg("EOMONTH", "SCALAR", 1, 2, any1, "DATE")
	reg("ISDATE", "SCALAR", 1, 1, any1, "BIT")

	// NULL 處理
	reg("ISNULL", "SCALAR", 2, 2, []string{"ANY", "ANY"}, "ANY")
	reg("COALESCE", "SCALAR", 1, 99, any1, "ANY")
	reg("NULLIF", "SCALAR", 2, 2, []string{"ANY", "ANY"}, "ANY")
	reg("IIF", "SCALAR", 3, 3, []string{"ANY", "ANY", "ANY"}, "ANY")

	// 型別轉換／判斷
	reg("ISNUMERIC", "SCALAR", 1, 1, any1, "BIT")
	reg("TRY_CAST", "SCALAR", 1, 1, any1, "ANY")
	reg("TRY_CONVERT", "SCALAR", 2, 3, []string{"ANY", "ANY"}, "ANY")

	// 特殊結構
	reg("EXISTS", "SCALAR", 1, 1, any1, "BIT")
	reg("NOT EXISTS", "SCALAR", 1, 1, any1, "BIT")

	// UUID
	reg("NEWID", "SCALAR", 0, 0, []string{}, "UNIQUEIDENTIFIER")
	reg("NEWSEQUENTIALID", "SCALAR", 0, 0, []string{}, "UNIQUEIDENTIFIER")

	// JSON
	reg("JSON_VALUE", "SCALAR", 2, 2, []string{"ANY", "NVARCHAR"}, "NVARCHAR")
	reg("JSON_QUERY", "SCALAR", 2, 2, []string{"ANY", "NVARCHAR"}, "NVARCHAR")
	reg("JSON_MODIFY", "SCALAR", 3, 3, []string{"ANY", "NVARCHAR", "ANY"}, "NVARCHAR")
	reg("ISJSON", "SCALAR", 1, 1, any1, "BIT")

	// 窗函數 —— 排序
	reg("ROW_NUMBER", "WINDOW", 0, 0, []string{}, "BIGINT")
	reg("RANK", "WINDOW", 0, 0, []string{}, "BIGINT")
	reg("DENSE_RANK", "WINDOW", 0, 0, []string{}, "BIGINT")
	reg("NTILE", "WINDOW", 1, 1, []string{"INT"}, "INT")

	// 窗函數 —— 分析
	reg("LAG", "WINDOW", 1, 3, []string{"ANY", "INT", "ANY"}, "ANY")
	reg("LEAD", "WINDOW", 1, 3, []string{"ANY", "INT", "ANY"}, "ANY")
	reg("FIRST_VALUE", "WINDOW", 1, 1, any1, "ANY")
	reg("LAST_VALUE", "WINDOW", 1, 1, any1, "ANY")
	reg("NTH_VALUE", "WINDOW", 2, 2, []string{"ANY", "INT"}, "ANY")
	reg("PERCENT_RANK", "WINDOW", 0, 0, []string{}, "DECIMAL")
	reg("CUME_DIST", "WINDOW", 0, 0, []string{}, "DECIMAL")
	reg("PERCENT_CONT", "WINDOW", 1, 1, []string{"DECIMAL"}, "ANY")
	reg("PERCENTILE_CONT", "WINDOW", 1, 1, []string{"DECIMAL"}, "ANY")
	reg("PERCENTILE_DISC", "WINDOW", 1, 1, []string{"DECIMAL"}, "ANY")

	// 窗函數 —— 聚合（支援 OVER）
	reg("SUM_WINDOW", "WINDOW", 1, 1, any1, "INT")
	reg("AVG_WINDOW", "WINDOW", 1, 1, any1, "DECIMAL")
	reg("COUNT_WINDOW", "WINDOW", 0, 1, any1, "INT")
	reg("MIN_WINDOW", "WINDOW", 1, 1, any1, "ANY")
	reg("MAX_WINDOW", "WINDOW", 1, 1, any1, "ANY")
}

// ── CSV 載入 ────────────────────────────────────────────────────────────────

// LoadFromCSV 對照 Python load_from_csv：支援 3 欄 / 4 欄格式、有無標頭、BOM。
func (r *MetadataRegistry) LoadFromCSV(content string) error {
	firstLine := content
	if i := strings.IndexByte(content, '\n'); i >= 0 {
		firstLine = content[:i]
	}
	firstUpper := strings.ToUpper(firstLine)
	hasHeader := strings.Contains(firstUpper, "TABLE_NAME") || strings.Contains(firstUpper, "COLUMN_NAME")

	rd := csv.NewReader(strings.NewReader(content))
	rd.FieldsPerRecord = -1
	records, err := rd.ReadAll()
	if err != nil {
		return valueErr("CSV parse error: " + err.Error())
	}
	if len(records) == 0 {
		return nil
	}

	var fieldNames []string
	dataRows := records
	if hasHeader {
		fieldNames = records[0]
		dataRows = records[1:]
	} else {
		colCount := len(strings.Split(strings.TrimRight(firstLine, "\r"), ","))
		if colCount >= 4 {
			fieldNames = []string{"table_schema", "table_name", "column_name", "data_type"}
		} else {
			fieldNames = []string{"table_name", "column_name", "data_type"}
		}
	}

	col := func(rec []string, name string) string {
		for i, fn := range fieldNames {
			if fn == name && i < len(rec) {
				return rec[i]
			}
		}
		return ""
	}

	for _, rec := range dataRows {
		tn := col(rec, "table_name")
		cn := col(rec, "column_name")
		if tn == "" || cn == "" {
			continue
		}
		tName := strings.ToUpper(strings.TrimSpace(strings.TrimLeft(tn, utf8BOM)))
		cName := strings.ToUpper(strings.TrimSpace(cn))
		dt := col(rec, "data_type")
		if dt == "" {
			dt = "UNKNOWN"
		}
		dType := strings.ToUpper(strings.TrimSpace(dt))
		schema := strings.ToUpper(strings.TrimSpace(strings.TrimLeft(col(rec, "table_schema"), utf8BOM)))
		key := tName
		if schema != "" {
			key = schema + "." + tName
		}
		if r.tables[key] == nil {
			r.tables[key] = map[string]string{}
		}
		if _, exists := r.tables[key][cName]; !exists {
			r.colOrder[key] = append(r.colOrder[key], cName)
		}
		r.tables[key][cName] = dType
	}
	return nil
}

// ── 資料表查詢 ──────────────────────────────────────────────────────────────

// resolveKey 對照 _resolve_key。
func (r *MetadataRegistry) resolveKey(name string) string {
	k := strings.ToUpper(name)
	if _, ok := r.tables[k]; ok {
		return k
	}
	if strings.Contains(k, ".") {
		parts := strings.Split(k, ".")
		short := parts[len(parts)-1]
		if _, ok := r.tables[short]; ok {
			return short
		}
	} else {
		suffix := "." + k
		var match string
		count := 0
		for key := range r.tables {
			if strings.HasSuffix(key, suffix) {
				match = key
				count++
			}
		}
		if count == 1 {
			return match
		}
	}
	return k
}

func (r *MetadataRegistry) HasTable(name string) bool {
	_, ok := r.tables[r.resolveKey(name)]
	return ok
}

// GetColumns 回傳欄位清單，順序為 CSV 插入順序（對照 Python dict.keys()）。
func (r *MetadataRegistry) GetColumns(name string) []string {
	key := r.resolveKey(name)
	if r.tables[key] == nil {
		return nil
	}
	return append([]string(nil), r.colOrder[key]...)
}

func (r *MetadataRegistry) HasColumn(table, column string) bool {
	t := r.tables[r.resolveKey(table)]
	if t == nil {
		return false
	}
	_, ok := t[strings.ToUpper(column)]
	return ok
}

func (r *MetadataRegistry) GetColumnType(table, column string) string {
	t := r.tables[r.resolveKey(table)]
	if t == nil {
		return "UNKNOWN"
	}
	if ty, ok := t[strings.ToUpper(column)]; ok {
		return ty
	}
	return "UNKNOWN"
}

func (r *MetadataRegistry) GetColumnCount(table string) int {
	return len(r.tables[r.resolveKey(table)])
}

// ── 函數查詢 ────────────────────────────────────────────────────────────────

func (r *MetadataRegistry) HasFunction(name string) bool {
	_, ok := r.functions[strings.ToUpper(name)]
	return ok
}

func (r *MetadataRegistry) GetFunction(name string) *FunctionMetadata {
	return r.functions[strings.ToUpper(name)]
}

func (r *MetadataRegistry) IsAggregate(name string) bool {
	m := r.GetFunction(name)
	return m != nil && m.FuncType == "AGGREGATE"
}

func (r *MetadataRegistry) IsRestricted(name string) bool {
	return r.restrictedFunctions[strings.ToUpper(name)]
}
