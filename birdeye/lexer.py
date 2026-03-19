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
    KEYWORD_TOP = auto()        # Issue #30
    KEYWORD_ORDER = auto()      # Issue #30
    KEYWORD_BY = auto()         # Issue #30
    KEYWORD_ASC = auto()        # Issue #30
    KEYWORD_DESC = auto()       # Issue #30
    KEYWORD_GROUP = auto()      # Issue #31
    KEYWORD_HAVING = auto()     # Issue #31
    # 💡 v1.6.4 新增：子查詢關鍵字
    KEYWORD_IN = auto()         
    KEYWORD_EXISTS = auto()     
    
    # Identifiers & Literals
    IDENTIFIER = auto()
    STRING_LITERAL = auto()
    NUMERIC_LITERAL = auto()
    
    # Symbols
    SYMBOL_ASTERISK = auto()   # *
    SYMBOL_COMMA = auto()      # ,
    SYMBOL_DOT = auto()        # .
    SYMBOL_EQUAL = auto()      # =
    SYMBOL_PLUS = auto()       # +
    SYMBOL_LPAREN = auto()     # (
    SYMBOL_RPAREN = auto()     # )
    SYMBOL_SEMICOLON = auto()  # ;
    
    # Comparison Operators (v1.6.3)
    SYMBOL_GT = auto()         # >
    SYMBOL_LT = auto()         # <
    SYMBOL_GE = auto()         # >=
    SYMBOL_LE = auto()         # <=
    SYMBOL_NE = auto()         # != 或 <>
    
    # Meta
    EOF = auto()

class Token:
    def __init__(self, type, value, start, end):
        self.type = type
        self.value = value   
        self.start = start
        self.end = end

    def __repr__(self):
        return f"Token({self.type}, {repr(self.value)}, {self.start}, {self.end})"

class Lexer:
    """
    詞法分析器：將 SQL 字串轉換為 Token 序列。
    v1.6.4: 支援 IN 與 EXISTS 關鍵字，為 Issue #32 子查詢重構打底。
    """
    def __init__(self, source):
        self.source = source
        self.tokens = []
        self.pos = 0
        self._bracket_stack = [] 

    def _peek(self, offset=0):
        if self.pos + offset >= len(self.source):
            return None
        return self.source[self.pos + offset]

    def _advance(self):
        char = self.source[self.pos]
        self.pos += 1
        return char

    def tokenize(self):
        # 💡 v1.6.4: 更新關鍵字清單
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
            "TOP": TokenType.KEYWORD_TOP,
            "ORDER": TokenType.KEYWORD_ORDER,
            "BY": TokenType.KEYWORD_BY,
            "ASC": TokenType.KEYWORD_ASC,
            "DESC": TokenType.KEYWORD_DESC,
            "GROUP": TokenType.KEYWORD_GROUP,
            "HAVING": TokenType.KEYWORD_HAVING,
            "IN": TokenType.KEYWORD_IN,
            "EXISTS": TokenType.KEYWORD_EXISTS,
        }

        while self.pos < len(self.source):
            char = self._peek()

            if char.isspace():
                self._advance()
                continue

            # 1. 處理註解 (維持 ZTA 審計純淨度)
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

            # 2. 處理標識符與關鍵字
            if char.isalpha() or char == '_':
                start = self.pos
                while self._peek() and (self._peek().isalnum() or self._peek() == '_'):
                    self._advance()
                text = self.source[start:self.pos]
                token_type = keywords.get(text.upper(), TokenType.IDENTIFIER)
                self.tokens.append(Token(token_type, text, start, self.pos))
                continue

            # 3. 處理數字
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

            # 4. 處理字串
            if char == "'":
                start = self.pos
                self._advance()
                while self._peek() and self._peek() != "'":
                    self._advance()
                if not self._peek():
                    raise ValueError("Unclosed string literal")
                self._advance()
                text = self.source[start:self.pos]
                self.tokens.append(Token(TokenType.STRING_LITERAL, text, start, self.pos))
                continue

            # 5. 處理 MSSQL 中括號 (標識符淨化)
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
                inner_text = self.source[start+1:self.pos-1]
                self.tokens.append(Token(TokenType.IDENTIFIER, inner_text, start, self.pos))
                continue

            # 6. 處理比較運算子 (v1.6.3 實作)
            if char == '=':
                self.tokens.append(Token(TokenType.SYMBOL_EQUAL, "=", self.pos, self.pos + 1)); self._advance()
            elif char == '>':
                if self._peek(1) == '=':
                    self.tokens.append(Token(TokenType.SYMBOL_GE, ">=", self.pos, self.pos + 2))
                    self._advance(); self._advance()
                else:
                    self.tokens.append(Token(TokenType.SYMBOL_GT, ">", self.pos, self.pos + 1)); self._advance()
            elif char == '<':
                if self._peek(1) == '=':
                    self.tokens.append(Token(TokenType.SYMBOL_LE, "<=", self.pos, self.pos + 2))
                    self._advance(); self._advance()
                elif self._peek(1) == '>':
                    self.tokens.append(Token(TokenType.SYMBOL_NE, "<>", self.pos, self.pos + 2))
                    self._advance(); self._advance()
                else:
                    self.tokens.append(Token(TokenType.SYMBOL_LT, "<", self.pos, self.pos + 1)); self._advance()
            elif char == '!':
                if self._peek(1) == '=':
                    self.tokens.append(Token(TokenType.SYMBOL_NE, "!=", self.pos, self.pos + 2))
                    self._advance(); self._advance()
                else: self._advance()

            # 7. 處理符號與括號平衡
            elif char == '*':
                self.tokens.append(Token(TokenType.SYMBOL_ASTERISK, "*", self.pos, self.pos + 1)); self._advance()
            elif char == ',':
                self.tokens.append(Token(TokenType.SYMBOL_COMMA, ",", self.pos, self.pos + 1)); self._advance()
            elif char == '.':
                self.tokens.append(Token(TokenType.SYMBOL_DOT, ".", self.pos, self.pos + 1)); self._advance()
            elif char == '+':
                self.tokens.append(Token(TokenType.SYMBOL_PLUS, "+", self.pos, self.pos + 1)); self._advance()
            elif char == ';':
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
                self._advance()

        if self._bracket_stack:
            raise ValueError("Unclosed bracket")

        self.tokens.append(Token(TokenType.EOF, "", self.pos, self.pos))
        return self.tokens