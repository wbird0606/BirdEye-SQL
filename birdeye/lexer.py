from enum import Enum, auto

class TokenType(Enum):
    # Keywords (SQL 關鍵字)
    KEYWORD_SELECT = auto()
    KEYWORD_FROM = auto()
    KEYWORD_AS = auto()
    KEYWORD_WHERE = auto()
    KEYWORD_UPDATE = auto()
    KEYWORD_SET = auto()
    KEYWORD_DELETE = auto()
    KEYWORD_INSERT = auto()
    KEYWORD_INTO = auto()
    KEYWORD_VALUES = auto()
    KEYWORD_JOIN = auto()
    KEYWORD_INNER = auto()
    KEYWORD_LEFT = auto()
    KEYWORD_RIGHT = auto()
    KEYWORD_ON = auto()
    KEYWORD_AND = auto()
    KEYWORD_OR = auto()
    
    # Identifiers & Literals (標識符與常量)
    IDENTIFIER = auto()
    STRING_LITERAL = auto()
    NUMERIC_LITERAL = auto()
    
    # Symbols (符號)
    SYMBOL_ASTERISK = auto()   # *
    SYMBOL_COMMA = auto()      # ,
    SYMBOL_DOT = auto()        # .
    SYMBOL_EQUAL = auto()      # =
    SYMBOL_PLUS = auto()       # +
    SYMBOL_LPAREN = auto()     # (
    SYMBOL_RPAREN = auto()     # )
    SYMBOL_SEMICOLON = auto()  # ; 💡 新增：用於攔截 SQL 注入語句
    
    # Meta
    EOF = auto()

class Token:
    def __init__(self, type, value, start, end):
        self.type = type
        self.value = value   # 儲存處理後的值 (如去掉引號或中括號的文字)
        self.start = start
        self.end = end

    def __repr__(self):
        return f"Token({self.type}, {repr(self.value)}, {self.start}, {self.end})"

