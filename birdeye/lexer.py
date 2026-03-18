from enum import Enum, auto
from dataclasses import dataclass
from typing import List

class TokenType(Enum):
    """BirdEye-SQL 支援的標記類型"""
    # Keywords
    KEYWORD_SELECT = auto()
    KEYWORD_FROM = auto()
    KEYWORD_AS = auto()
    
    # Identifiers & Literals
    IDENTIFIER = auto()
    STRING_LITERAL = auto()   # 'Active'
    NUMERIC_LITERAL = auto()  # 100
    
    # Symbols
    SYMBOL_ASTERISK = auto()   # *
    SYMBOL_COMMA = auto()      # ,
    SYMBOL_DOT = auto()        # .
    SYMBOL_SEMICOLON = auto()  # ;
    SYMBOL_MINUS = auto()      # -
    SYMBOL_BRACKET_L = auto()  # [
    SYMBOL_BRACKET_R = auto()  # ]
    
    # Special
    EOF = auto()

@dataclass
class Token:
    """Zero-copy Token: 僅儲存索引，優化記憶體效能"""
    type: TokenType
    start: int
    end: int

class Lexer:
    def __init__(self, source_code: str):
        self.source = source_code
        self.position = 0
        self.length = len(source_code)
        self.in_bracket = False # 括號狀態感知

    def _skip_whitespace(self):
        """跳過空白，但在中括號內不跳過"""
        while self.position < self.length and self.source[self.position].isspace():
            if self.in_bracket: break
            self.position += 1

    def _read_string_literal(self) -> Token:
        start_pos = self.position
        self.position += 1 # 跳過起始 '
        while self.position < self.length and self.source[self.position] != "'":
            self.position += 1
        
        # --- 【Issue #20 修正】檢查是否是因為 EOF 而跳出 ---
        if self.position >= self.length:
            raise ValueError("Unclosed string literal")
            
        self.position += 1 # 跳過結尾 '
        return Token(TokenType.STRING_LITERAL, start_pos, self.position)

    def _read_numeric_literal(self) -> Token:
        """讀取數值常量"""
        start_pos = self.position
        while self.position < self.length and self.source[self.position].isdigit():
            self.position += 1
        return Token(TokenType.NUMERIC_LITERAL, start_pos, self.position)

    def _read_identifier_or_keyword(self) -> Token:
        """根據狀態切換讀取策略"""
        start_pos = self.position
        if self.in_bracket:
            while self.position < self.length and self.source[self.position] != ']':
                self.position += 1
        else:
            while self.position < self.length and (self.source[self.position].isalnum() or self.source[self.position] == '_'):
                self.position += 1
        
        word = self.source[start_pos:self.position]
        if self.in_bracket:
            return Token(TokenType.IDENTIFIER, start_pos, self.position)
        
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
            start_pos = self.position
            
            # 1. 註解跳過
            if not self.in_bracket:
                if char == '-' and next_char == '-':
                    while self.position < self.length and self.source[self.position] != '\n': self.position += 1
                    continue
                if char == '/' and next_char == '*':
                    self.position += 2
                    while self.position < self.length - 1:
                        if self.source[self.position] == '*' and self.source[self.position+1] == '/':
                            self.position += 2; break
                        self.position += 1
                    else: self.position = self.length
                    continue

            # 2. 字串與數字
            if char == "'": tokens.append(self._read_string_literal()); continue
            if char.isdigit() and not self.in_bracket: tokens.append(self._read_numeric_literal()); continue
            
            # 3. 符號與標識符
            if char == '*': tokens.append(Token(TokenType.SYMBOL_ASTERISK, start_pos, start_pos+1)); self.position += 1
            elif char == ',': tokens.append(Token(TokenType.SYMBOL_COMMA, start_pos, start_pos+1)); self.position += 1
            elif char == '.': tokens.append(Token(TokenType.SYMBOL_DOT, start_pos, start_pos+1)); self.position += 1
            elif char == ';': tokens.append(Token(TokenType.SYMBOL_SEMICOLON, start_pos, start_pos+1)); self.position += 1
            elif char == '-': tokens.append(Token(TokenType.SYMBOL_MINUS, start_pos, start_pos+1)); self.position += 1
            elif char == '[':
                tokens.append(Token(TokenType.SYMBOL_BRACKET_L, start_pos, start_pos+1))
                self.position += 1; self.in_bracket = True
                if self.position < self.length and self.source[self.position] != ']':
                    tokens.append(self._read_identifier_or_keyword())
            elif char == ']':
                tokens.append(Token(TokenType.SYMBOL_BRACKET_R, start_pos, start_pos+1))
                self.position += 1; self.in_bracket = False
            elif char.isalpha() or char == '_': tokens.append(self._read_identifier_or_keyword())
            else:
                tokens.append(self._read_identifier_or_keyword() if self.in_bracket else Token(TokenType.IDENTIFIER, start_pos, start_pos+1))
                if not self.in_bracket: self.position += 1
        
        # --- 【Issue #20 修正】掃描結束後，確認括號是否閉合 ---
        if self.in_bracket:
            raise ValueError("Unclosed bracket")
            
        tokens.append(Token(TokenType.EOF, self.position, self.position))
        return tokens