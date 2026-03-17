# birdeye/parser.py
from dataclasses import dataclass, field
from typing import List, Optional
from birdeye.lexer import Token, TokenType

# --- AST 節點定義 ---

@dataclass
class ASTNode:
    """語法樹節點的基底類別"""
    pass

@dataclass
class IdentifierNode(ASTNode):
    """代表欄位名稱或資料表名稱"""
    name: str
    token: Token

@dataclass
class SelectStatement(ASTNode):
    """代表一個完整的 SELECT 查詢"""
    table: Optional[IdentifierNode] = None
    columns: List[IdentifierNode] = field(default_factory=list)
    is_select_star: bool = False

# --- 遞迴下降解析器 ---

class Parser:
    def __init__(self, tokens: List[Token], source_code: str):
        self.tokens = tokens
        self.source_code = source_code
        self.current = 0
        self.length = len(tokens)

    # --- 核心游標控制 ---

    def _peek(self) -> Optional[Token]:
        """查看目前的 Token，但不移動游標"""
        if self.current < self.length:
            return self.tokens[self.current]
        return None

    def _advance(self) -> Optional[Token]:
        """讀取目前的 Token，並將游標往前推一格"""
        token = self._peek()
        if token and token.type != TokenType.EOF:
            self.current += 1
        return token

    def _match(self, expected_type: TokenType) -> bool:
        """如果目前的 Token 類型符合預期，就消耗掉它並回傳 True"""
        token = self._peek()
        if token and token.type == expected_type:
            self._advance()
            return True
        return False

    def _consume(self, expected_type: TokenType, error_message: str) -> Token:
        """強制消耗一個預期的 Token，如果類型不對，直接拋出語法錯誤"""
        token = self._peek()
        if token and token.type == expected_type:
            return self._advance()
        raise SyntaxError(error_message)

    def _get_token_text(self, token: Token) -> str:
        """Zero-copy 精神：只有在 AST 節點真正需要字串時，才從原字串切出來"""
        return self.source_code[token.start:token.end]

    # --- 語法解析邏輯 (Recursive Descent) ---

    def parse(self) -> ASTNode:
        """解析的進入點"""
        # 1. 解析主要的 SELECT 語句
        stmt = self._parse_select()
        
        # 2. 🛑 ZTA 終極防禦：確保沒有尾隨的惡意垃圾 (Trailing Garbage)
        # 如果解析完之後，下一個 Token 不是 EOF (代表後面還有東西沒處理到)
        current_token = self._peek()
        if current_token and current_token.type != TokenType.EOF:
            # 直接拔刀，攔截可能的 SQL 注入！
            raise SyntaxError(f"Unexpected tokens after parsing: '{self._get_token_text(current_token)}'. Possible SQL injection detected.")
            
        return stmt

    def _parse_select(self) -> SelectStatement:
        stmt = SelectStatement()

        # 1. 確保開頭是 SELECT
        self._consume(TokenType.KEYWORD_SELECT, "Expected SELECT keyword")

        # 2. 解析欄位或星號 (*)
        if self._match(TokenType.SYMBOL_ASTERISK):
            stmt.is_select_star = True
        else:
            # 至少要有一個欄位
            stmt.columns.append(self._parse_identifier())
            # 如果後面跟著逗號，就繼續解析下一個欄位 (處理如: col1, col2, col3)
            while self._match(TokenType.SYMBOL_COMMA):
                stmt.columns.append(self._parse_identifier())

        # 3. 確保緊接著 FROM 關鍵字
        self._consume(TokenType.KEYWORD_FROM, "Expected FROM keyword")

        # 4. 解析資料表名稱
        stmt.table = self._parse_identifier()

        return stmt

    def _parse_identifier(self) -> IdentifierNode:
        """解析 Identifier (資料表名或欄位名)"""
        token = self._consume(TokenType.IDENTIFIER, "Expected identifier (column or table name)")
        # 在這裡將 Zero-copy 的 Token 轉化為實際的字串名稱，賦予 AST 節點語意
        name = self._get_token_text(token)
        return IdentifierNode(name=name, token=token)