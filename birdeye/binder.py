# birdeye/binder.py
from birdeye.parser import ASTNode, SelectStatement, IdentifierNode
from birdeye.registry import MetadataRegistry
from birdeye.lexer import Token, TokenType

class SemanticError(Exception):
    """語意錯誤，用於攔截不存在的表或欄位"""
    pass

class Binder:
    def __init__(self, registry: MetadataRegistry):
        self.registry = registry

    def bind(self, ast: ASTNode) -> ASTNode:
        """語意綁定進入點"""
        if isinstance(ast, SelectStatement):
            return self._bind_select(ast)
        raise NotImplementedError("目前只支援 SELECT 語句的綁定")

    def _bind_select(self, stmt: SelectStatement) -> SelectStatement:
        # 1. 驗證資料表是否存在
        if not stmt.table:
            raise SemanticError("Missing table in SELECT statement")
            
        table_name = stmt.table.name
        if not self.registry.has_table(table_name):
            raise SemanticError(f"Table '{table_name}' does not exist")

        # 2. 處理星號展開 (Star Expansion)
        if stmt.is_select_star:
            t_name_lower = table_name.lower()
            # 存取我們在 Registry 建好的 O(1) 字典結構，抓出所有合法欄位
            all_columns = self.registry._catalog.get(t_name_lower, {}).keys()
            
            # 清空原有的 columns 並填入展開後的真實欄位
            stmt.columns = []
            for col_name in all_columns:
                # 產生虛擬的 Token (index 為 -1 代表是 Binder 自動展開的，非原始 SQL)
                virtual_token = Token(TokenType.IDENTIFIER, -1, -1)
                stmt.columns.append(IdentifierNode(name=col_name, token=virtual_token))
            
        # 3. 欄位存在性校驗 (針對明確指定的欄位)
        else:
            for col_node in stmt.columns:
                col_name = col_node.name
                if not self.registry.has_column(table_name, col_name):
                    raise SemanticError(f"Column '{col_name}' does not exist in table '{table_name}'")

        return stmt