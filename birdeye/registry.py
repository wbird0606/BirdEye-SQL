import csv

class FunctionMetadata:
    """
    💡 Issue #35: 強化版函數元數據。
    支援參數類型檢查 (Type Checking) 與結果類型推導 (Type Inference)。
    """
    def __init__(self, name, func_type, min_args=1, max_args=1, expected_types=None, return_type="UNKNOWN"):
        self.name = name.upper()
        self.func_type = func_type.upper()  # 'SCALAR' 或 'AGGREGATE'
        self.min_args = min_args
        self.max_args = max_args
        # 預期參數類型清單 (例如 ["NVARCHAR", "INT", "INT"] 針對 SUBSTRING)
        self.expected_types = expected_types or [] 
        self.return_type = return_type.upper()

class MetadataRegistry:
    """
    元數據註冊表：核心 Source of Truth。
    v1.7.5: 實作數據類型感知與函數類型定義。
    """
    def __init__(self):
        # 表格元數據: { TABLE_NAME: { COL_NAME: DATA_TYPE } }
        self.tables = {}
        self.functions = {}
        self.restricted_functions = {
            "OPENROWSET", "OPENDATASOURCE", "OPENXML", 
            "IS_SRVROLEMEMBER", "HAS_PERMS_BY_NAME"
        }
        self._setup_builtins()

    def _setup_builtins(self):
        """
        🛡️ 註冊內建函數與其類型規則
        格式: name, type, min, max, [expected_types], return_type
        """
        # --- 聚合函數 (SUM/AVG 支援所有數值類型) ---
        self.register_function("SUM", "AGGREGATE", 1, 1, ["ANY"], "INT")
        self.register_function("COUNT", "AGGREGATE", 0, 1, ["ANY"], "INT")
        self.register_function("AVG", "AGGREGATE", 1, 1, ["ANY"], "INT")
        self.register_function("MAX", "AGGREGATE", 1, 1, ["ANY"], "ANY")
        self.register_function("MIN", "AGGREGATE", 1, 1, ["ANY"], "ANY")
        
        # --- 標量函數: 字串類 ---
        self.register_function("LEN", "SCALAR", 1, 1, ["NVARCHAR"], "INT")
        self.register_function("UPPER", "SCALAR", 1, 1, ["NVARCHAR"], "NVARCHAR")
        self.register_function("LOWER", "SCALAR", 1, 1, ["NVARCHAR"], "NVARCHAR")
        self.register_function("SUBSTRING", "SCALAR", 3, 3, ["NVARCHAR", "INT", "INT"], "NVARCHAR")
        self.register_function("REPLACE", "SCALAR", 3, 3, ["NVARCHAR", "NVARCHAR", "NVARCHAR"], "NVARCHAR")
        self.register_function("LTRIM", "SCALAR", 1, 1, ["NVARCHAR"], "NVARCHAR")
        self.register_function("RTRIM", "SCALAR", 1, 1, ["NVARCHAR"], "NVARCHAR")
        self.register_function("TRIM", "SCALAR", 1, 1, ["NVARCHAR"], "NVARCHAR")
        self.register_function("CHARINDEX", "SCALAR", 2, 3, ["NVARCHAR", "NVARCHAR"], "INT")
        self.register_function("PATINDEX", "SCALAR", 2, 2, ["NVARCHAR", "NVARCHAR"], "INT")
        self.register_function("STUFF", "SCALAR", 4, 4, ["NVARCHAR", "INT", "INT", "NVARCHAR"], "NVARCHAR")
        self.register_function("LEFT", "SCALAR", 2, 2, ["NVARCHAR", "INT"], "NVARCHAR")
        self.register_function("RIGHT", "SCALAR", 2, 2, ["NVARCHAR", "INT"], "NVARCHAR")
        self.register_function("REPLICATE", "SCALAR", 2, 2, ["NVARCHAR", "INT"], "NVARCHAR")
        self.register_function("REVERSE", "SCALAR", 1, 1, ["NVARCHAR"], "NVARCHAR")
        self.register_function("STR", "SCALAR", 1, 3, ["ANY"], "NVARCHAR")
        self.register_function("STRING_AGG", "AGGREGATE", 2, 2, ["ANY", "NVARCHAR"], "NVARCHAR")
        self.register_function("CONCAT", "SCALAR", 1, 99, ["ANY"], "NVARCHAR")
        self.register_function("CONCAT_WS", "SCALAR", 2, 99, ["NVARCHAR"], "NVARCHAR")
        self.register_function("FORMAT", "SCALAR", 2, 3, ["ANY", "NVARCHAR"], "NVARCHAR")
        self.register_function("SPACE", "SCALAR", 1, 1, ["INT"], "NVARCHAR")
        self.register_function("UNICODE", "SCALAR", 1, 1, ["NVARCHAR"], "INT")
        self.register_function("CHAR", "SCALAR", 1, 1, ["INT"], "NVARCHAR")
        self.register_function("ASCII", "SCALAR", 1, 1, ["NVARCHAR"], "INT")
        self.register_function("NCHAR", "SCALAR", 1, 1, ["INT"], "NVARCHAR")

        # --- 標量函數: 數值類 ---
        self.register_function("ABS", "SCALAR", 1, 1, ["ANY"], "INT")
        self.register_function("CEILING", "SCALAR", 1, 1, ["ANY"], "INT")
        self.register_function("FLOOR", "SCALAR", 1, 1, ["ANY"], "INT")
        self.register_function("ROUND", "SCALAR", 2, 3, ["ANY", "INT"], "DECIMAL")
        self.register_function("POWER", "SCALAR", 2, 2, ["ANY", "ANY"], "DECIMAL")
        self.register_function("SQRT", "SCALAR", 1, 1, ["ANY"], "DECIMAL")
        self.register_function("SQUARE", "SCALAR", 1, 1, ["ANY"], "DECIMAL")
        self.register_function("LOG", "SCALAR", 1, 2, ["ANY"], "DECIMAL")
        self.register_function("EXP", "SCALAR", 1, 1, ["ANY"], "DECIMAL")
        self.register_function("SIGN", "SCALAR", 1, 1, ["ANY"], "INT")
        self.register_function("RAND", "SCALAR", 0, 1, ["ANY"], "DECIMAL")

        # --- 標量函數: 日期類 ---
        self.register_function("GETDATE", "SCALAR", 0, 0, [], "DATETIME")
        self.register_function("GETUTCDATE", "SCALAR", 0, 0, [], "DATETIME")
        self.register_function("SYSDATETIME", "SCALAR", 0, 0, [], "DATETIME")
        self.register_function("DATEDIFF", "SCALAR", 3, 3, ["ANY", "ANY", "ANY"], "INT")
        self.register_function("DATEADD", "SCALAR", 3, 3, ["ANY", "INT", "ANY"], "DATETIME")
        self.register_function("DATEPART", "SCALAR", 2, 2, ["ANY", "ANY"], "INT")
        self.register_function("DATENAME", "SCALAR", 2, 2, ["ANY", "ANY"], "NVARCHAR")
        self.register_function("YEAR", "SCALAR", 1, 1, ["ANY"], "INT")
        self.register_function("MONTH", "SCALAR", 1, 1, ["ANY"], "INT")
        self.register_function("DAY", "SCALAR", 1, 1, ["ANY"], "INT")
        self.register_function("EOMONTH", "SCALAR", 1, 2, ["ANY"], "DATE")
        self.register_function("ISDATE", "SCALAR", 1, 1, ["ANY"], "BIT")

        # --- 標量函數: NULL 處理類 ---
        self.register_function("ISNULL", "SCALAR", 2, 2, ["ANY", "ANY"], "ANY")
        self.register_function("COALESCE", "SCALAR", 1, 99, ["ANY"], "ANY")
        self.register_function("NULLIF", "SCALAR", 2, 2, ["ANY", "ANY"], "ANY")
        self.register_function("IIF", "SCALAR", 3, 3, ["ANY", "ANY", "ANY"], "ANY")

        # --- 標量函數: 型別轉換/判斷類 ---
        self.register_function("ISNUMERIC", "SCALAR", 1, 1, ["ANY"], "BIT")
        self.register_function("TRY_CAST", "SCALAR", 1, 1, ["ANY"], "ANY")
        self.register_function("TRY_CONVERT", "SCALAR", 2, 3, ["ANY", "ANY"], "ANY")

        # --- 特殊結構 ---
        self.register_function("EXISTS", "SCALAR", 1, 1, ["ANY"], "BIT")
        self.register_function("NOT EXISTS", "SCALAR", 1, 1, ["ANY"], "BIT")

        # --- UUID 函數 (Issue #54) ---
        self.register_function("NEWID", "SCALAR", 0, 0, [], "UNIQUEIDENTIFIER")
        self.register_function("NEWSEQUENTIALID", "SCALAR", 0, 0, [], "UNIQUEIDENTIFIER")

        # --- JSON 函數 (Issue #54) ---
        self.register_function("JSON_VALUE",  "SCALAR", 2, 2, ["ANY", "NVARCHAR"], "NVARCHAR")
        self.register_function("JSON_QUERY",  "SCALAR", 2, 2, ["ANY", "NVARCHAR"], "NVARCHAR")
        self.register_function("JSON_MODIFY", "SCALAR", 3, 3, ["ANY", "NVARCHAR", "ANY"], "NVARCHAR")
        self.register_function("ISJSON",      "SCALAR", 1, 1, ["ANY"], "BIT")

    # --- 1. 資料表與欄位類型管理 ---

    def load_from_csv(self, csv_file_obj):
        """載入表格定義，包含 data_type 欄位。
        支援三欄格式（table_name, column_name, data_type）
        與四欄格式（table_schema, table_name, column_name, data_type）。
        四欄格式下以 SCHEMA.TABLE 為 key，支援跨 schema 同名資料表。
        """
        import io

        content = csv_file_obj.read()
        if isinstance(content, bytes):
            content = content.decode('utf-8')

        f = io.StringIO(content)
        first_line = f.readline().upper()
        f.seek(0)

        has_header = "TABLE_NAME" in first_line or "COLUMN_NAME" in first_line
        has_schema_col = "TABLE_SCHEMA" in first_line

        if has_header:
            reader = csv.DictReader(f)
        else:
            # 無標頭：以逗號數量判斷是否含 schema 欄
            col_count = len(first_line.rstrip('\n').split(','))
            if col_count >= 4:
                reader = csv.DictReader(
                    f, fieldnames=['table_schema', 'table_name', 'column_name', 'data_type'])
                has_schema_col = True
            else:
                reader = csv.DictReader(
                    f, fieldnames=['table_name', 'column_name', 'data_type'])

        for row in reader:
            if not row.get('table_name') or not row.get('column_name'):
                continue

            t_name = row['table_name'].lstrip('\ufeff').strip().upper()
            c_name = row['column_name'].strip().upper()
            d_type = (row.get('data_type') or "UNKNOWN").strip().upper()

            schema = (row.get('table_schema') or '').lstrip('\ufeff').strip().upper()
            key = f"{schema}.{t_name}" if schema else t_name

            if key not in self.tables:
                self.tables[key] = {}
            self.tables[key][c_name] = d_type

    def _resolve_key(self, name: str) -> str:
        """將 table_name（可含或不含 schema prefix）解析為 self.tables 中的實際 key。

        解析順序：
        1. 精確比對（SCHEMA.TABLE 或 TABLE 直接命中）
        2. SCHEMA.TABLE → TABLE：registry 僅有 3-col 舊格式時的降級
        3. TABLE → SCHEMA.TABLE：registry 為 4-col 格式但 SQL 未帶 schema，
           僅在該 table name 全域唯一（單一 schema）時才 fallback；
           多個 schema 有同名表格時回傳原值（查不到 = 呼叫端得到空結果）。
        """
        k = name.upper()
        if k in self.tables:
            return k
        if '.' in k:
            # SCHEMA.TABLE → try TABLE (3-col registry fallback)
            short = k.split('.')[-1]
            if short in self.tables:
                return short
        else:
            # TABLE → try any SCHEMA.TABLE (4-col registry, unqualified SQL)
            matches = [key for key in self.tables if key.endswith(f'.{k}')]
            if len(matches) == 1:
                return matches[0]
        return k

    def has_table(self, table_name):
        return self._resolve_key(table_name) in self.tables

    def get_columns(self, table_name):
        return list(self.tables.get(self._resolve_key(table_name), {}).keys())

    def has_column(self, table_name, column_name):
        t_meta = self.tables.get(self._resolve_key(table_name), {})
        return column_name.upper() in t_meta

    def get_column_type(self, table_name, column_name):
        """取得特定欄位的定義類型"""
        t_meta = self.tables.get(self._resolve_key(table_name), {})
        return t_meta.get(column_name.upper(), "UNKNOWN")

    def get_column_count(self, table_name):
        return len(self.tables.get(self._resolve_key(table_name), {}))

    # --- 2. 函數類型管理 ---

    def register_function(self, name, func_type, min_args=1, max_args=1, expected_types=None, return_type="UNKNOWN"):
        name_up = name.upper()
        self.functions[name_up] = FunctionMetadata(
            name_up, func_type, min_args, max_args, expected_types, return_type
        )

    def has_function(self, name):
        return name.upper() in self.functions

    def get_function(self, name):
        return self.functions.get(name.upper())

    def is_aggregate(self, name):
        meta = self.get_function(name)
        return meta and meta.func_type == "AGGREGATE"

    def is_restricted(self, name):
        return name.upper() in self.restricted_functions