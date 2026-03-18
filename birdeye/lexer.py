from enum import Enum, auto
from dataclasses import dataclass
from typing import List

class TokenType(Enum):
    """定義 BirdEye-SQL 支援的所有標記類型 [cite: 9, 11]"""
    # Keywords (SQL 關鍵字)
    KEYWORD_SELECT = auto()
    KEYWORD_FROM = auto()
    KEYWORD_AS = auto()
    
    # Identifiers (資料表名、欄位名)
    IDENTIFIER = auto()
    
    # Symbols (運算符與符號)
    SYMBOL_ASTERISK = auto()   # *
    SYMBOL_COMMA = auto()      # ,
    SYMBOL_DOT = auto()        # .
    SYMBOL_SEMICOLON = auto()  # ;
    SYMBOL_MINUS = auto()      # -
    SYMBOL_BRACKET_L = auto()  # [ (MSSQL 特有)
    SYMBOL_BRACKET_R = auto()  # ] (MSSQL 特有)
    
    # Special
    EOF = auto()               # End of File

@dataclass
class Token:
    """Zero-copy Token: 僅儲存原始代碼的索引位置 """
    type: TokenType
    start: int
    end: int

class Lexer:
    def __init__(self, source_code: str):
        self.source = source_code
        self.position = 0
        self.length = len(source_code)

    def _skip_whitespace(self):
        """跳過所有空白、換行與定位符"""
        while self.position < self.length and self.source[self.position].isspace():
            self.position += 1

    def _read_identifier_or_keyword(self) -> Token:
        """讀取連續字元並判斷是否為關鍵字 (不分大小寫) """
        start_pos = self.position
        while self.position < self.length and (self.source[self.position].isalnum() or self.source[self.position] == '_'):
            self.position += 1
        
        # 取得字串文本進行關鍵字比對
        word = self.source[start_pos:self.position].upper()
        
        if word == "SELECT":
            return Token(TokenType.KEYWORD_SELECT, start_pos, self.position)
        elif word == "FROM":
            return Token(TokenType.KEYWORD_FROM, start_pos, self.position)
        elif word == "AS":
            return Token(TokenType.KEYWORD_AS, start_pos, self.position)
        else:
            return Token(TokenType.IDENTIFIER, start_pos, self.position)

    def tokenize(self) -> List[Token]:
        """核心掃描邏輯：將 SQL 字串轉化為 Token 流 """
        tokens = []
        
        while self.position < self.length:
            self._skip_whitespace()
            if self.position >= self.length:
                break
                
            char = self.source[self.position]
            start_pos = self.position
            
            # --- 符號辨識鏈 ---
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
                tokens.append(Token(TokenType.SYMBOL_MINUS, start_pos, start_pos + 1))
                self.position += 1
            elif char == '[':
                tokens.append(Token(TokenType.SYMBOL_BRACKET_L, start_pos, start_pos + 1))
                self.position += 1
            elif char == ']':
                tokens.append(Token(TokenType.SYMBOL_BRACKET_R, start_pos, start_pos + 1))
                self.position += 1
            
            # --- 標識符與關鍵字 ---
            elif char.isalpha() or char == '_':
                tokens.append(self._read_identifier_or_keyword())
            
            # --- 錯誤防護機制 (與 BVA 測試連動) ---
            else:
                # 遇到無法解析的字元，暫時視為單字元標識符交給 Parser 處理 EOF 結界
                tokens.append(Token(TokenType.IDENTIFIER, start_pos, start_pos + 1))
                self.position += 1
                
        # 補上 EOF 結界，確保 Parser 能偵測 SQL 注入 [cite: 10]
        tokens.append(Token(TokenType.EOF, self.position, self.position))
        return tokens