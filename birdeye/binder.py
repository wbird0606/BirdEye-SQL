from birdeye.parser import SelectStatement, IdentifierNode
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Token, TokenType

class SemanticError(Exception): pass

class Binder:
    def __init__(self, registry: MetadataRegistry):
        self.registry = registry

    def bind(self, stmt: SelectStatement):
        """
        執行語意綁定：驗證元數據並處理別名與星號展開 
        """
        if not stmt.table:
            raise SemanticError("No table specified in SELECT statement")

        table_name = stmt.table.name
        alias = stmt.table_alias
        t_name_lower = table_name.lower()

        # 1. 驗證資料表是否存在於 Registry [cite: 4]
        if not self.registry.has_table(table_name):
            raise SemanticError(f"Table '{table_name}' not found")

        # 2. 處理星號展開 (包含 * 和 Schema.Table.*) 
        if stmt.is_select_star or stmt.star_prefixes:
            valid_prefixes = [t_name_lower, (alias or "").lower()]
            
            # 檢查 Table.* 中的前綴是否正確匹配資料表或別名
            for prefix in stmt.star_prefixes:
                # 取得前綴的最後一個節點 (例如 dbo.Users 取得 Users)
                last_part = prefix.split('.')[-1].lower()
                if last_part not in valid_prefixes:
                    raise SemanticError(f"Unknown prefix '{prefix}' in star expansion")
            
            # 從 Registry 抓出該表的真實欄位清單
            all_cols = self.registry._catalog[t_name_lower].keys()
            for col_name in all_cols:
                # 建立新的標識符節點，保留 Registry 中的原始命名
                stmt.columns.append(IdentifierNode(name=col_name, token=Token(TokenType.IDENTIFIER, -1, -1)))
            
            # 標記為已展開，避免重複處理
            stmt.is_select_star = True 

        # 3. 驗證明確指定的欄位與其限定符 (Qualifiers) 
        for col in stmt.columns:
            if col.qualifiers:
                # 取得直接前綴 (例如 dbo.Users.UserID 的 Users)
                # 這是為了處理 MSSQL 的多層級路徑歸屬 [cite: 4]
                immediate_prefix = col.qualifiers[-1].lower()
                if immediate_prefix not in [t_name_lower, (alias or "").lower()]:
                    raise SemanticError(f"Invalid qualifier '{'.'.join(col.qualifiers)}' for column '{col.name}'")
            
            # 驗證欄位是否存在於該資料表中 [cite: 4]
            if not self.registry.has_column(table_name, col.name):
                raise SemanticError(f"Column '{col.name}' not found in '{table_name}'")

        return stmt