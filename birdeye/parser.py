from dataclasses import dataclass, field
from typing import List, Optional
from birdeye.lexer import Token, TokenType

@dataclass
class IdentifierNode:
    """
    SQL 標識符節點，支援多層級限定符與別名。
    這是根據計畫書中對於 MSSQL 語法相容性的要求設計的。
    """
    name: str
    token: Token
    qualifiers: List[str] = field(default_factory=list)
    alias: Optional[str] = None # Issue #18: 支援欄位別名

    @property
    def qualifier(self) -> str:
        """
        向後相容屬性：自動將 qualifiers 列表接回點號字串。
        確保 Issue #12 之前的測試腳本無需修改即可執行。
        """
        return ".".join(self.qualifiers)

@dataclass
class SelectStatement:
    """SELECT 語句的抽象語法樹 (AST) 根節點"""
    table: Optional[IdentifierNode] = None
    table_alias: Optional[str] = None
    columns: List[IdentifierNode] = field(default_factory=list)
    is_select_star: bool = False
    star_prefixes: List[str] = field(default_factory=list)

class Parser:
    """
    遞迴下降解析器 (Recursive Descent Parser)。
    實作了針對 MSSQL 語法特性的嚴格校驗邏輯。
    """
    def __init__(self, tokens: List[Token], source_code: str):
        self.tokens = tokens
        self.source_code = source_code
        self.current = 0

    def _peek(self): 
        """查看目前的 Token"""
        return self.tokens[self.current] if self.current < len(self.tokens) else None

    def _advance(self):
        """移動至下一個 Token"""
        token = self._peek()
        if token and token.type != TokenType.EOF:
            self.current += 1
        return token

    def _match(self, t_type):
        """如果類型符合則消費該 Token，否則回傳 None"""
        if self._peek() and self._peek().type == t_type:
            return self._advance()
        return None

    def _consume(self, t_type, msg):
        """強制消費特定類型的 Token，否則拋出語法錯誤"""
        token = self._match(t_type)
        if token:
            return token
        raise SyntaxError(msg)

    def _get_text(self, t):
        """Zero-copy: 根據 Token 索引從原始字串擷取文本"""
        return self.source_code[t.start:t.end]

    def parse(self):
        """執行解析流程並驗證結尾是否為 EOF"""
        stmt = self._parse_select()
        if self._peek() and self._peek().type != TokenType.EOF:
            raise SyntaxError(f"Unexpected token: {self._get_text(self._peek())}")
        return stmt

    def _parse_select(self):
        """
        解析 SELECT 子句核心邏輯。
        已針對 Issue #18 強化常量與別名的處理能力。
        """
        stmt = SelectStatement()
        self._consume(TokenType.KEYWORD_SELECT, "Expected SELECT")
        
        while True:
            column_node = None
            
            # 1. 處理星號 (SELECT *)
            if self._match(TokenType.SYMBOL_ASTERISK):
                stmt.is_select_star = True
            
            # 2. 處理常量 (Issue #18: Literals Support)
            elif self._peek() and self._peek().type in [TokenType.STRING_LITERAL, TokenType.NUMERIC_LITERAL]:
                token = self._advance()
                text = self._get_text(token).strip("'") # 去除單引號
                column_node = IdentifierNode(name=text, token=token)
                stmt.columns.append(column_node)
            
            # 3. 處理標識符 (支援多層級 dbo.Table.Col)
            else:
                parts = [self._parse_identifier_segment()]
                while self._match(TokenType.SYMBOL_DOT):
                    if self._match(TokenType.SYMBOL_ASTERISK):
                        stmt.star_prefixes.append(".".join([p.name for p in parts]))
                        break
                    parts.append(self._parse_identifier_segment())
                else:
                    column_node = parts[-1]
                    column_node.qualifiers = [p.name for p in parts[:-1]]
                    stmt.columns.append(column_node)

            # --- 欄位別名處理 (Column Alias) ---
            # 支援可選的 AS 關鍵字
            self._match(TokenType.KEYWORD_AS)
            alias_tok = self._match(TokenType.IDENTIFIER)
            if alias_tok and column_node:
                column_node.alias = self._get_text(alias_tok)
            
            # 檢查連續逗號或結束條件 (Issue #14)
            if not self._match(TokenType.SYMBOL_COMMA):
                break
            
        self._consume(TokenType.KEYWORD_FROM, "Expected FROM")
        
        # 解析來源資料表 (支援多層級路徑)
        table_parts = [self._parse_identifier_segment()]
        while self._match(TokenType.SYMBOL_DOT):
            table_parts.append(self._parse_identifier_segment())
        
        stmt.table = table_parts[-1]
        stmt.table.qualifiers = [p.name for p in table_parts[:-1]]
        
        # 解析資料表別名 (Table Alias)
        self._match(TokenType.KEYWORD_AS)
        alias_tok = self._match(TokenType.IDENTIFIER)
        if alias_tok:
            stmt.table_alias = self._get_text(alias_tok)
        
        return stmt

    def _parse_identifier_segment(self) -> IdentifierNode:
        """
        解析單一識別符片段。
        支援 MSSQL 的中括號轉義語法。
        """
        if self._match(TokenType.SYMBOL_BRACKET_L):
            token = self._consume(TokenType.IDENTIFIER, "Expected ID inside []")
            self._consume(TokenType.SYMBOL_BRACKET_R, "Expected ]")
        else:
            token = self._consume(TokenType.IDENTIFIER, "Expected identifier")
        
        return IdentifierNode(name=self._get_text(token), token=token)