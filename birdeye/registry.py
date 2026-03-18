import csv

class MetadataRegistry:
    def __init__(self):
        self.tables = {}

    def load_from_csv(self, file_handle):
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

    def get_columns_for_table(self, table_name: str) -> list:
        """取得表格欄位清單"""
        t_name = table_name.upper()
        return list(self.tables[t_name].keys()) if t_name in self.tables else []