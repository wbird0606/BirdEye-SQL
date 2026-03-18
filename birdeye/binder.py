from birdeye.parser import SelectStatement, IdentifierNode
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Token, TokenType

# birdeye/binder.py

class SemanticError(Exception):
    """當 SQL 語意違反資料庫結構或作用域規則時拋出"""
    pass


class Binder:
    def __init__(self, registry):
        self.registry = registry

    def bind(self, stmt):
        from birdeye.parser import IdentifierNode
        table_name = stmt.table.name
        
        if not self.registry.has_table(table_name):
            raise SemanticError(f"Table '{table_name}' not found")

        # 決定唯一合法限定符
        expected_qualifier = stmt.table_alias if stmt.table_alias else table_name

        # --- 【修復 星號展開邏輯】 ---
        
        # 1. 處理全域星號 SELECT *
        if stmt.is_select_star:
            all_cols = self.registry.get_columns_for_table(table_name)
            # 展開並加入 columns 清單
            for col in all_cols:
                stmt.columns.append(IdentifierNode(name=col, token=None, qualifiers=[expected_qualifier]))

        # 2. 處理限定星號 SELECT Table.* 或 Alias.*
        for prefix in stmt.star_prefixes:
            # 驗證前綴是否為合法的表名或別名
            if prefix.upper() not in [table_name.upper(), (stmt.table_alias or "").upper()]:
                raise SemanticError(f"Unknown table prefix '{prefix}' in star expansion")
            
            # 若使用了原名但有別名，根據 Issue #19 應報警
            if stmt.table_alias and prefix.upper() == table_name.upper():
                raise SemanticError(f"Original table name '{table_name}' cannot be used for star expansion when alias '{stmt.table_alias}' is defined")

            all_cols = self.registry.get_columns_for_table(table_name)
            for col in all_cols:
                stmt.columns.append(IdentifierNode(name=col, token=None, qualifiers=[expected_qualifier]))

        # 3. 驗證現有欄位與作用域
        for col in stmt.columns:
            if col.qualifiers:
                actual_qualifier = col.qualifiers[-1]
                if stmt.table_alias and actual_qualifier.upper() == table_name.upper():
                    raise SemanticError(f"Original table name '{table_name}' cannot be used when alias '{stmt.table_alias}' is defined")
                
                if actual_qualifier.upper() not in [table_name.upper(), (stmt.table_alias or "").upper()]:
                    raise SemanticError(f"Unknown qualifier '{actual_qualifier}' for column '{col.name}'")

            if not self.registry.has_column(table_name, col.name):
                raise SemanticError(f"Column '{col.name}' not found in '{table_name}'")

        return stmt