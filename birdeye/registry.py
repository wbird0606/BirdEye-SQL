import csv

class FunctionMetadata:
    """
    💡 Issue #34: 函數元數據。
    儲存函數類型與參數數量限制，作為 Binder 執行 ZTA 安全校驗的依據。
    """
    def __init__(self, name, func_type, min_args=1, max_args=1):
        self.name = name.upper()
        self.func_type = func_type.upper()  # 'SCALAR' 或 'AGGREGATE'
        self.min_args = min_args
        self.max_args = max_args

class MetadataRegistry:
    """
    元數據註冊表：管理資料表結構與 SQL 函數定義。
    v1.7.1: 整合 EXISTS 特殊函數定義，修復相關子查詢語意報錯。
    """
    def __init__(self):
        # 表格元數據: { TABLE_NAME: { COL_NAME: DATA_TYPE } }
        self.tables = {}
        
        # 💡 函數註冊表: { FUNC_NAME: FunctionMetadata }
        self.functions = {}
        
        # 🛡️ ZTA 限制函數黑名單 (預防 SQL 注入後的高風險系統調用)
        self.restricted_functions = {
            "OPENROWSET", "OPENDATASOURCE", "OPENXML", 
            "IS_SRVROLEMEMBER", "HAS_PERMS_BY_NAME"
        }
        
        # 初始化預設內建函數
        self._setup_builtins()

    def _setup_builtins(self):
        """預先註冊常用的 MSSQL 內建函數"""
        
        # --- 1. 聚合函數 (Aggregate) ---
        self.register_function("SUM", "AGGREGATE", 1, 1)
        self.register_function("COUNT", "AGGREGATE", 0, 1) # 支援 COUNT(*) 與 COUNT(col)
        self.register_function("AVG", "AGGREGATE", 1, 1)
        self.register_function("MIN", "AGGREGATE", 1, 1)
        self.register_function("MAX", "AGGREGATE", 1, 1)
        
        # --- 2. 標量函數 (Scalar) - 字串處理 ---
        self.register_function("LEN", "SCALAR", 1, 1)
        self.register_function("UPPER", "SCALAR", 1, 1)
        self.register_function("LOWER", "SCALAR", 1, 1)
        self.register_function("SUBSTRING", "SCALAR", 3, 3)
        self.register_function("TRIM", "SCALAR", 1, 1)
        
        # --- 3. 標量函數 (Scalar) - 日期處理 ---
        self.register_function("GETDATE", "SCALAR", 0, 0)
        self.register_function("DATEPART", "SCALAR", 2, 2)
        self.register_function("DATEDIFF", "SCALAR", 3, 3)

        # --- 4. 💡 特殊結構化函數 ---
        # EXISTS 在 Parser 中被包裝為 FunctionCall，參數是子查詢
        self.register_function("EXISTS", "SCALAR", 1, 1)

    # --- 1. 資料表元數據管理 ---

    def load_from_csv(self, csv_file_obj):
        """從 CSV 檔案載入表格定義 (格式: table_name,column_name,data_type)"""
        reader = csv.DictReader(csv_file_obj)
        for row in reader:
            t_name = row['table_name'].upper()
            c_name = row['column_name'].upper()
            d_type = row['data_type'].upper()
            
            if t_name not in self.tables:
                self.tables[t_name] = {}
            self.tables[t_name][c_name] = d_type

    def has_table(self, table_name):
        return table_name.upper() in self.tables

    def get_columns(self, table_name):
        return list(self.tables.get(table_name.upper(), {}).keys())

    def has_column(self, table_name, column_name):
        t_meta = self.tables.get(table_name.upper(), {})
        return column_name.upper() in t_meta

    def get_column_count(self, table_name):
        return len(self.tables.get(table_name.upper(), {}))

    # --- 2. 函數註冊與查詢介面 ---

    def register_function(self, name, func_type, min_args=1, max_args=1):
        """註冊新函數定義"""
        name_up = name.upper()
        self.functions[name_up] = FunctionMetadata(name_up, func_type, min_args, max_args)

    def has_function(self, name):
        """檢查函數是否存在於註冊表中"""
        return name.upper() in self.functions

    def get_function(self, name):
        """取得函數元數據"""
        return self.functions.get(name.upper())

    def is_aggregate(self, name):
        """判斷是否為聚合函數 (用於執行 ZTA 嚴格分組政策)"""
        meta = self.get_function(name)
        return meta and meta.func_type == "AGGREGATE"

    def is_restricted(self, name):
        """🛡️ ZTA 核心：檢查是否為黑名單受限函數"""
        return name.upper() in self.restricted_functions