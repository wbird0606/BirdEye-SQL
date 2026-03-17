# birdeye/lexer.py
from enum import Enum, auto
from dataclasses import dataclass
from typing import List

class TokenType(Enum):
    # Keywords
    KEYWORD_SELECT = auto()
    KEYWORD_FROM = auto()
    
    # Identifiers
    IDENTIFIER = auto()
    
    # Symbols
    SYMBOL_ASTERISK = auto() # *
    SYMBOL_COMMA = auto()    # ,
    SYMBOL_DOT = auto()      # .
    SYMBOL_SEMICOLON = auto() # ;  <-- 新增
    SYMBOL_MINUS = auto()    # -   <-- 新增
    
    # Special
    EOF = auto()             # End of File

@dataclass
class Token:
    """Zero-copy Token: 只保存原始資料的指標(Index)，不複製字串內容"""
    type: TokenType
    start: int
    end: int

class Lexer:
    def __init__(self, source_code: str):
        self.source = source_code
        self.position = 0
        self.length = len(source_code)

    def _skip_whitespace(self):
        """跳過空白、Tab 與換行符號"""
        while self.position < self.length and self.source[self.position].isspace():
            self.position += 1

    def _read_identifier_or_keyword(self) -> Token:
        """讀取連續的字母或數字，並判斷是關鍵字還是 Identifier"""
        start_pos = self.position
        while self.position < self.length and (self.source[self.position].isalnum() or self.source[self.position] == '_'):
            self.position += 1
        
        # 利用 slice 取出字串來比對 Keyword (只有在判斷時暫時切出，回傳的 Token 仍是 zero-copy)
        # 注意：這裡統一轉大寫來比對，實現 Case-insensitive
        word = self.source[start_pos:self.position].upper()
        
        if word == "SELECT":
            return Token(TokenType.KEYWORD_SELECT, start_pos, self.position)
        elif word == "FROM":
            return Token(TokenType.KEYWORD_FROM, start_pos, self.position)
        else:
            return Token(TokenType.IDENTIFIER, start_pos, self.position)

    def tokenize(self) -> List[Token]:
        tokens = []
        
        while self.position < self.length:
            self._skip_whitespace()
            if self.position >= self.length:
                break
                
            char = self.source[self.position]
            start_pos = self.position
            
            # 處理符號
            # 處理符號 (新增 ; 和 -)
            if char == '*':
                tokens.append(Token(TokenType.SYMBOL_ASTERISK, start_pos, start_pos + 1))
                self.position += 1
            elif char == ',':
                tokens.append(Token(TokenType.SYMBOL_COMMA, start_pos, start_pos + 1))
                self.position += 1
            elif char == '.':
                tokens.append(Token(TokenType.SYMBOL_DOT, start_pos, start_pos + 1))
                self.position += 1
            elif char == ';':  # <-- 新增分號
                tokens.append(Token(TokenType.SYMBOL_SEMICOLON, start_pos, start_pos + 1))
                self.position += 1
            elif char == '-':  # <-- 新增連字號 (SQL 註解常用)
                tokens.append(Token(TokenType.SYMBOL_MINUS, start_pos, start_pos + 1))
                self.position += 1
            elif char.isalpha() or char == '_':
                tokens.append(self._read_identifier_or_keyword())
            else:
                # 為了避免未來再有未知符號讓 Lexer 崩潰，我們把它當作一格的 Identifier 傳下去
                # 這樣 Parser 就會因為拿到不預期的 Token 而拋出 SyntaxError，而不是在這裡炸掉
                tokens.append(Token(TokenType.IDENTIFIER, start_pos, start_pos + 1))
                self.position += 1
                
        # 最後補上 EOF Token
        tokens.append(Token(TokenType.EOF, self.position, self.position))
        return tokens