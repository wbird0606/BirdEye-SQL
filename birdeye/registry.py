import csv

class MetadataRegistry:
    """
    元數據註冊表：負責加載並管理數據庫表結構資訊。
    支援 ZTA 語意分析所需的欄位查找與數量校驗。
    """
    def __init__(self):
        # 結構: { "TABLE_NAME": { "COLUMN_NAME": "DATA_TYPE" } }
        self.tables = {}

    def load_from_csv(self, file_obj):
        """
        從 CSV 檔案加載元數據，支援 io.StringIO (用於測試) 或實際檔案。
        表格與欄位名稱統一存儲為大寫，以實現大小寫不敏感的查找。
        """
        reader = csv.DictReader(file_obj)
        for row in reader:
            table_name = row['table_name'].upper()
            column_name = row['column_name'].upper()
            data_type = row['data_type']
            
            if table_name not in self.tables:
                self.tables[table_name] = {}
            
            self.tables[table_name][column_name] = data_type

    def has_table(self, table_name: str) -> bool:
        """檢查特定表格是否存在於註冊表中。"""
        return table_name.upper() in self.tables

    def has_column(self, table_name: str, column_name: str) -> bool:
        """檢查特定表格中是否包含該欄位。"""
        t = table_name.upper()
        c = column_name.upper()
        return t in self.tables and c in self.tables[t]

    def get_columns(self, table_name: str) -> list:
        """
        回傳該表所有欄位的名稱清單。
        💡 修復重點：用於 SELECT * 的星號展開邏輯。
        """
        t = table_name.upper()
        if t in self.tables:
            return list(self.tables[t].keys())
        return []

    def get_column_count(self, table_name: str) -> int:
        """
        回傳該表的總欄位數。
        💡 修復重點：用於 INSERT VALUES 數量的 ZTA 對齊檢查。
        """
        return len(self.get_columns(table_name))