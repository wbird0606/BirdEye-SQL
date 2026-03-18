# birdeye/lexer.py

from enum import Enum, auto
from dataclasses import dataclass
from typing import List

class TokenType(Enum):
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
    type: TokenType
    start: int
    end: int

class Lexer:
    def __init__(self, source_code: str):
        self.source = source_code
        self.position = 0
        self.length = len(source_code)
        self.in_bracket = False 

    def _skip_whitespace(self):
        # 關鍵：只有在非括號模式下才主動跳過空格
        # 在括號內，空格可能是標識符的一部分
        while self.position < self.length and self.source[self.position].isspace():
            if self.in_bracket:
                break
            self.position += 1

    def _read_identifier_or_keyword(self) -> Token:
        """根據是否在括號內，切換不同的讀取策略"""
        start_pos = self.position
        
        if self.in_bracket:
            # 【Issue #16】括號模式：貪婪讀取直到遇見 ] 為止
            while self.position < self.length and self.source[self.position] != ']':
                self.position += 1
        else:
            # 正常模式：僅讀取英數與底線
            while self.position < self.length and (self.source[self.position].isalnum() or self.source[self.position] == '_'):
                self.position += 1
        
        # 取得文本
        word = self.source[start_pos:self.position]
        
        # 關鍵邏輯：如果在括號內，強制為 IDENTIFIER 且不進行關鍵字比對
        if self.in_bracket:
            return Token(TokenType.IDENTIFIER, start_pos, self.position)
        
        # 否則檢查是否為關鍵字
        upper_word = word.upper()
        if upper_word == "SELECT":
            return Token(TokenType.KEYWORD_SELECT, start_pos, self.position)
        elif upper_word == "FROM":
            return Token(TokenType.KEYWORD_FROM, start_pos, self.position)
        elif upper_word == "AS":
            return Token(TokenType.KEYWORD_AS, start_pos, self.position)
        else:
            return Token(TokenType.IDENTIFIER, start_pos, self.position)

    def tokenize(self) -> List[Token]:
        tokens = []
        while self.position < self.length:
            self._skip_whitespace()
            if self.position >= self.length: break
                
            char = self.source[self.position]
            # 取得下一個字元，用於判斷雙字元符號
            next_char = self.source[self.position + 1] if self.position + 1 < self.length else None
            start_pos = self.position
            
            # --- 【Issue #17】註解跳過邏輯 ---
            # 只有在非中括號模式下才處理註解 (防止 [Column -- Name] 被誤殺)
            if not self.in_bracket:
                # 1. 單行註解 (-- ...)
                if char == '-' and next_char == '-':
                    while self.position < self.length and self.source[self.position] != '\n':
                        self.position += 1
                    continue # 直接進入下一輪掃描，不產生 Token
                
                # 2. 多行註解 (/* ... */)
                if char == '/' and next_char == '*':
                    self.position += 2 # 跳過 /*
                    while self.position < self.length - 1:
                        if self.source[self.position] == '*' and self.source[self.position + 1] == '/':
                            self.position += 2 # 跳過 */
                            break
                        self.position += 1
                    else:
                        # 沒找到結束符號，直接跳到結尾 (或是留給後續 Issue #20 處理報錯)
                        self.position = self.length
                    continue

            # --- 原有符號辨識鏈 ---
            if char == '*':
                tokens.append(Token(TokenType.SYMBOL_ASTERISK, start_pos, start_pos + 1))
                self.position += 1
            elif char == ',':
                tokens.append(Token(TokenType.SYMBOL_COMMA, start_pos, start_pos + 1))
                self.position += 1
            elif char == '.':
                tokens.append(Token(TokenType.SYMBOL_DOT, start_pos, start_pos + 1))
                self.position += 1
            elif char == ';':
                tokens.append(Token(TokenType.SYMBOL_SEMICOLON, start_pos, start_pos + 1))
                self.position += 1
            elif char == '-':
                # 這裡的單一減號可能是運算子
                tokens.append(Token(TokenType.SYMBOL_MINUS, start_pos, start_pos + 1))
                self.position += 1
            elif char == '[':
                tokens.append(Token(TokenType.SYMBOL_BRACKET_L, start_pos, start_pos + 1))
                self.position += 1
                self.in_bracket = True
                if self.position < self.length and self.source[self.position] != ']':
                    tokens.append(self._read_identifier_or_keyword())
            elif char == ']':
                tokens.append(Token(TokenType.SYMBOL_BRACKET_R, start_pos, start_pos + 1))
                self.position += 1
                self.in_bracket = False
            elif char.isalpha() or char == '_':
                tokens.append(self._read_identifier_or_keyword())
            else:
                # 其他特殊字元 (如數字或未知標記)
                tokens.append(self._read_identifier_or_keyword() if self.in_bracket else Token(TokenType.IDENTIFIER, start_pos, start_pos + 1))
                if not self.in_bracket: self.position += 1
                
        tokens.append(Token(TokenType.EOF, self.position, self.position))
        return tokens