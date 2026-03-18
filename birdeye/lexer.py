from enum import Enum, auto
from dataclasses import dataclass
from typing import List

class TokenType(Enum):
    """BirdEye-SQL 支援的標記類型"""
    KEYWORD_SELECT = auto()
    KEYWORD_FROM = auto()
    KEYWORD_AS = auto()
    IDENTIFIER = auto()
    STRING_LITERAL = auto()
    NUMERIC_LITERAL = auto()
    SYMBOL_ASTERISK = auto()
    SYMBOL_COMMA = auto()
    SYMBOL_DOT = auto()
    SYMBOL_SEMICOLON = auto()
    SYMBOL_MINUS = auto()
    SYMBOL_BRACKET_L = auto()
    SYMBOL_BRACKET_R = auto()
    EOF = auto()

@dataclass
class Token:
    """Zero-copy Token: 僅儲存索引"""
    type: TokenType
    start: int
    end: int

class Lexer:
    def __init__(self, source_code: str):
        self.source = source_code
        self.position = 0
        self.length = len(source_code)

    def _skip_whitespace(self):
        while self.position < self.length and self.source[self.position].isspace():
            self.position += 1

    def _skip_multi_line_comment(self):
        """實作支援巢狀的多行註解解析 (Issue #21)"""
        start_pos = self.position
        self.position += 2  # 跳過開頭的 /*
        nesting_level = 1
        
        while nesting_level > 0:
            if self.position + 1 >= self.length:
                raise ValueError("Unclosed nested block comment")
            
            # 偵測到新的巢狀開始
            if self.source[self.position:self.position+2] == "/*":
                nesting_level += 1
                self.position += 2
            # 偵測到閉合符號
            elif self.source[self.position:self.position+2] == "*/":
                nesting_level -= 1
                self.position += 2
            else:
                self.position += 1

    def _read_string_literal(self) -> Token:
        start_pos = self.position
        self.position += 1
        while self.position < self.length and self.source[self.position] != "'":
            self.position += 1
        if self.position >= self.length:
            raise ValueError("Unclosed string literal")
        self.position += 1
        return Token(TokenType.STRING_LITERAL, start_pos, self.position)

    def _read_numeric_literal(self) -> Token:
        start_pos = self.position
        while self.position < self.length and self.source[self.position].isdigit():
            self.position += 1
        return Token(TokenType.NUMERIC_LITERAL, start_pos, self.position)

    def _read_bracket_content(self) -> Token:
        """實作支援 ]] 轉義的中括號內容讀取 (Issue #22)"""
        start_pos = self.position
        while self.position < self.length:
            if self.source[self.position] == ']':
                # 如果是連續的 ]], 則視為轉義，繼續讀取
                if self.position + 1 < self.length and self.source[self.position+1] == ']':
                    self.position += 2
                    continue
                else:
                    # 真正的閉合
                    break
            self.position += 1
        
        if self.position >= self.length:
            raise ValueError("Unclosed bracket")
        return Token(TokenType.IDENTIFIER, start_pos, self.position)

    def _read_identifier_or_keyword(self) -> Token:
        start_pos = self.position
        while self.position < self.length and (self.source[self.position].isalnum() or self.source[self.position] == '_'):
            self.position += 1
        
        word = self.source[start_pos:self.position]
        upper_word = word.upper()
        keywords = {"SELECT": TokenType.KEYWORD_SELECT, "FROM": TokenType.KEYWORD_FROM, "AS": TokenType.KEYWORD_AS}
        return Token(keywords.get(upper_word, TokenType.IDENTIFIER), start_pos, self.position)

    def tokenize(self) -> List[Token]:
        tokens = []
        while self.position < self.length:
            self._skip_whitespace()
            if self.position >= self.length: break
            
            char = self.source[self.position]
            next_char = self.source[self.position + 1] if self.position + 1 < self.length else None
            
            # 1. 註解處理
            if char == '-' and next_char == '-':
                while self.position < self.length and self.source[self.position] != '\n':
                    self.position += 1
                continue
            if char == '/' and next_char == '*':
                self._skip_multi_line_comment()
                continue

            # 2. 標量與符號
            start_pos = self.position
            if char == "'": tokens.append(self._read_string_literal()); continue
            if char.isdigit(): tokens.append(self._read_numeric_literal()); continue
            
            if char == '*': tokens.append(Token(TokenType.SYMBOL_ASTERISK, start_pos, start_pos+1)); self.position += 1
            elif char == ',': tokens.append(Token(TokenType.SYMBOL_COMMA, start_pos, start_pos+1)); self.position += 1
            elif char == '.': tokens.append(Token(TokenType.SYMBOL_DOT, start_pos, start_pos+1)); self.position += 1
            elif char == ';': tokens.append(Token(TokenType.SYMBOL_SEMICOLON, start_pos, start_pos+1)); self.position += 1
            elif char == '-': tokens.append(Token(TokenType.SYMBOL_MINUS, start_pos, start_pos+1)); self.position += 1
            
            # 3. 中括號標識符 (Issue #22)
            elif char == '[':
                tokens.append(Token(TokenType.SYMBOL_BRACKET_L, start_pos, start_pos+1))
                self.position += 1
                tokens.append(self._read_bracket_content())
                tokens.append(Token(TokenType.SYMBOL_BRACKET_R, self.position, self.position+1))
                self.position += 1
            
            # 4. 一般標識符與關鍵字
            elif char.isalpha() or char == '_':
                tokens.append(self._read_identifier_or_keyword())
            else:
                self.position += 1 # 跳過未知字元
        
        tokens.append(Token(TokenType.EOF, self.position, self.position))
        return tokens