class Lexer:
    """
    詞法分析器：將 SQL 字串轉換為 Token 序列。
    支援 ZTA 審計所需的註解過濾、多重語句識別與括號完整性檢查。
    """
    def __init__(self, source):
        self.source = source
        self.tokens = []
        self.pos = 0
        self._bracket_stack = [] # 用於追蹤 ( 與 [ 的平衡狀態

    def _peek(self, offset=0):
        if self.pos + offset >= len(self.source):
            return None
        return self.source[self.pos + offset]

    def _advance(self):
        char = self.source[self.pos]
        self.pos += 1
        return char

    def tokenize(self):
        keywords = {
            "SELECT": TokenType.KEYWORD_SELECT,
            "FROM": TokenType.KEYWORD_FROM,
            "AS": TokenType.KEYWORD_AS,
            "WHERE": TokenType.KEYWORD_WHERE,
            "UPDATE": TokenType.KEYWORD_UPDATE,
            "SET": TokenType.KEYWORD_SET,
            "DELETE": TokenType.KEYWORD_DELETE,
            "INSERT": TokenType.KEYWORD_INSERT,
            "INTO": TokenType.KEYWORD_INTO,
            "VALUES": TokenType.KEYWORD_VALUES,
            "JOIN": TokenType.KEYWORD_JOIN,
            "INNER": TokenType.KEYWORD_INNER,
            "LEFT": TokenType.KEYWORD_LEFT,
            "RIGHT": TokenType.KEYWORD_RIGHT,
            "ON": TokenType.KEYWORD_ON,
            "AND": TokenType.KEYWORD_AND,
            "OR": TokenType.KEYWORD_OR,
        }

        while self.pos < len(self.source):
            char = self._peek()

            # 1. 跳過空白
            if char.isspace():
                self._advance()
                continue

            # 2. 處理註解 (ZTA 審計：移除無語義干擾)
            if char == '-' and self._peek(1) == '-':
                self._advance(); self._advance()
                while self._peek() and self._peek() != '\n':
                    self._advance()
                continue
            
            if char == '/' and self._peek(1) == '*':
                self._advance(); self._advance()
                closed = False
                while self._peek():
                    if self._peek() == '*' and self._peek(1) == '/':
                        self._advance(); self._advance()
                        closed = True
                        break
                    self._advance()
                if not closed:
                    raise ValueError("Unclosed nested block comment")
                continue

            # 3. 處理標識符與關鍵字
            if char.isalpha() or char == '_':
                start = self.pos
                while self._peek() and (self._peek().isalnum() or self._peek() == '_'):
                    self._advance()
                text = self.source[start:self.pos]
                token_type = keywords.get(text.upper(), TokenType.IDENTIFIER)
                self.tokens.append(Token(token_type, text, start, self.pos))
                continue

            # 4. 處理數字常量 (含浮點數)
            if char.isdigit():
                start = self.pos
                while self._peek() and self._peek().isdigit():
                    self._advance()
                if self._peek() == '.' and self._peek(1) and self._peek(1).isdigit():
                    self._advance()
                    while self._peek() and self._peek().isdigit():
                        self._advance()
                self.tokens.append(Token(TokenType.NUMERIC_LITERAL, self.source[start:self.pos], start, self.pos))
                continue

            # 5. 處理字串常量
            if char == "'":
                start = self.pos
                self._advance()
                while self._peek() and self._peek() != "'":
                    self._advance()
                if not self._peek():
                    raise ValueError("Unclosed string literal")
                self._advance()
                # 儲存包含引號的原始文字
                text = self.source[start:self.pos]
                self.tokens.append(Token(TokenType.STRING_LITERAL, text, start, self.pos))
                continue

            # 6. 處理 MSSQL 中括號標識符 (如 [First Name])
            if char == '[':
                start = self.pos
                self._advance()
                self._bracket_stack.append('[')
                while self._peek() and self._peek() != ']':
                    self._advance()
                if not self._peek():
                    raise ValueError("Unclosed bracket")
                self._advance()
                self._bracket_stack.pop()
                # 💡 核心修復：儲存去除括號後的純文字，解決 USERS != [USERS] 問題
                inner_text = self.source[start+1:self.pos-1]
                self.tokens.append(Token(TokenType.IDENTIFIER, inner_text, start, self.pos))
                continue

            # 7. 處理單一符號與括號平衡
            if char == '*':
                self.tokens.append(Token(TokenType.SYMBOL_ASTERISK, "*", self.pos, self.pos + 1)); self._advance()
            elif char == ',':
                self.tokens.append(Token(TokenType.SYMBOL_COMMA, ",", self.pos, self.pos + 1)); self._advance()
            elif char == '.':
                self.tokens.append(Token(TokenType.SYMBOL_DOT, ".", self.pos, self.pos + 1)); self._advance()
            elif char == '=':
                self.tokens.append(Token(TokenType.SYMBOL_EQUAL, "=", self.pos, self.pos + 1)); self._advance()
            elif char == '+':
                self.tokens.append(Token(TokenType.SYMBOL_PLUS, "+", self.pos, self.pos + 1)); self._advance()
            elif char == ';':
                # 💡 核心修復：正式識別分號以支援安全注入檢查
                self.tokens.append(Token(TokenType.SYMBOL_SEMICOLON, ";", self.pos, self.pos + 1)); self._advance()
            elif char == '(':
                self.tokens.append(Token(TokenType.SYMBOL_LPAREN, "(", self.pos, self.pos + 1))
                self._bracket_stack.append('(')
                self._advance()
            elif char == ')':
                if self._bracket_stack and self._bracket_stack[-1] == '(':
                    self._bracket_stack.pop()
                self.tokens.append(Token(TokenType.SYMBOL_RPAREN, ")", self.pos, self.pos + 1))
                self._advance()
            else:
                # 跳過未知字元 (如 \r)
                self._advance()

        # 8. 最終安全性校驗：檢查是否有未閉合的括號
        if self._bracket_stack:
            raise ValueError("Unclosed bracket")

        self.tokens.append(Token(TokenType.EOF, "", self.pos, self.pos))
        return self.tokens