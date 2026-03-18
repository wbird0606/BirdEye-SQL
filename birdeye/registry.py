# birdeye/registry.py
import csv
from typing import TextIO, Optional

# birdeye/registry.py

class MetadataRegistry:
    def __init__(self):
        # 結構：{ table_name.upper(): { column_name.upper(): data_type } }
        self.tables = {}

    def load_from_csv(self, file_handle):
        import csv
        reader = csv.DictReader(file_handle)
        for row in reader:
            t_name = row['table_name'].upper()
            c_name = row['column_name'].upper()
            if t_name not in self.tables:
                self.tables[t_name] = {}
            self.tables[t_name][c_name] = row['data_type']

    def has_table(self, table_name: str) -> bool:
        return table_name.upper() in self.tables

    def has_column(self, table_name: str, column_name: str) -> bool:
        t_name = table_name.upper()
        return t_name in self.tables and column_name.upper() in self.tables[t_name]

    # --- 【修復 AttributeError】新增此方法 ---
    def get_columns_for_table(self, table_name: str) -> list:
        """回傳指定表格的所有原始欄位名稱清單"""
        t_name = table_name.upper()
        if t_name in self.tables:
            return list(self.tables[t_name].keys())
        return []
    def get_column_type(self, table_name: str, column_name: str) -> str:
        """取得特定欄位的資料型態"""
        t_name = table_name.upper()
        c_name = column_name.upper()
        if self.has_column(t_name, c_name):
            return self.tables[t_name][c_name]
        return None