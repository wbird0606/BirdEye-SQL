# birdeye/parser.py
from dataclasses import dataclass, field
from typing import List, Optional
from birdeye.lexer import Token, TokenType

@dataclass
class IdentifierNode:
    name: str
    token: Token
    qualifiers: List[str] = field(default_factory=list) # 升級為 List，存儲多層路徑
    @property
    def qualifier(self) -> str:
        """
        向後相容屬性：將多個限定符接合成字串 (e.g., ['dbo', 'Users'] -> 'dbo.Users')
        這樣舊的測試腳本不需要改 code 也能跑通。
        """
        return ".".join(self.qualifiers)

@dataclass
class SelectStatement:
    table: Optional[IdentifierNode] = None
    table_alias: Optional[str] = None
    columns: List[IdentifierNode] = field(default_factory=list)
    is_select_star: bool = False
    star_prefixes: List[str] = field(default_factory=list)

class Parser:
    def __init__(self, tokens: List[Token], source_code: str):
        self.tokens = tokens
        self.source_code = source_code
        self.current = 0
        self.length = len(tokens)

    def _peek(self): return self.tokens[self.current] if self.current < self.length else None
    def _advance(self):
        token = self._peek()
        if token and token.type != TokenType.EOF: self.current += 1
        return token
    def _match(self, t_type):
        if self._peek() and self._peek().type == t_type: return self._advance()
        return None
    def _consume(self, t_type, msg):
        token = self._match(t_type)
        if token: return token
        raise SyntaxError(msg)
    def _get_token_text(self, t): return self.source_code[t.start:t.end]

    def parse(self):
        stmt = self._parse_select()
        if self._peek() and self._peek().type != TokenType.EOF:
            raise SyntaxError(f"Unexpected token: {self._get_token_text(self._peek())}")
        return stmt

    def _parse_select(self):
        stmt = SelectStatement()
        self._consume(TokenType.KEYWORD_SELECT, "Expected SELECT")
        
        while True:
            # 1. 處理單純的 '*'
            if self._match(TokenType.SYMBOL_ASTERISK):
                stmt.is_select_star = True
            else:
                # 2. 處理可能帶有點號的多層路徑 (e.g., dbo.Users.UserID)
                parts = [self._parse_identifier_segment()]
                
                while self._match(TokenType.SYMBOL_DOT):
                    if self._match(TokenType.SYMBOL_ASTERISK):
                        # 處理 Table.* 或 Schema.Table.*
                        prefix = ".".join([p.name for p in parts])
                        stmt.star_prefixes.append(prefix)
                        break
                    parts.append(self._parse_identifier_segment())
                else:
                    # 這是正常的 Column 名稱
                    # 最後一個是欄位名，前面所有都是限定符 (Qualifiers)
                    node = parts[-1]
                    node.qualifiers = [p.name for p in parts[:-1]]
                    stmt.columns.append(node)

            if not self._match(TokenType.SYMBOL_COMMA): break
            
        self._consume(TokenType.KEYWORD_FROM, "Expected FROM")
        
        # 3. 解析 Table 名稱 (同樣支援多層級，如 dbo.Users)
        table_parts = [self._parse_identifier_segment()]
        while self._match(TokenType.SYMBOL_DOT):
            table_parts.append(self._parse_identifier_segment())
        
        stmt.table = table_parts[-1]
        stmt.table.qualifiers = [p.name for p in table_parts[:-1]]
        
        # 4. 解析 AS 與 Alias
        self._match(TokenType.KEYWORD_AS)
        alias_tok = self._match(TokenType.IDENTIFIER)
        if alias_tok: stmt.table_alias = self.source_code[alias_tok.start:alias_tok.end]
        
        return stmt

    def _parse_identifier(self):
        # 支援 [Name] 或 Name 格式 [cite: 9]
        if self._match(TokenType.SYMBOL_BRACKET_L):
            token = self._consume(TokenType.IDENTIFIER, "Expected ID inside []")
            self._consume(TokenType.SYMBOL_BRACKET_R, "Expected ]")
        else:
            token = self._consume(TokenType.IDENTIFIER, "Expected identifier")
        return IdentifierNode(name=self._get_token_text(token), token=token)
    
    def _parse_identifier_segment(self) -> IdentifierNode:
        """解析單一標識符片段，支援 [Name] 或 Name 格式 [cite: 9]"""
        if self._match(TokenType.SYMBOL_BRACKET_L):
            token = self._consume(TokenType.IDENTIFIER, "Expected ID inside []")
            self._consume(TokenType.SYMBOL_BRACKET_R, "Expected ]")
        else:
            token = self._consume(TokenType.IDENTIFIER, "Expected identifier")
        return IdentifierNode(name=self.source_code[token.start:token.end], token=token)