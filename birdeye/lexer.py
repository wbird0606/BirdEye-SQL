from enum import Enum, auto
from dataclasses import dataclass
from typing import List

class TokenType(Enum):
    """定義 BirdEye-SQL 支援的所有標記類型"""
    KEYWORD_SELECT = auto()
    KEYWORD_FROM = auto()
    KEYWORD_AS = auto()
    IDENTIFIER = auto()
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
    """Zero-copy Token: 僅儲存原始代碼的索引位置"""
    type: TokenType
    start: int
    end: int

class Lexer:
    def __init__(self, source_code: str):
        self.source = source_code
        self.position = 0
        self.length = len(source_code)
        # 狀態感知：記錄目前是否處於 MSSQL 中括號內
        self.in_bracket = False 

    def _skip_whitespace(self):
        while self.position < self.length and self.source[self.position].isspace():
            self.position += 1

    def _read_identifier_or_keyword(self) -> Token:
        """讀取標識符，並根據是否在括號內決定是否檢查關鍵字"""
        start_pos = self.position
        while self.position < self.length and (self.source[self.position].isalnum() or self.source[self.position] == '_'):
            self.position += 1
        
        # 取得字串文本
        word = self.source[start_pos:self.position].upper()
        
        # 關鍵邏輯：如果在括號內，無條件視為 IDENTIFIER
        if self.in_bracket:
            return Token(TokenType.IDENTIFIER, start_pos, self.position)
        
        # 否則執行關鍵字比對
        if word == "SELECT":
            return Token(TokenType.KEYWORD_SELECT, start_pos, self.position)
        elif word == "FROM":
            return Token(TokenType.KEYWORD_FROM, start_pos, self.position)
        elif word == "AS":
            return Token(TokenType.KEYWORD_AS, start_pos, self.position)
        else:
            return Token(TokenType.IDENTIFIER, start_pos, self.position)

    def tokenize(self) -> List[Token]:
        tokens = []
        while self.position < self.length:
            self._skip_whitespace()
            if self.position >= self.length: break
                
            char = self.source[self.position]
            start_pos = self.position
            
            # --- 完整的符號辨識鏈 ---
            if char == '*':
                tokens.append(Token(TokenType.SYMBOL_ASTERISK, start_pos, start_pos + 1))
                self.position += 1
            elif char == ',':
                tokens.append(Token(TokenType.SYMBOL_COMMA, start_pos, start_pos + 1))
                self.position += 1
            elif char == '.':
                tokens.append(Token(TokenType.SYMBOL_DOT, start_pos, start_pos + 1))
                self.position += 1
            elif char == ';': # <--- 補上這個
                tokens.append(Token(TokenType.SYMBOL_SEMICOLON, start_pos, start_pos + 1))
                self.position += 1
            elif char == '-': # <--- 補上這個 (為了支援註解或運算)
                tokens.append(Token(TokenType.SYMBOL_MINUS, start_pos, start_pos + 1))
                self.position += 1
            elif char == '[':
                self.in_bracket = True
                tokens.append(Token(TokenType.SYMBOL_BRACKET_L, start_pos, start_pos + 1))
                self.position += 1
            elif char == ']':
                self.in_bracket = False
                tokens.append(Token(TokenType.SYMBOL_BRACKET_R, start_pos, start_pos + 1))
                self.position += 1
            elif char.isalpha() or char == '_':
                tokens.append(self._read_identifier_or_keyword())
            else:
                # 真正的未知字元才當標識符處理 (例如 $, # 等)
                tokens.append(Token(TokenType.IDENTIFIER, start_pos, start_pos + 1))
                self.position += 1
                
        tokens.append(Token(TokenType.EOF, self.position, self.position))
        return tokens