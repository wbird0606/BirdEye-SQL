from dataclasses import dataclass, field
from typing import List, Optional
from birdeye.lexer import Token, TokenType

@dataclass
class IdentifierNode:
    """SQL 標識符節點，支援多層級限定符與別名"""
    name: str
    token: Token
    qualifiers: List[str] = field(default_factory=list)
    alias: Optional[str] = None

    @property
    def qualifier(self) -> str:
        return ".".join(self.qualifiers)

@dataclass
class SelectStatement:
    """SELECT 語句 AST 根節點"""
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

    def _peek(self): 
        return self.tokens[self.current] if self.current < len(self.tokens) else None

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

    def _get_text(self, t):
        return self.source_code[t.start:t.end]

    def parse(self):
        stmt = self._parse_select()
        if self._peek() and self._peek().type != TokenType.EOF:
            raise SyntaxError(f"Unexpected token: {self._get_text(self._peek())}")
        return stmt

    def _parse_select(self):
        stmt = SelectStatement()
        self._consume(TokenType.KEYWORD_SELECT, "Expected SELECT")
        
        while True:
            column_node = None
            if self._match(TokenType.SYMBOL_ASTERISK):
                stmt.is_select_star = True
            elif self._peek() and self._peek().type in [TokenType.STRING_LITERAL, TokenType.NUMERIC_LITERAL]:
                token = self._advance()
                text = self._get_text(token).strip("'")
                column_node = IdentifierNode(name=text, token=token)
                stmt.columns.append(column_node)
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

            self._match(TokenType.KEYWORD_AS)
            alias_tok = self._match(TokenType.IDENTIFIER)
            if alias_tok and column_node:
                column_node.alias = self._get_text(alias_tok)
            
            if not self._match(TokenType.SYMBOL_COMMA): break
            
        self._consume(TokenType.KEYWORD_FROM, "Expected FROM")
        table_parts = [self._parse_identifier_segment()]
        while self._match(TokenType.SYMBOL_DOT):
            table_parts.append(self._parse_identifier_segment())
        
        stmt.table = table_parts[-1]
        stmt.table.qualifiers = [p.name for p in table_parts[:-1]]
        
        self._match(TokenType.KEYWORD_AS)
        alias_tok = self._match(TokenType.IDENTIFIER)
        if alias_tok: stmt.table_alias = self._get_text(alias_tok)
        return stmt

    def _parse_identifier_segment(self) -> IdentifierNode:
        """解析單一識別符片段，支援轉義還原 (Issue #22)"""
        if self._match(TokenType.SYMBOL_BRACKET_L):
            token = self._consume(TokenType.IDENTIFIER, "Expected ID inside []")
            self._consume(TokenType.SYMBOL_BRACKET_R, "Expected ]")
            # 重要：將 ]] 還原為 ]
            name = self._get_text(token).replace("]]", "]")
        else:
            token = self._consume(TokenType.IDENTIFIER, "Expected identifier")
            name = self._get_text(token)
        
        return IdentifierNode(name=name, token=token)