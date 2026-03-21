from birdeye.lexer import TokenType
from birdeye.ast import (
    SelectStatement, UpdateStatement, DeleteStatement, InsertStatement,
    SqlBulkCopyStatement, IdentifierNode, LiteralNode,
    BinaryExpressionNode, FunctionCallNode, JoinNode, AssignmentNode,
    OrderByNode, CaseExpressionNode, BetweenExpressionNode, CastExpressionNode,
    UnionStatement, CTENode, TruncateStatement, DeclareStatement, ApplyNode
)

class Parser:
    """
    語法分析器：將 Token 序列轉換為抽象語法樹 (AST)。
    v1.10.0: 支援 TRUNCATE TABLE、CTE、UNION、CAST 等完整語法。
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
        
        ctes = []
        if tok.type == TokenType.KEYWORD_WITH:
            ctes = self._parse_ctes()
            tok = self._peek()

        if not tok: raise SyntaxError("Unexpected end of input")

        if tok.type == TokenType.KEYWORD_SELECT:
            stmt = self._parse_select_with_set_ops()
            if ctes: stmt.ctes = ctes
        elif tok.type == TokenType.KEYWORD_UPDATE:
            stmt = self._parse_update()
            if ctes: stmt.ctes = ctes
        elif tok.type == TokenType.KEYWORD_DELETE:
            stmt = self._parse_delete()
            if ctes: stmt.ctes = ctes
        elif tok.type == TokenType.KEYWORD_INSERT: stmt = self._parse_insert()
        elif tok.type == TokenType.KEYWORD_TRUNCATE: stmt = self._parse_truncate()
        elif tok.type == TokenType.KEYWORD_DECLARE: stmt = self._parse_declare()
        elif tok.type == TokenType.IDENTIFIER and self._get_text(tok).upper() == "BULK":
            stmt = self._parse_bulk_insert()
        else:
            raise SyntaxError(f"Unexpected token: {self._get_text(tok)}")

        # 允許尾端分號
        self._match(TokenType.SYMBOL_SEMICOLON)

        peek = self._peek()
        if peek and peek.type != TokenType.EOF:
            raise SyntaxError(f"Unexpected token: {self._get_text(peek)}")
        return stmt

    # --- 2. CTE 解析 ---

    def _parse_ctes(self):
        self._consume(TokenType.KEYWORD_WITH, "Expected WITH")
        ctes = []
        while True:
            name_tok = self._consume(TokenType.IDENTIFIER, "Expected CTE name")
            name = self._get_text(name_tok).upper()
            self._consume(TokenType.KEYWORD_AS, "Expected AS after CTE name")
            self._consume(TokenType.SYMBOL_LPAREN, "Expected ( before CTE query")
            query = self._parse_select_with_set_ops()
            self._consume(TokenType.SYMBOL_RPAREN, "Expected ) after CTE query")
            ctes.append(CTENode(name=name, query=query))
            if not self._match(TokenType.SYMBOL_COMMA): break
        return ctes

    # --- 3. DQL 解析: SELECT & UNION ---

    def _parse_select_with_set_ops(self):
        node = self._parse_single_select()
        while True:
            if self._match(TokenType.KEYWORD_UNION):
                op = "UNION"
                if self._match(TokenType.KEYWORD_ALL): op = "UNION ALL"
                right = self._parse_single_select()
                node = UnionStatement(left=node, operator=op, right=right)
            elif self._match(TokenType.KEYWORD_INTERSECT):
                right = self._parse_single_select()
                node = UnionStatement(left=node, operator="INTERSECT", right=right)
            elif self._match(TokenType.KEYWORD_EXCEPT):
                right = self._parse_single_select()
                node = UnionStatement(left=node, operator="EXCEPT", right=right)
            else: break
        return node

    def _parse_single_select(self):
        stmt = SelectStatement()
        self._consume(TokenType.KEYWORD_SELECT, "Expected SELECT")

        if self._match(TokenType.KEYWORD_DISTINCT):
            stmt.is_distinct = True

        if self._match(TokenType.KEYWORD_TOP):
            num_tok = self._match(TokenType.NUMERIC_LITERAL)
            if not num_tok: raise SyntaxError("Expected numeric literal after TOP")
            stmt.top_count = int(num_tok.value)
            if self._match(TokenType.KEYWORD_PERCENT):
                stmt.top_percent = True

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

        # Issue #52: 解析 SELECT ... INTO #table FROM ...
        if self._match(TokenType.KEYWORD_INTO):
            stmt.into_table, _ = self._parse_full_identifier_safe()

        if self._match(TokenType.KEYWORD_FROM):
            # 衍生資料表: FROM (SELECT ...) alias
            if self._peek() and self._peek().type == TokenType.SYMBOL_LPAREN:
                self._advance()
                subq = self._parse_select_with_set_ops()
                self._consume(TokenType.SYMBOL_RPAREN, "Expected ) after derived table")
                self._match(TokenType.KEYWORD_AS)
                alias_tok = self._consume(TokenType.IDENTIFIER, "Derived table must have an alias")
                stmt.table = subq
                stmt.table_alias = self._get_text(alias_tok)
            else:
                stmt.table, _ = self._parse_full_identifier_safe()
                self._match(TokenType.KEYWORD_AS)
                alias_tok = self._match(TokenType.IDENTIFIER)
                if alias_tok: stmt.table_alias = self._get_text(alias_tok)

            if self._peek() and self._peek().type == TokenType.SYMBOL_COMMA: raise SyntaxError("Expected FROM")

            while True:
                # Issue #53: 檢查 CROSS APPLY / OUTER APPLY
                apply_type = None
                if self._match(TokenType.KEYWORD_CROSS):
                    if self._peek() and self._peek().type == TokenType.KEYWORD_APPLY:
                        self._advance(); apply_type = "CROSS"
                    elif self._peek() and self._peek().type == TokenType.KEYWORD_JOIN:
                        # Issue #62: CROSS JOIN（笛卡兒積）
                        self._advance()
                        tbl, _ = self._parse_full_identifier_safe()
                        j_node = JoinNode(type="CROSS", table=tbl)
                        self._match(TokenType.KEYWORD_AS); al = self._match(TokenType.IDENTIFIER)
                        if al: j_node.alias = self._get_text(al)
                        stmt.joins.append(j_node)
                        continue
                    else:
                        raise SyntaxError("Expected APPLY or JOIN after CROSS")
                elif self._match(TokenType.KEYWORD_OUTER):
                    if self._peek() and self._peek().type == TokenType.KEYWORD_APPLY:
                        self._advance(); apply_type = "OUTER"
                    else:
                        raise SyntaxError("Expected APPLY after OUTER")
                if apply_type:
                    self._consume(TokenType.SYMBOL_LPAREN, "Expected ( after APPLY")
                    subquery = self._parse_select_with_set_ops()
                    self._consume(TokenType.SYMBOL_RPAREN, "Expected ) after APPLY subquery")
                    self._match(TokenType.KEYWORD_AS)
                    al = self._match(TokenType.IDENTIFIER)
                    alias = self._get_text(al) if al else None
                    stmt.applies.append(ApplyNode(type=apply_type, subquery=subquery, alias=alias))
                    continue

                jt = "INNER"
                if self._match(TokenType.KEYWORD_LEFT): jt = "LEFT"
                elif self._match(TokenType.KEYWORD_RIGHT): jt = "RIGHT"
                elif self._match(TokenType.KEYWORD_FULL): jt = "FULL"  # Issue #63
                self._match(TokenType.KEYWORD_INNER)
                self._match(TokenType.KEYWORD_OUTER)  # 吸收可選的 OUTER
                if self._match(TokenType.KEYWORD_JOIN):
                    # JOIN 子查詢: JOIN (SELECT ...) alias ON ...
                    if self._peek() and self._peek().type == TokenType.SYMBOL_LPAREN:
                        self._advance()
                        subq = self._parse_select_with_set_ops()
                        self._consume(TokenType.SYMBOL_RPAREN, "Expected ) after JOIN subquery")
                        self._match(TokenType.KEYWORD_AS)
                        al_tok = self._consume(TokenType.IDENTIFIER, "JOIN subquery must have an alias")
                        j_node = JoinNode(type=jt, table=subq)
                        j_node.alias = self._get_text(al_tok)
                    else:
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
            needs_from = stmt.is_select_star or any(self._contains_identifier(c) for c in stmt.columns)
            if needs_from: self._consume(TokenType.KEYWORD_FROM, "Expected FROM")

        if self._match(TokenType.KEYWORD_WHERE): stmt.where_condition = self._parse_expression()
        if self._match(TokenType.KEYWORD_GROUP):
            self._consume(TokenType.KEYWORD_BY, "Expected BY after GROUP")
            while True:
                stmt.group_by_cols.append(self._parse_expression())
                if not self._match(TokenType.SYMBOL_COMMA): break
        if self._match(TokenType.KEYWORD_HAVING): stmt.having_condition = self._parse_expression()
        if self._match(TokenType.KEYWORD_ORDER):
            self._consume(TokenType.KEYWORD_BY, "Expected BY after ORDER")
            while True:
                col_expr = self._parse_expression()
                direction = "ASC"
                if self._match(TokenType.KEYWORD_DESC): direction = "DESC"
                elif self._match(TokenType.KEYWORD_ASC): direction = "ASC"
                stmt.order_by_terms.append(OrderByNode(column=col_expr, direction=direction))
                if not self._match(TokenType.SYMBOL_COMMA): break
        # Issue #64: OFFSET n ROWS [FETCH NEXT n ROWS ONLY]
        if self._match(TokenType.KEYWORD_OFFSET):
            num_tok = self._consume(TokenType.NUMERIC_LITERAL, "Expected number after OFFSET")
            stmt.offset_count = int(num_tok.value)
            self._match(TokenType.KEYWORD_ROWS)  # 吸收可選 ROWS
            if self._match(TokenType.KEYWORD_FETCH):
                self._match(TokenType.KEYWORD_NEXT)  # 吸收可選 NEXT
                fetch_tok = self._consume(TokenType.NUMERIC_LITERAL, "Expected number after FETCH")
                stmt.fetch_count = int(fetch_tok.value)
                self._match(TokenType.KEYWORD_ROWS)  # 吸收可選 ROWS
                self._match(TokenType.KEYWORD_ONLY)  # 吸收可選 ONLY
        return stmt

    def _contains_identifier(self, node) -> bool:
        if isinstance(node, IdentifierNode): return True
        if isinstance(node, BinaryExpressionNode): return self._contains_identifier(node.left) or self._contains_identifier(node.right)
        if isinstance(node, FunctionCallNode): return any(self._contains_identifier(arg) for arg in node.args)
        if isinstance(node, CaseExpressionNode):
            if node.input_expr and self._contains_identifier(node.input_expr): return True
            for w, t in node.branches:
                if self._contains_identifier(w) or self._contains_identifier(t): return True
            return self._contains_identifier(node.else_expr) if node.else_expr else False
        return False

    # --- 4. DML 解析 ---

    def _parse_truncate(self):
        self._consume(TokenType.KEYWORD_TRUNCATE, "Expected TRUNCATE")
        self._consume(TokenType.KEYWORD_TABLE, "Expected TABLE after TRUNCATE")
        table, _ = self._parse_full_identifier_safe()
        return TruncateStatement(table=table)

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
        self._consume(TokenType.KEYWORD_WHERE, "WHERE clause is mandatory for UPDATE/DELETE")
        stmt.where_condition = self._parse_expression()
        return stmt

    def _parse_delete(self):
        stmt = DeleteStatement()
        self._consume(TokenType.KEYWORD_DELETE, "Expected DELETE")
        self._match(TokenType.KEYWORD_FROM)
        stmt.table, _ = self._parse_full_identifier_safe()
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
        # Issue #57: INSERT-SELECT
        if self._peek() and self._peek().type == TokenType.KEYWORD_SELECT:
            stmt.source = self._parse_select_with_set_ops()
            return stmt
        # Issue #58: Multi-row VALUES
        self._consume(TokenType.KEYWORD_VALUES, "Expected VALUES")
        while True:
            self._consume(TokenType.SYMBOL_LPAREN, "Expected (")
            row = []
            while True:
                row.append(self._parse_expression())
                if not self._match(TokenType.SYMBOL_COMMA): break
            self._consume(TokenType.SYMBOL_RPAREN, "Expected )")
            stmt.value_rows.append(row)
            if not self._match(TokenType.SYMBOL_COMMA): break
        # 向後相容：保留 values 指向第一列
        stmt.values = stmt.value_rows[0] if stmt.value_rows else []
        return stmt

    def _parse_bulk_insert(self):
        self._advance()
        self._consume(TokenType.KEYWORD_INSERT, "Expected INSERT")
        self._consume(TokenType.KEYWORD_INTO, "Expected INTO")
        stmt = SqlBulkCopyStatement()
        stmt.table, _ = self._parse_full_identifier_safe()
        return stmt

    def _parse_declare(self):
        """解析 DECLARE @var TYPE [(size)] [= default_value]  (Issue #51)"""
        self._consume(TokenType.KEYWORD_DECLARE, "Expected DECLARE")
        var_tok = self._consume(TokenType.IDENTIFIER, "Expected variable name after DECLARE")
        var_name = self._get_text(var_tok)
        type_tok = self._consume(TokenType.IDENTIFIER, "Expected type after variable name")
        var_type = self._get_text(type_tok).upper()
        # 吸收可選的長度參數，如 NVARCHAR(50)
        if self._match(TokenType.SYMBOL_LPAREN):
            while self._peek() and self._peek().type != TokenType.SYMBOL_RPAREN:
                self._advance()
            self._consume(TokenType.SYMBOL_RPAREN, "Expected ) after type size")
        # 吸收可選的預設值，如 = 0
        default_value = None
        if self._match(TokenType.SYMBOL_EQUAL):
            default_value = self._parse_expression()
        return DeclareStatement(var_name=var_name, var_type=var_type, default_value=default_value)

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
            if self._match(TokenType.KEYWORD_IS):
                is_not = False
                if self._match(TokenType.KEYWORD_NOT): is_not = True
                self._consume(TokenType.KEYWORD_NULL, "Expected NULL after IS")
                op = "IS NOT NULL" if is_not else "IS NULL"
                node = BinaryExpressionNode(left=node, operator=op, right=LiteralNode(value="NULL", type=TokenType.IDENTIFIER))
                continue
            if self._match(TokenType.KEYWORD_BETWEEN):
                low = self._parse_term()
                self._consume(TokenType.KEYWORD_AND, "Expected AND after BETWEEN low")
                high = self._parse_term()
                node = BetweenExpressionNode(expr=node, low=low, high=high, is_not=False)
                continue
            if self._match(TokenType.KEYWORD_NOT):
                if self._match(TokenType.KEYWORD_LIKE):
                    node = BinaryExpressionNode(left=node, operator="NOT LIKE", right=self._parse_term())
                elif self._match(TokenType.KEYWORD_BETWEEN):
                    low = self._parse_term()
                    self._consume(TokenType.KEYWORD_AND, "Expected AND after BETWEEN low")
                    high = self._parse_term()
                    node = BetweenExpressionNode(expr=node, low=low, high=high, is_not=True)
                elif self._match(TokenType.KEYWORD_IN):
                    # Issue #60: NOT IN
                    self._consume(TokenType.SYMBOL_LPAREN, "Expected ( after NOT IN")
                    if self._peek() and self._peek().type == TokenType.KEYWORD_SELECT:
                        right_node = self._parse_select_with_set_ops()
                    else:
                        right_node = []
                        while True:
                            right_node.append(self._parse_expression())
                            if not self._match(TokenType.SYMBOL_COMMA): break
                    self._consume(TokenType.SYMBOL_RPAREN, "Expected ) after NOT IN list")
                    node = BinaryExpressionNode(left=node, operator="NOT IN", right=right_node)
                else:
                    raise SyntaxError("Expected LIKE, BETWEEN, or IN after NOT")
                continue
            if self._match(TokenType.KEYWORD_LIKE):
                node = BinaryExpressionNode(left=node, operator="LIKE", right=self._parse_term())
                continue
            if self._match(TokenType.KEYWORD_IN):
                self._consume(TokenType.SYMBOL_LPAREN, "Expected ( after IN")
                if self._peek() and self._peek().type == TokenType.KEYWORD_SELECT:
                    right_node = self._parse_select_with_set_ops()
                else:
                    right_node = []
                    while True:
                        right_node.append(self._parse_expression())
                        if not self._match(TokenType.SYMBOL_COMMA): break
                self._consume(TokenType.SYMBOL_RPAREN, "Expected ) after IN list")
                node = BinaryExpressionNode(left=node, operator="IN", right=right_node)
                continue
            
            # 💡 TDD New: 支援比較運算子後接 ANY 或 ALL
            op_tok = self._match(
                TokenType.SYMBOL_EQUAL, TokenType.SYMBOL_GT, TokenType.SYMBOL_LT,
                TokenType.SYMBOL_GE, TokenType.SYMBOL_LE, TokenType.SYMBOL_NE
            )
            if op_tok:
                op_str = self._get_text(op_tok)
                mod_tok = self._match(TokenType.KEYWORD_ANY, TokenType.KEYWORD_ALL)
                if mod_tok:
                    op_str = f"{op_str} {self._get_text(mod_tok).upper()}"
                    self._consume(TokenType.SYMBOL_LPAREN, f"Expected ( after {op_str}")
                    if self._peek() and self._peek().type == TokenType.KEYWORD_SELECT:
                        right_node = self._parse_select_with_set_ops()
                    else:
                        right_node = []
                        while True:
                            right_node.append(self._parse_expression())
                            if not self._match(TokenType.SYMBOL_COMMA): break
                        if not right_node: raise SyntaxError(f"Expected expression list after {op_str}")
                    self._consume(TokenType.SYMBOL_RPAREN, f"Expected ) after {op_str} list")
                    node = BinaryExpressionNode(left=node, operator=op_str, right=right_node)
                else:
                    node = BinaryExpressionNode(left=node, operator=op_str, right=self._parse_term())
            else: break
        return node

    def _parse_term(self):
        node = self._parse_factor()
        while True:
            if self._match(TokenType.SYMBOL_PLUS):
                node = BinaryExpressionNode(left=node, operator="+", right=self._parse_factor())
            elif self._match(TokenType.SYMBOL_MINUS):
                node = BinaryExpressionNode(left=node, operator="-", right=self._parse_factor())
            else: break
        return node
        
    def _parse_factor(self):
        node = self._parse_primary()
        while True:
            if self._match(TokenType.SYMBOL_ASTERISK):
                node = BinaryExpressionNode(left=node, operator="*", right=self._parse_primary())
            elif self._match(TokenType.SYMBOL_SLASH):
                node = BinaryExpressionNode(left=node, operator="/", right=self._parse_primary())
            elif self._match(TokenType.SYMBOL_PERCENT):
                node = BinaryExpressionNode(left=node, operator="%", right=self._parse_primary())
            elif self._match(TokenType.SYMBOL_AMPERSAND):
                node = BinaryExpressionNode(left=node, operator="&", right=self._parse_primary())
            elif self._match(TokenType.SYMBOL_PIPE):
                node = BinaryExpressionNode(left=node, operator="|", right=self._parse_primary())
            elif self._match(TokenType.SYMBOL_CARET):
                node = BinaryExpressionNode(left=node, operator="^", right=self._parse_primary())
            else: break
        return node

    def _parse_primary(self):
        tok = self._peek()
        if not tok: raise SyntaxError("Unexpected end of input")

        if tok.type == TokenType.KEYWORD_CAST:
            self._advance()
            self._consume(TokenType.SYMBOL_LPAREN, "Expected ( after CAST")
            expr = self._parse_expression()
            self._consume(TokenType.KEYWORD_AS, "Expected AS in CAST")
            type_tok = self._consume(TokenType.IDENTIFIER, "Expected target type in CAST")
            target_type = self._get_text(type_tok).upper()
            # 吸收可選的型別長度，如 VARCHAR(10) 或 DECIMAL(18,2)
            if self._match(TokenType.SYMBOL_LPAREN):
                while self._peek() and self._peek().type != TokenType.SYMBOL_RPAREN:
                    self._advance()
                self._consume(TokenType.SYMBOL_RPAREN, "Expected ) after type size")
            self._consume(TokenType.SYMBOL_RPAREN, "Expected ) after CAST type")
            return CastExpressionNode(expr=expr, target_type=target_type)

        if tok.type == TokenType.KEYWORD_CONVERT:
            self._advance()
            self._consume(TokenType.SYMBOL_LPAREN, "Expected ( after CONVERT")
            type_tok = self._consume(TokenType.IDENTIFIER, "Expected target type in CONVERT")
            target_type = self._get_text(type_tok).upper()
            # 吸收可選的型別長度，如 VARCHAR(20)
            if self._match(TokenType.SYMBOL_LPAREN):
                while self._peek() and self._peek().type != TokenType.SYMBOL_RPAREN:
                    self._advance()
                self._consume(TokenType.SYMBOL_RPAREN, "Expected ) after type size")
            self._consume(TokenType.SYMBOL_COMMA, "Expected comma in CONVERT")
            expr = self._parse_expression()
            # 吸收可選的第三個參數 (style)
            if self._match(TokenType.SYMBOL_COMMA):
                self._parse_expression()  # consume style arg
            self._consume(TokenType.SYMBOL_RPAREN, "Expected ) after CONVERT")
            return CastExpressionNode(expr=expr, target_type=target_type, is_convert=True)

        if self._match(TokenType.KEYWORD_CASE):
            return self._parse_case_expression()

        if self._match(TokenType.KEYWORD_EXISTS):
            self._consume(TokenType.SYMBOL_LPAREN, "Expected ( after EXISTS")
            subquery = self._parse_select_with_set_ops()
            self._consume(TokenType.SYMBOL_RPAREN, "Expected ) after EXISTS")
            return FunctionCallNode(name="EXISTS", args=[subquery])

        # Issue #61: NOT EXISTS / NOT (前置否定)
        if tok.type == TokenType.KEYWORD_NOT:
            self._advance()
            if self._match(TokenType.KEYWORD_EXISTS):
                self._consume(TokenType.SYMBOL_LPAREN, "Expected ( after NOT EXISTS")
                subquery = self._parse_select_with_set_ops()
                self._consume(TokenType.SYMBOL_RPAREN, "Expected ) after NOT EXISTS")
                return FunctionCallNode(name="NOT EXISTS", args=[subquery])
            raise SyntaxError("Expected EXISTS after NOT")

        if self._match(TokenType.SYMBOL_LPAREN):
            if self._peek() and self._peek().type == TokenType.KEYWORD_SELECT:
                node = self._parse_select_with_set_ops()
            else: node = self._parse_expression()
            self._consume(TokenType.SYMBOL_RPAREN, "Expected )")
            return node
        
        # Issue #Boundary: 一元位元補數 (bitwise NOT)，如 ~1
        if tok.type == TokenType.SYMBOL_TILDE:
            self._advance()
            operand = self._parse_primary()
            return BinaryExpressionNode(left=LiteralNode(value="0", type=TokenType.NUMERIC_LITERAL), operator="~", right=operand)

        if self._match(TokenType.SYMBOL_ASTERISK): return IdentifierNode(name="*", qualifiers=[])

        if tok.type == TokenType.SYMBOL_COMMA: raise SyntaxError("Expected identifier")

        # Issue #Boundary: 支援一元負號 (unary minus)，如 -1, -3.14
        if tok.type == TokenType.SYMBOL_MINUS:
            self._advance()
            operand = self._parse_primary()
            if isinstance(operand, LiteralNode) and operand.type == TokenType.NUMERIC_LITERAL:
                operand.value = "-" + operand.value
                return operand
            return BinaryExpressionNode(left=LiteralNode(value="0", type=TokenType.NUMERIC_LITERAL), operator="-", right=operand)

        if tok.type == TokenType.NUMERIC_LITERAL: return LiteralNode(value=self._get_text(self._advance()), type=tok.type)
        if tok.type == TokenType.STRING_LITERAL: return LiteralNode(value=self._get_text(self._advance()).strip("'"), type=tok.type)
        # Issue #56: NULL 字面值
        if tok.type == TokenType.KEYWORD_NULL:
            self._advance()
            return LiteralNode(value="NULL", type=TokenType.KEYWORD_NULL)
        
        # 關鍵字也可能作為函數名稱使用 (如 LEFT、RIGHT、DAY、MONTH、YEAR)
        _keyword_functions = {
            TokenType.KEYWORD_LEFT, TokenType.KEYWORD_RIGHT,
        }
        if tok.type in _keyword_functions and self._peek(1) and self._peek(1).type == TokenType.SYMBOL_LPAREN:
            func_name = self._get_text(self._advance()).upper()
            self._consume(TokenType.SYMBOL_LPAREN, "Expected (")
            args = []
            if self._peek() and self._peek().type != TokenType.SYMBOL_RPAREN:
                while True:
                    args.append(self._parse_expression())
                    if not self._match(TokenType.SYMBOL_COMMA): break
            self._consume(TokenType.SYMBOL_RPAREN, "Expected )")
            return FunctionCallNode(name=func_name, args=args)

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
                # 吸收 COUNT(DISTINCT ...) 中的 DISTINCT 關鍵字
                self._match(TokenType.KEYWORD_DISTINCT)
                if self._peek() and self._peek().type != TokenType.SYMBOL_RPAREN:
                    while True:
                        args.append(self._parse_expression())
                        if not self._match(TokenType.SYMBOL_COMMA): break
                self._consume(TokenType.SYMBOL_RPAREN, "Expected )")
                return FunctionCallNode(name=id_node.name, args=args)
            return id_node
        
        raise SyntaxError(f"Unexpected expression token: {self._get_text(tok)}")

    def _parse_case_expression(self):
        input_expr = None
        if self._peek() and self._peek().type != TokenType.KEYWORD_WHEN:
            input_expr = self._parse_expression()
        
        case_node = CaseExpressionNode(input_expr=input_expr)
        while self._match(TokenType.KEYWORD_WHEN):
            when_expr = self._parse_expression()
            self._consume(TokenType.KEYWORD_THEN, "Expected THEN after WHEN")
            then_expr = self._parse_expression()
            case_node.branches.append((when_expr, then_expr))
        
        if not case_node.branches: raise SyntaxError("CASE expression must have at least one WHEN branch")
        if self._match(TokenType.KEYWORD_ELSE): case_node.else_expr = self._parse_expression()
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
