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
        # --- 聚合函數 ---
        self.register_function("SUM", "AGGREGATE", 1, 1, ["INT"], "INT")
        self.register_function("COUNT", "AGGREGATE", 0, 1, ["ANY"], "INT")
        self.register_function("AVG", "AGGREGATE", 1, 1, ["INT"], "INT")
        
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

    # --- 1. 資料表與欄位類型管理 ---

    def load_from_csv(self, csv_file_obj):
        """載入表格定義，包含 data_type 欄位"""
        reader = csv.DictReader(csv_file_obj)
        for row in reader:
            t_name = row['table_name'].upper()
            c_name = row['column_name'].upper()
            d_type = row['data_type'].upper()
            
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