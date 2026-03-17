# birdeye/registry.py
import csv
from typing import TextIO, Optional

class MetadataRegistry:
    def __init__(self):
        # 核心資料結構: { "table_name_lower": { "column_name_lower": "DATA_TYPE" } }
        # 確保 O(1) 的 table 與 column 雙重查找
        self._catalog = {}

    def load_from_csv(self, file_obj: TextIO) -> None:
        """解析 CSV 並建構 O(1) 查詢樹"""
        reader = csv.DictReader(file_obj)
        for row in reader:
            # 統一轉小寫以支援 Case-insensitive
            t_name = row['table_name'].strip().lower()
            c_name = row['column_name'].strip().lower()
            d_type = row['data_type'].strip().upper() # 型態統一轉大寫方便後續比對

            # 初始化 Table 節點
            if t_name not in self._catalog:
                self._catalog[t_name] = {}
            
            # 註冊 Column 與其 Type
            self._catalog[t_name][c_name] = d_type

    def has_table(self, table_name: str) -> bool:
        """O(1) 檢查資料表是否存在"""
        return table_name.lower() in self._catalog

    def has_column(self, table_name: str, column_name: str) -> bool:
        """O(1) 檢查特定資料表下是否存在該欄位"""
        t_name_lower = table_name.lower()
        if t_name_lower not in self._catalog:
            return False
        return column_name.lower() in self._catalog[t_name_lower]

    def get_column_type(self, table_name: str, column_name: str) -> Optional[str]:
        """O(1) 獲取欄位資料型態"""
        t_name_lower = table_name.lower()
        c_name_lower = column_name.lower()
        
        if self.has_column(table_name, column_name):
            return self._catalog[t_name_lower][c_name_lower]
        return None