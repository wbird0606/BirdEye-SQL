from birdeye.lexer import TokenType
from birdeye.ast import (
    SelectStatement, UpdateStatement, DeleteStatement, InsertStatement, 
    SqlBulkCopyStatement, IdentifierNode, LiteralNode, 
    BinaryExpressionNode, FunctionCallNode, JoinNode, AssignmentNode,
    OrderByNode, CaseExpressionNode
)

class Parser:
    """
    語法分析器：將 Token 序列轉換為抽象語法樹 (AST)。
    v1.6.9: 支援 CASE WHEN、子查詢，並實作 ZTA 語意感知 FROM 檢查。
    """
    def __init__(self, tokens, source):
        self.tokens = tokens
        self.source = source
        self.pos = 0
        self._is_qual_star = False 

    # --- 基礎工具方法 ---

    def _peek(self, offset=0):
        if self.pos + offset >= len(self.tokens): return None
        return self.tokens[self.pos + offset]

    def _advance(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _match(self, *types):
        tok = self._peek()
        if tok and tok.type in types:
            return self._advance()
        return None

    def _consume(self, type, message):
        tok = self._match(type)
        if not tok: raise SyntaxError(message)
        return tok

    def _get_text(self, token):
        text = token.value if hasattr(token, 'value') and token.value else self.source[token.start:token.end]
        return text.strip("[]")

    # --- 1. 主解析入口 ---

    def parse(self):
        tok = self._peek()
        if not tok or tok.type == TokenType.EOF: raise SyntaxError("Empty source")
        
        if tok.type == TokenType.KEYWORD_SELECT: stmt = self._parse_select()
        elif tok.type == TokenType.KEYWORD_UPDATE: stmt = self._parse_update()
        elif tok.type == TokenType.KEYWORD_DELETE: stmt = self._parse_delete()
        elif tok.type == TokenType.KEYWORD_INSERT: stmt = self._parse_insert()
        elif tok.type == TokenType.IDENTIFIER and self._get_text(tok).upper() == "BULK":
            stmt = self._parse_bulk_insert()
        else:
            raise SyntaxError(f"Unexpected token: {self._get_text(tok)}")
        
        peek = self._peek()
        if peek and peek.type != TokenType.EOF:
            raise SyntaxError(f"Unexpected token: {self._get_text(peek)}")
        return stmt

    # --- 2. DQL 解析: SELECT ---

    def _parse_select(self):
        stmt = SelectStatement()
        self._consume(TokenType.KEYWORD_SELECT, "Expected SELECT")

        if self._match(TokenType.KEYWORD_TOP):
            num_tok = self._match(TokenType.NUMERIC_LITERAL)
            if not num_tok: raise SyntaxError("Expected numeric literal after TOP")
            stmt.top_count = int(num_tok.value)

        # 解析投影欄位
        while True:
            if self._match(TokenType.SYMBOL_ASTERISK):
                stmt.is_select_star = True
            else:
                self._is_qual_star = False
                expr = self._parse_expression()
                if self._is_qual_star:
                    prefix = expr.name if not expr.qualifiers else ".".join(expr.qualifiers + [expr.name])
                    stmt.star_prefixes.append(prefix)
                else:
                    self._match(TokenType.KEYWORD_AS)
                    alias = self._match(TokenType.IDENTIFIER)
                    if alias: expr.alias = self._get_text(alias)
                    stmt.columns.append(expr)
            if not self._match(TokenType.SYMBOL_COMMA): break

        # 💡 ZTA 語意感知 FROM 檢查
        if self._match(TokenType.KEYWORD_FROM):
            stmt.table, _ = self._parse_full_identifier_safe()
            self._match(TokenType.KEYWORD_AS)
            alias_tok = self._match(TokenType.IDENTIFIER)
            if alias_tok: stmt.table_alias = self._get_text(alias_tok)

            # 🛡️ 攔截隱含式關聯 (FROM A, B)
            if self._peek() and self._peek().type == TokenType.SYMBOL_COMMA:
                raise SyntaxError("Expected FROM")

            # 解析 JOIN
            while True:
                jt = "INNER"
                if self._match(TokenType.KEYWORD_LEFT): jt = "LEFT"
                elif self._match(TokenType.KEYWORD_RIGHT): jt = "RIGHT"
                self._match(TokenType.KEYWORD_INNER)
                if self._match(TokenType.KEYWORD_JOIN):
                    tbl, _ = self._parse_full_identifier_safe()
                    j_node = JoinNode(type=jt, table=tbl)
                    self._match(TokenType.KEYWORD_AS); al = self._match(TokenType.IDENTIFIER)
                    if al: j_node.alias = self._get_text(al)
                    self._consume(TokenType.KEYWORD_ON, "Expected ON")
                    cond = self._parse_expression()
                    j_node.on_condition = cond
                    if isinstance(cond, BinaryExpressionNode):
                        j_node.on_left, j_node.on_right = cond.left, cond.right
                    stmt.joins.append(j_node)
                else: break
        else:
            # 💡 只有在全為常數投影時才允許省略 FROM
            needs_from = stmt.is_select_star or any(not isinstance(c, LiteralNode) for c in stmt.columns)
            if needs_from:
                self._consume(TokenType.KEYWORD_FROM, "Expected FROM")

        # 其餘子句
        if self._match(TokenType.KEYWORD_WHERE):
            stmt.where_condition = self._parse_expression()
        if self._match(TokenType.KEYWORD_GROUP):
            self._consume(TokenType.KEYWORD_BY, "Expected BY after GROUP")
            while True:
                stmt.group_by_cols.append(self._parse_expression())
                if not self._match(TokenType.SYMBOL_COMMA): break
        if self._match(TokenType.KEYWORD_HAVING):
            stmt.having_condition = self._parse_expression()
        if self._match(TokenType.KEYWORD_ORDER):
            self._consume(TokenType.KEYWORD_BY, "Expected BY after ORDER")
            while True:
                col_expr = self._parse_expression()
                direction = "ASC"
                if self._match(TokenType.KEYWORD_DESC): direction = "DESC"
                elif self._match(TokenType.KEYWORD_ASC): direction = "ASC"
                stmt.order_by_terms.append(OrderByNode(column=col_expr, direction=direction))
                if not self._match(TokenType.SYMBOL_COMMA): break

        return stmt

    # --- 3. DML 解析 ---

    def _parse_update(self):
        stmt = UpdateStatement()
        self._consume(TokenType.KEYWORD_UPDATE, "Expected UPDATE")
        stmt.table, _ = self._parse_full_identifier_safe()
        self._consume(TokenType.KEYWORD_SET, "Expected SET")
        while True:
            col, _ = self._parse_full_identifier_safe()
            self._consume(TokenType.SYMBOL_EQUAL, "Expected =")
            val = self._parse_expression()
            stmt.set_clauses.append(AssignmentNode(column=col, expression=val))
            if not self._match(TokenType.SYMBOL_COMMA): break
        # 🛡️ ZTA 強制性報錯訊息
        self._consume(TokenType.KEYWORD_WHERE, "WHERE clause is mandatory for UPDATE/DELETE")
        stmt.where_condition = self._parse_expression()
        return stmt

    def _parse_delete(self):
        stmt = DeleteStatement()
        self._consume(TokenType.KEYWORD_DELETE, "Expected DELETE")
        self._match(TokenType.KEYWORD_FROM)
        stmt.table, _ = self._parse_full_identifier_safe()
        # 🛡️ ZTA 強制性報錯訊息
        self._consume(TokenType.KEYWORD_WHERE, "WHERE clause is mandatory for UPDATE/DELETE")
        stmt.where_condition = self._parse_expression()
        return stmt

    def _parse_insert(self):
        stmt = InsertStatement()
        self._consume(TokenType.KEYWORD_INSERT, "Expected INSERT")
        self._consume(TokenType.KEYWORD_INTO, "Expected INTO")
        stmt.table, _ = self._parse_full_identifier_safe()
        if self._match(TokenType.SYMBOL_LPAREN):
            while True:
                col, _ = self._parse_full_identifier_safe()
                stmt.columns.append(col)
                if not self._match(TokenType.SYMBOL_COMMA): break
            self._consume(TokenType.SYMBOL_RPAREN, "Unclosed bracket")
        self._consume(TokenType.KEYWORD_VALUES, "Expected VALUES")
        self._consume(TokenType.SYMBOL_LPAREN, "Expected (")
        while True:
            stmt.values.append(self._parse_expression())
            if not self._match(TokenType.SYMBOL_COMMA): break
        self._consume(TokenType.SYMBOL_RPAREN, "Expected )")
        return stmt

    def _parse_bulk_insert(self):
        self._advance() 
        self._consume(TokenType.KEYWORD_INSERT, "Expected INSERT")
        self._consume(TokenType.KEYWORD_INTO, "Expected INTO")
        stmt = SqlBulkCopyStatement()
        stmt.table, _ = self._parse_full_identifier_safe()
        return stmt

    # --- 7. 表達式解析引擎 ---

    def _parse_expression(self): return self._parse_logical_or()
    def _parse_logical_or(self):
        node = self._parse_logical_and()
        while self._match(TokenType.KEYWORD_OR):
            node = BinaryExpressionNode(left=node, operator="OR", right=self._parse_logical_and())
        return node
    def _parse_logical_and(self):
        node = self._parse_comparison()
        while self._match(TokenType.KEYWORD_AND):
            node = BinaryExpressionNode(left=node, operator="AND", right=self._parse_comparison())
        return node

    def _parse_comparison(self):
        node = self._parse_term()
        while True:
            if self._match(TokenType.KEYWORD_IN):
                self._consume(TokenType.SYMBOL_LPAREN, "Expected ( after IN")
                if self._peek() and self._peek().type == TokenType.KEYWORD_SELECT:
                    right_node = self._parse_select()
                else:
                    right_node = []
                    while True:
                        right_node.append(self._parse_expression())
                        if not self._match(TokenType.SYMBOL_COMMA): break
                self._consume(TokenType.SYMBOL_RPAREN, "Expected ) after IN list")
                node = BinaryExpressionNode(left=node, operator="IN", right=right_node)
                continue
            op_tok = self._match(
                TokenType.SYMBOL_EQUAL, TokenType.SYMBOL_GT, TokenType.SYMBOL_LT,
                TokenType.SYMBOL_GE, TokenType.SYMBOL_LE, TokenType.SYMBOL_NE
            )
            if op_tok:
                node = BinaryExpressionNode(left=node, operator=self._get_text(op_tok), right=self._parse_term())
            else: break
        return node

    def _parse_term(self):
        node = self._parse_factor()
        while self._match(TokenType.SYMBOL_PLUS):
            node = BinaryExpressionNode(left=node, operator="+", right=self._parse_factor())
        return node
    def _parse_factor(self):
        node = self._parse_primary()
        while self._match(TokenType.SYMBOL_ASTERISK):
            node = BinaryExpressionNode(left=node, operator="*", right=self._parse_primary())
        return node

    def _parse_primary(self):
        # 💡 Issue #33: CASE 入口
        if self._match(TokenType.KEYWORD_CASE):
            return self._parse_case_expression()

        if self._match(TokenType.KEYWORD_EXISTS):
            self._consume(TokenType.SYMBOL_LPAREN, "Expected ( after EXISTS")
            subquery = self._parse_select()
            self._consume(TokenType.SYMBOL_RPAREN, "Expected ) after EXISTS")
            return FunctionCallNode(name="EXISTS", args=[subquery])

        if self._match(TokenType.SYMBOL_LPAREN):
            if self._peek() and self._peek().type == TokenType.KEYWORD_SELECT:
                node = self._parse_select()
            else: node = self._parse_expression()
            self._consume(TokenType.SYMBOL_RPAREN, "Expected )")
            return node
        
        if self._match(TokenType.SYMBOL_ASTERISK):
            return IdentifierNode(name="*", qualifiers=[])

        tok = self._peek()
        # 💡 精準報錯：對齊測試要求
        if tok and tok.type == TokenType.SYMBOL_COMMA:
            raise SyntaxError("Expected identifier")
        
        if not tok: raise SyntaxError("Unexpected end of input")
        
        if tok.type == TokenType.NUMERIC_LITERAL:
            return LiteralNode(value=self._get_text(self._advance()), type=tok.type)
        if tok.type == TokenType.STRING_LITERAL:
            return LiteralNode(value=self._get_text(self._advance()).strip("'"), type=tok.type)
        
        if tok.type == TokenType.IDENTIFIER:
            id_node, is_func = self._parse_full_identifier_safe()
            if self._match(TokenType.SYMBOL_DOT):
                if self._match(TokenType.SYMBOL_ASTERISK):
                    self._is_qual_star = True
                    return id_node
                raise SyntaxError("Expected * after .")
            if is_func:
                self._consume(TokenType.SYMBOL_LPAREN, "Expected (")
                args = []
                if self._peek() and self._peek().type != TokenType.SYMBOL_RPAREN:
                    while True:
                        args.append(self._parse_expression())
                        if not self._match(TokenType.SYMBOL_COMMA): break
                self._consume(TokenType.SYMBOL_RPAREN, "Expected )")
                return FunctionCallNode(name=id_node.name, args=args)
            return id_node
        
        raise SyntaxError(f"Unexpected expression token: {self._get_text(tok)}")

    def _parse_case_expression(self):
        """💡 Issue #33: 遞迴解析 CASE 分支"""
        input_expr = None
        if self._peek() and self._peek().type != TokenType.KEYWORD_WHEN:
            input_expr = self._parse_expression()
        
        case_node = CaseExpressionNode(input_expr=input_expr)
        while self._match(TokenType.KEYWORD_WHEN):
            when_expr = self._parse_expression()
            self._consume(TokenType.KEYWORD_THEN, "Expected THEN after WHEN")
            then_expr = self._parse_expression()
            case_node.branches.append((when_expr, then_expr))
        
        if not case_node.branches:
            raise SyntaxError("CASE expression must have at least one WHEN branch")
        if self._match(TokenType.KEYWORD_ELSE):
            case_node.else_expr = self._parse_expression()
        self._consume(TokenType.KEYWORD_END, "Expected END at the end of CASE")
        return case_node

    def _parse_full_identifier_safe(self):
        parts = []
        while True:
            parts.append(self._get_text(self._consume(TokenType.IDENTIFIER, "Expected identifier")))
            if self._peek() and self._peek().type == TokenType.SYMBOL_DOT:
                if self._peek(1) and self._peek(1).type == TokenType.SYMBOL_ASTERISK: break
                self._advance()
            else: break
        is_func = (self._peek() and self._peek().type == TokenType.SYMBOL_LPAREN)
        name = parts.pop()
        return IdentifierNode(name=name, qualifiers=parts), is_func