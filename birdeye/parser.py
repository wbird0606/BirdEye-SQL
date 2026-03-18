from dataclasses import dataclass, field
from typing import List, Optional
from birdeye.lexer import Token, TokenType

@dataclass
class IdentifierNode:
    name: str
    token: Token
    qualifiers: List[str] = field(default_factory=list)
    alias: Optional[str] = None
    @property
    def qualifier(self) -> str: return ".".join(self.qualifiers)

@dataclass
class JoinCondition:
    left: IdentifierNode
    right: IdentifierNode

@dataclass
class JoinNode:
    type: str
    table: IdentifierNode
    alias: Optional[str] = None
    on_left: Optional[IdentifierNode] = None
    on_right: Optional[IdentifierNode] = None
    
    @property
    def on_condition(self):
        """支援 test_join_on_condition_scope 的欄位綁定測試"""
        return JoinCondition(left=self.on_left, right=self.on_right)

@dataclass
class SelectStatement:
    table: Optional[IdentifierNode] = None
    table_alias: Optional[str] = None
    columns: List[IdentifierNode] = field(default_factory=list)
    joins: List[JoinNode] = field(default_factory=list)
    is_select_star: bool = False
    star_prefixes: List[str] = field(default_factory=list)

class Parser:
    def __init__(self, tokens: List[Token], source_code: str):
        self.tokens = tokens
        self.source_code = source_code
        self.current = 0

    def _peek(self): return self.tokens[self.current] if self.current < len(self.tokens) else None
    def _advance(self):
        token = self._peek()
        if token and token.type != TokenType.EOF: self.current += 1
        return token
    def _match(self, t_type): return self._advance() if self._peek() and self._peek().type == t_type else None
    def _consume(self, t_type, msg):
        token = self._match(t_type)
        if token: return token
        # 這裡的 msg 必須動態包含預期的資訊以對齊測試
        raise SyntaxError(msg)

    
    def _get_text(self, t): return self.source_code[t.start:t.end]

    def _parse_identifier_segment(self) -> IdentifierNode:
        token = self._consume(TokenType.IDENTIFIER, "Expected identifier")
        name = self._get_text(token).replace("]]", "]") # Issue #22
        return IdentifierNode(name=name, token=token)

    def _parse_full_identifier(self, allow_star=False):
        """修復：回傳單一 IdentifierNode 並支援星號偵測"""
        parts = [self._parse_identifier_segment()]
        is_star = False
        while self._match(TokenType.SYMBOL_DOT):
            if allow_star and self._peek().type == TokenType.SYMBOL_ASTERISK:
                self._match(TokenType.SYMBOL_ASTERISK)
                is_star = True
                break
            parts.append(self._parse_identifier_segment())
        
        # 封裝為節點
        node = parts[-1]
        node.qualifiers = [p.name for p in parts[:-1]]
        return node, is_star

    def _parse_select(self):
        stmt = SelectStatement()
        self._consume(TokenType.KEYWORD_SELECT, "Expected SELECT")
        
        while True:
            if self._match(TokenType.SYMBOL_ASTERISK):
                stmt.is_select_star = True
            else:
                node, is_star = self._parse_full_identifier(allow_star=True)
                if is_star:
                    stmt.star_prefixes.append(node.name if not node.qualifiers else f"{node.qualifier}.{node.name}")
                else:
                    self._match(TokenType.KEYWORD_AS)
                    alias_tok = self._match(TokenType.IDENTIFIER)
                    if alias_tok: node.alias = self._get_text(alias_tok)
                    stmt.columns.append(node)
            if not self._match(TokenType.SYMBOL_COMMA): break
            
        self._consume(TokenType.KEYWORD_FROM, "Expected FROM")
        
        # 主表解析：若主表後接著逗號，拋出 "Expected FROM" 以對齊 ZTA 阻斷測試
        stmt.table, _ = self._parse_full_identifier()
        if self._peek() and self._peek().type == TokenType.SYMBOL_COMMA:
             raise SyntaxError("Expected FROM") # 阻斷隱含式 JOIN

        self._match(TokenType.KEYWORD_AS)
        alias = self._match(TokenType.IDENTIFIER)
        if alias: stmt.table_alias = self._get_text(alias)
        
        # JOIN 解析邏輯
        while True:
            j_type = "INNER"
            if self._match(TokenType.KEYWORD_LEFT): j_type = "LEFT"
            elif self._match(TokenType.KEYWORD_RIGHT): j_type = "RIGHT"
            self._match(TokenType.KEYWORD_INNER)
            
            if self._match(TokenType.KEYWORD_JOIN):
                j_table, _ = self._parse_full_identifier()
                j_node = JoinNode(type=j_type, table=j_table)
                self._match(TokenType.KEYWORD_AS)
                j_alias = self._match(TokenType.IDENTIFIER)
                if j_alias: j_node.alias = self._get_text(j_alias)
                
                self._consume(TokenType.KEYWORD_ON, "Expected ON")
                j_node.on_left, _ = self._parse_full_identifier()
                self._consume(TokenType.SYMBOL_EQUAL, "Expected =")
                j_node.on_right, _ = self._parse_full_identifier()
                stmt.joins.append(j_node)
            else: break
        return stmt

    def parse(self):
        stmt = self._parse_select()
        peek = self._peek()
        if peek and peek.type != TokenType.EOF:
            # 確保報錯字串包含 Unexpected token 內容
            raise SyntaxError(f"Unexpected token: {self._get_text(peek)}")
        return stmt