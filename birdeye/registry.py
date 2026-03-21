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
        
        # --- 標量函數: 字串類 (回傳 NVARCHAR 或 INT) ---
        self.register_function("LEN", "SCALAR", 1, 1, ["NVARCHAR"], "INT")
        self.register_function("UPPER", "SCALAR", 1, 1, ["NVARCHAR"], "NVARCHAR")
        self.register_function("LOWER", "SCALAR", 1, 1, ["NVARCHAR"], "NVARCHAR")
        self.register_function("SUBSTRING", "SCALAR", 3, 3, ["NVARCHAR", "INT", "INT"], "NVARCHAR")
        
        # --- 標量函數: 日期類 ---
        self.register_function("GETDATE", "SCALAR", 0, 0, [], "DATETIME")
        self.register_function("DATEDIFF", "SCALAR", 3, 3, ["ANY", "DATETIME", "DATETIME"], "INT")

        # --- 特殊結構 ---
        self.register_function("EXISTS", "SCALAR", 1, 1, ["ANY"], "BIT")

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
        """載入表格定義，包含 data_type 欄位"""
        # 💡 v1.7.6: 支援無標頭 CSV 與數據類型標準化 (TDD Fix)
        import io
        
        # 讀取內容並確保是字串格式
        content = csv_file_obj.read()
        if isinstance(content, bytes):
            content = content.decode('utf-8')
        
        # 使用 StringIO 重新包裝以便重複讀取首行進行偵測
        f = io.StringIO(content)
        first_line = f.readline().upper()
        f.seek(0)
        
        # 判斷是否包含標頭標籤 (TABLE_NAME 或 COLUMN_NAME)
        if "TABLE_NAME" in first_line or "COLUMN_NAME" in first_line:
            reader = csv.DictReader(f)
        else:
            # 針對無標頭 CSV (如 data/output.csv)，手動指定欄位名
            reader = csv.DictReader(f, fieldnames=['table_name', 'column_name', 'data_type'])

        for row in reader:
            # 略過空行或不完整的列
            if not row.get('table_name') or not row.get('column_name'):
                continue
                
            # 🛡️ 處理 BOM 與多餘空格 (TDD Fix for AddressID not found)
            t_name = row['table_name'].lstrip('\ufeff').strip().upper()
            c_name = row['column_name'].strip().upper()
            
            # 💡 保留真實的類型定義 (不再強行轉換 UDT)
            d_type = (row['data_type'] or "UNKNOWN").strip().upper()
            
            if t_name not in self.tables:
                self.tables[t_name] = {}
            # 儲存欄位名對應的數據類型
            self.tables[t_name][c_name] = d_type

    def has_table(self, table_name):
        return table_name.upper() in self.tables

    def get_columns(self, table_name):
        return list(self.tables.get(table_name.upper(), {}).keys())

    def has_column(self, table_name, column_name):
        t_meta = self.tables.get(table_name.upper(), {})
        return column_name.upper() in t_meta

    def get_column_type(self, table_name, column_name):
        """💡 取得特定欄位的定義類型"""
        t_meta = self.tables.get(table_name.upper(), {})
        return t_meta.get(column_name.upper(), "UNKNOWN")

    def get_column_count(self, table_name):
        return len(self.tables.get(table_name.upper(), {}))

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