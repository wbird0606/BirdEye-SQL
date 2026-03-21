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
    KEYWORD_UNION = auto()      # For UNION
    KEYWORD_ALL = auto()        # For UNION ALL
    KEYWORD_WITH = auto()       # For CTE
    KEYWORD_TRUNCATE = auto()   # For TRUNCATE
    KEYWORD_TABLE = auto()      # For TABLE
    KEYWORD_ANY = auto()        # For ANY
    KEYWORD_OVER = auto()       # For Window Functions
    KEYWORD_PARTITION = auto()  # For Window Functions
    KEYWORD_ROWS = auto()       # For Window Functions
    KEYWORD_RANGE = auto()      # For Window Functions
    KEYWORD_PRECEDING = auto()  # For Window Functions
    KEYWORD_FOLLOWING = auto()  # For Window Functions
    KEYWORD_CURRENT = auto()    # For Window Functions
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
    KEYWORD_IN = auto()         # Issue #32
    KEYWORD_EXISTS = auto()     # Issue #32
    KEYWORD_IS = auto()         # For IS NULL
    KEYWORD_NOT = auto()        # For IS NOT NULL
    KEYWORD_NULL = auto()       # For IS NULL
    KEYWORD_LIKE = auto()       # For LIKE
    KEYWORD_BETWEEN = auto()    # For BETWEEN
    KEYWORD_CAST = auto()       # For CAST
    KEYWORD_CONVERT = auto()    # For CONVERT
    
    # 💡 Issue #33 新增：CASE 邏輯關鍵字
    KEYWORD_CASE = auto()
    KEYWORD_WHEN = auto()
    KEYWORD_THEN = auto()
    KEYWORD_ELSE = auto()
    KEYWORD_END = auto()
    
    # Identifiers & Literals
    IDENTIFIER = auto()
    STRING_LITERAL = auto()
    NUMERIC_LITERAL = auto()
    
    # Symbols (符號)
    SYMBOL_ASTERISK = auto()   # *
    SYMBOL_COMMA = auto()      # ,
    SYMBOL_DOT = auto()        # .
    SYMBOL_EQUAL = auto()      # =
    SYMBOL_PLUS = auto()       # +
    SYMBOL_MINUS = auto()      # -
    SYMBOL_SLASH = auto()      # /
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
    v1.6.7: 支援 CASE WHEN 邏輯關鍵字，完整支援子查詢與比較運算子。
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
        # 💡 Issue #33: 更新關鍵字映射字典
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
            "UNION": TokenType.KEYWORD_UNION,
            "ALL": TokenType.KEYWORD_ALL,
            "WITH": TokenType.KEYWORD_WITH,
            "TRUNCATE": TokenType.KEYWORD_TRUNCATE,
            "TABLE": TokenType.KEYWORD_TABLE,
            "ANY": TokenType.KEYWORD_ANY,
            "ALL": TokenType.KEYWORD_ALL,
            "OVER": TokenType.KEYWORD_OVER,
            "PARTITION": TokenType.KEYWORD_PARTITION,
            "ROWS": TokenType.KEYWORD_ROWS,
            "RANGE": TokenType.KEYWORD_RANGE,
            "PRECEDING": TokenType.KEYWORD_PRECEDING,
            "FOLLOWING": TokenType.KEYWORD_FOLLOWING,
            "CURRENT": TokenType.KEYWORD_CURRENT,
            "ON": TokenType.KEYWORD_ON,            "AND": TokenType.KEYWORD_AND,
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
            "IS": TokenType.KEYWORD_IS,
            "NOT": TokenType.KEYWORD_NOT,
            "NULL": TokenType.KEYWORD_NULL,
            "LIKE": TokenType.KEYWORD_LIKE,
            "BETWEEN": TokenType.KEYWORD_BETWEEN,
            "CAST": TokenType.KEYWORD_CAST,
            "CONVERT": TokenType.KEYWORD_CONVERT,
            "OVER": TokenType.KEYWORD_OVER,
            "PARTITION": TokenType.KEYWORD_PARTITION,
            "ROWS": TokenType.KEYWORD_ROWS,
            "RANGE": TokenType.KEYWORD_RANGE,
            "PRECEDING": TokenType.KEYWORD_PRECEDING,
            "FOLLOWING": TokenType.KEYWORD_FOLLOWING,
            "CURRENT": TokenType.KEYWORD_CURRENT,
            "CASE": TokenType.KEYWORD_CASE,
            "WHEN": TokenType.KEYWORD_WHEN,
            "THEN": TokenType.KEYWORD_THEN,
            "ELSE": TokenType.KEYWORD_ELSE,
            "END": TokenType.KEYWORD_END,
        }

        while self.pos < len(self.source):
            char = self._peek()

            if char.isspace():
                self._advance()
                continue

            # 1. 處理註解 (確保審計語意乾淨)
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

            # 4. 處理字串 (包含 '' 轉義支援)
            if char == "'":
                start = self.pos
                self._advance()
                while self._peek():
                    if self._peek() == "'":
                        if self._peek(1) == "'":
                            # 遇到 '' 代表轉義單引號，跳過兩個字元
                            self._advance(); self._advance()
                        else:
                            # 遇到單個 ' 代表字串結束
                            break
                    else:
                        self._advance()
                if not self._peek():
                    raise ValueError("Unclosed string literal")
                self._advance() # 消耗最後的關閉引號
                
                # 💡 TDD Fix: 提取內容並將轉義的 '' 轉回 '
                raw_text = self.source[start:self.pos]
                processed_text = raw_text.replace("''", "'")
                
                self.tokens.append(Token(TokenType.STRING_LITERAL, processed_text, start, self.pos))
                continue

            # 5. 處理 MSSQL 中括號標識符
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

            # 6. 處理比較運算子 (GT, LT, GE, LE, NE)
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

            # 7. 單一符號與括號平衡檢查
            elif char == '*':
                self.tokens.append(Token(TokenType.SYMBOL_ASTERISK, "*", self.pos, self.pos + 1)); self._advance()
            elif char == ',':
                self.tokens.append(Token(TokenType.SYMBOL_COMMA, ",", self.pos, self.pos + 1)); self._advance()
            elif char == '.':
                self.tokens.append(Token(TokenType.SYMBOL_DOT, ".", self.pos, self.pos + 1)); self._advance()
            elif char == '+':
                self.tokens.append(Token(TokenType.SYMBOL_PLUS, "+", self.pos, self.pos + 1)); self._advance()
            elif char == '-':
                self.tokens.append(Token(TokenType.SYMBOL_MINUS, "-", self.pos, self.pos + 1)); self._advance()
            elif char == '/':
                self.tokens.append(Token(TokenType.SYMBOL_SLASH, "/", self.pos, self.pos + 1)); self._advance()
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