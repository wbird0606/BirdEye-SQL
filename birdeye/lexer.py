from enum import Enum, auto
from dataclasses import dataclass
from typing import List

class TokenType(Enum):
    # Keywords - Query
    KEYWORD_SELECT = auto(); KEYWORD_FROM = auto(); KEYWORD_AS = auto()
    KEYWORD_JOIN = auto(); KEYWORD_ON = auto(); KEYWORD_INNER = auto()
    KEYWORD_LEFT = auto(); KEYWORD_RIGHT = auto()
    
    # Keywords - DML (Issue #27, #28)
    KEYWORD_UPDATE = auto(); KEYWORD_SET = auto(); KEYWORD_DELETE = auto()
    KEYWORD_INSERT = auto(); KEYWORD_INTO = auto(); KEYWORD_VALUES = auto()
    
    # Keywords - Logic & Condition (Issue #27)
    KEYWORD_WHERE = auto(); KEYWORD_AND = auto(); KEYWORD_OR = auto()
    
    # Identifiers & Literals
    IDENTIFIER = auto(); STRING_LITERAL = auto(); NUMERIC_LITERAL = auto()
    
    # Symbols
    SYMBOL_ASTERISK = auto(); SYMBOL_COMMA = auto(); SYMBOL_DOT = auto()
    SYMBOL_SEMICOLON = auto(); SYMBOL_MINUS = auto(); SYMBOL_EQUAL = auto()
    SYMBOL_PLUS = auto(); SYMBOL_SLASH = auto(); SYMBOL_PERCENT = auto()
    SYMBOL_PAREN_L = auto(); SYMBOL_PAREN_R = auto()
    SYMBOL_BRACKET_L = auto(); SYMBOL_BRACKET_R = auto()
    EOF = auto()

@dataclass
class Token:
    type: TokenType; start: int; end: int

class Lexer:
    def __init__(self, source_code: str):
        self.source = source_code; self.position = 0; self.length = len(source_code)

    def _skip_whitespace(self):
        while self.position < self.length and self.source[self.position].isspace(): self.position += 1

    def _skip_multi_line_comment(self):
        self.position += 2; nesting_level = 1
        while nesting_level > 0:
            if self.position + 1 >= self.length: raise ValueError("Unclosed nested block comment")
            if self.source[self.position:self.position+2] == "/*": nesting_level += 1; self.position += 2
            elif self.source[self.position:self.position+2] == "*/": nesting_level -= 1; self.position += 2
            else: self.position += 1

    def _read_bracket_content(self) -> Token:
        start_pos = self.position
        while self.position < self.length:
            if self.source[self.position] == ']':
                if self.position + 1 < self.length and self.source[self.position+1] == ']':
                    self.position += 2; continue
                else: break
            self.position += 1
        if self.position >= self.length: raise ValueError("Unclosed bracket")
        return Token(TokenType.IDENTIFIER, start_pos, self.position)

    def _read_identifier_or_keyword(self) -> Token:
        """更新：擴充 DML 與條件關鍵字識別"""
        start_pos = self.position
        while self.position < self.length and (self.source[self.position].isalnum() or self.source[self.position] == '_'):
            self.position += 1
        word = self.source[start_pos:self.position].upper()
        
        # 完整的關鍵字映射表
        keywords = {
            "SELECT": TokenType.KEYWORD_SELECT, "FROM": TokenType.KEYWORD_FROM, "AS": TokenType.KEYWORD_AS,
            "JOIN": TokenType.KEYWORD_JOIN, "ON": TokenType.KEYWORD_ON, "INNER": TokenType.KEYWORD_INNER,
            "LEFT": TokenType.KEYWORD_LEFT, "RIGHT": TokenType.KEYWORD_RIGHT,
            # DML
            "UPDATE": TokenType.KEYWORD_UPDATE, "SET": TokenType.KEYWORD_SET, "DELETE": TokenType.KEYWORD_DELETE,
            "INSERT": TokenType.KEYWORD_INSERT, "INTO": TokenType.KEYWORD_INTO, "VALUES": TokenType.KEYWORD_VALUES,
            # Logic
            "WHERE": TokenType.KEYWORD_WHERE, "AND": TokenType.KEYWORD_AND, "OR": TokenType.KEYWORD_OR
        }
        return Token(keywords.get(word, TokenType.IDENTIFIER), start_pos, self.position)

    def tokenize(self) -> List[Token]:
        tokens = []
        while self.position < self.length:
            self._skip_whitespace()
            if self.position >= self.length: break
            char = self.source[self.position]; start_pos = self.position
            next_char = self.source[self.position + 1] if self.position + 1 < self.length else None

            if char == '-' and next_char == '-':
                while self.position < self.length and self.source[self.position] != '\n': self.position += 1
                continue
            if char == '/' and next_char == '*': self._skip_multi_line_comment(); continue

            if char == "'": tokens.append(self._read_string_literal()); continue
            if char.isdigit(): tokens.append(self._read_numeric_literal()); continue
            
            if char == '*': tokens.append(Token(TokenType.SYMBOL_ASTERISK, start_pos, start_pos+1)); self.position += 1
            elif char == '+': tokens.append(Token(TokenType.SYMBOL_PLUS, start_pos, start_pos+1)); self.position += 1
            elif char == '-': tokens.append(Token(TokenType.SYMBOL_MINUS, start_pos, start_pos+1)); self.position += 1
            elif char == '/': tokens.append(Token(TokenType.SYMBOL_SLASH, start_pos, start_pos+1)); self.position += 1
            elif char == '%': tokens.append(Token(TokenType.SYMBOL_PERCENT, start_pos, start_pos+1)); self.position += 1
            elif char == '=': tokens.append(Token(TokenType.SYMBOL_EQUAL, start_pos, start_pos+1)); self.position += 1
            elif char == ',': tokens.append(Token(TokenType.SYMBOL_COMMA, start_pos, start_pos+1)); self.position += 1
            elif char == '.': tokens.append(Token(TokenType.SYMBOL_DOT, start_pos, start_pos+1)); self.position += 1
            elif char == '(': tokens.append(Token(TokenType.SYMBOL_PAREN_L, start_pos, start_pos+1)); self.position += 1
            elif char == ')': tokens.append(Token(TokenType.SYMBOL_PAREN_R, start_pos, start_pos+1)); self.position += 1
            elif char == '[':
                self.position += 1; tokens.append(self._read_bracket_content()); self.position += 1
            elif char.isalpha() or char == '_': tokens.append(self._read_identifier_or_keyword())
            elif char == ';':
                tokens.append(Token(TokenType.SYMBOL_SEMICOLON, start_pos, start_pos+1))
                self.position += 1
            else: self.position += 1
        tokens.append(Token(TokenType.EOF, self.position, self.position))
        return tokens

    def _read_string_literal(self):
        start = self.position; self.position += 1
        while self.position < self.length and self.source[self.position] != "'": self.position += 1
        if self.position >= self.length: raise ValueError("Unclosed string literal")
        self.position += 1
        return Token(TokenType.STRING_LITERAL, start, self.position)

    def _read_numeric_literal(self):
        """支援浮點數解析"""
        start = self.position
        while self.position < self.length and self.source[self.position].isdigit(): self.position += 1
        if self.position < self.length and self.source[self.position] == '.':
            if self.position + 1 < self.length and self.source[self.position + 1].isdigit():
                self.position += 1
                while self.position < self.length and self.source[self.position].isdigit(): self.position += 1
        return Token(TokenType.NUMERIC_LITERAL, start, self.position)