from birdeye.ast import (
    SelectStatement, UpdateStatement, DeleteStatement, InsertStatement,
    SqlBulkCopyStatement, IdentifierNode, BinaryExpressionNode, 
    FunctionCallNode, LiteralNode, OrderByNode
)

class SemanticError(Exception):
    """語意錯誤：當 SQL 語法正確但邏輯/權限不符元數據時拋出"""
    pass

class Binder:
    """
    語意綁定器：執行標識符解析、星號展開與 ZTA 政策強制執行。
    v1.6.2: 實作 Issue #31 - 聚合函數校驗與 GROUP BY 語意完整性檢查。
    """
    def __init__(self, registry):
        self.registry = registry
        self.current_scopes = {}    # 作用域名稱 (別名或表名) -> 原始大寫表名
        self.active_tables = []     # 當前查詢涉及的原始表名清單
        self.nullable_scopes = set() # 標記為 Nullable 的作用域 (用於 Join)
        
        # 💡 Issue #31: 聚合檢查狀態
        self._aggregate_funcs = {"SUM", "COUNT", "AVG", "MIN", "MAX"}

    def bind(self, stmt):
        """主入口：執行語意檢查並返回綁定後的 AST"""
        self.current_scopes = {}
        self.active_tables = []
        self.nullable_scopes = set()

        if isinstance(stmt, SelectStatement):
            self._bind_select(stmt)
        elif isinstance(stmt, UpdateStatement):
            self._bind_update(stmt)
        elif isinstance(stmt, DeleteStatement):
            self._bind_delete(stmt)
        elif isinstance(stmt, InsertStatement):
            self._bind_insert(stmt)
        elif isinstance(stmt, SqlBulkCopyStatement):
            self._bind_bulk_insert(stmt)
        return stmt

    # --- 核心語句綁定邏輯 ---

    def _bind_select(self, stmt):
        # 1. 註冊作用域 (FROM & JOIN)
        self._register_scope(stmt.table, stmt.table_alias)
        for join in stmt.joins:
            if join.type == "LEFT":
                self.nullable_scopes.add(join.alias.upper() if join.alias else join.table.name.upper())
            elif join.type == "RIGHT":
                self.nullable_scopes.update(self.current_scopes.keys())
            self._register_scope(join.table, join.alias)
            if join.on_condition:
                self._visit_expression(join.on_condition)

        # 2. 處理星號展開 (SELECT *)
        if stmt.is_select_star:
            self._expand_global_star(stmt)
        for prefix in stmt.star_prefixes:
            self._expand_qualified_star(stmt, prefix)

        # 3. 🛡️ ZTA 政策：檢查 WHERE 子句 (不允許聚合函數)
        if stmt.where_condition:
            if self._has_aggregate(stmt.where_condition):
                raise SemanticError("Aggregate functions are not allowed in WHERE clause")
            self._visit_expression(stmt.where_condition)

        # 4. 綁定 GROUP BY 欄位
        for g_col in stmt.group_by_cols:
            self._visit_expression(g_col)

        # 5. 🛡️ ZTA 政策：執行聚合完整性校驗
        # 如果有 GROUP BY，或者 SELECT 中有任何聚合函數，則啟動嚴格校驗
        is_agg_query = len(stmt.group_by_cols) > 0 or any(self._has_aggregate(c) for c in stmt.columns)
        
        for col_expr in stmt.columns:
            self._visit_expression(col_expr)
            if is_agg_query:
                self._validate_aggregate_integrity(col_expr, stmt.group_by_cols)

        # 6. 綁定 HAVING (支援聚合函數)
        if stmt.having_condition:
            self._visit_expression(stmt.having_condition)

        # 7. 綁定 ORDER BY
        for term in stmt.order_by_terms:
            self._visit_expression(term.column)

    def _bind_update(self, stmt):
        self._register_scope(stmt.table, stmt.table_alias)
        for clause in stmt.set_clauses:
            self._visit_expression(clause.column)
            self._visit_expression(clause.right) 
        if stmt.where_condition:
            self._visit_expression(stmt.where_condition)

    def _bind_delete(self, stmt):
        self._register_scope(stmt.table, stmt.table_alias)
        if stmt.where_condition:
            self._visit_expression(stmt.where_condition)

    def _bind_insert(self, stmt):
        self._register_scope(stmt.table, stmt.table_alias)
        for col in stmt.columns:
            self._visit_expression(col)
        for val in stmt.values:
            self._visit_expression(val)
        
        expected = len(stmt.columns) if stmt.columns else self.registry.get_column_count(stmt.table.name)
        actual = len(stmt.values)
        if expected != actual:
            raise SemanticError(f"Column count mismatch: Expected {expected}, got {actual}")

    def _bind_bulk_insert(self, stmt):
        if not self.registry.has_table(stmt.table.name):
            raise SemanticError(f"Table '{stmt.table.name}' not found")

    # --- 聚合輔助方法 ---

    def _has_aggregate(self, expr):
        """遞迴檢查表達式中是否包含聚合函數"""
        if isinstance(expr, FunctionCallNode):
            if expr.name.upper() in self._aggregate_funcs:
                return True
            return any(self._has_aggregate(arg) for arg in expr.args)
        elif isinstance(expr, BinaryExpressionNode):
            return self._has_aggregate(expr.left) or self._has_aggregate(expr.right)
        return False

    def _validate_aggregate_integrity(self, expr, group_by_cols):
        """
        🛡️ ZTA 核心校驗：確保非聚合欄位必須出現在 GROUP BY 中。
        """
        if self._has_aggregate(expr):
            return # 已經是聚合運算，安全
        
        if isinstance(expr, IdentifierNode):
            if expr.name == "*": return
            # 檢查此標識符是否在 GROUP BY 列表中 (比對名稱與限定符)
            found = False
            for g_col in group_by_cols:
                if isinstance(g_col, IdentifierNode):
                    if g_col.name.upper() == expr.name.upper() and g_col.qualifier == expr.qualifier:
                        found = True
                        break
            if not found:
                raise SemanticError(f"Column '{expr.name}' must appear in the GROUP BY clause or be used in an aggregate function")
        
        elif isinstance(expr, BinaryExpressionNode):
            self._validate_aggregate_integrity(expr.left, group_by_cols)
            self._validate_aggregate_integrity(expr.right, group_by_cols)
        
        elif isinstance(expr, FunctionCallNode):
            # 一般函數（非聚合）內部的所有參數也必須符合規則
            for arg in expr.args:
                self._validate_aggregate_integrity(arg, group_by_cols)

    # --- 標識符解析引擎 ---

    def _visit_expression(self, expr):
        if isinstance(expr, IdentifierNode):
            self._resolve_identifier(expr)
        elif isinstance(expr, BinaryExpressionNode):
            self._visit_expression(expr.left)
            self._visit_expression(expr.right)
        elif isinstance(expr, FunctionCallNode):
            for arg in expr.args:
                self._visit_expression(arg)
        elif isinstance(expr, LiteralNode):
            pass

    def _resolve_identifier(self, node):
        if node.name == "*": return
        full_qual = node.qualifier.upper() if node.qualifier else None

        if full_qual:
            for alias_key, real_table_val in self.current_scopes.items():
                if full_qual == real_table_val and alias_key != real_table_val:
                    raise SemanticError(f"Original table name '{node.qualifier}' cannot be used when alias '{alias_key.lower()}' is defined")
            
            match_scope = full_qual if full_qual in self.current_scopes else full_qual.split('.')[-1]
            if match_scope not in self.current_scopes:
                raise SemanticError(f"Unknown qualifier '{node.qualifier}'")
            
            real_table = self.current_scopes[match_scope]
            if not self.registry.has_column(real_table, node.name):
                raise SemanticError(f"Column '{node.name}' not found in '{real_table.capitalize()}'")
        else:
            matches = []
            for scope_name, real_table in self.current_scopes.items():
                if scope_name == real_table and any(v == real_table and k != real_table for k, v in self.current_scopes.items()):
                    continue
                if self.registry.has_column(real_table, node.name):
                    matches.append(real_table)
            
            if not matches:
                if len(self.current_scopes) == 1:
                    t_name = list(self.current_scopes.values())[0].capitalize()
                    raise SemanticError(f"Column '{node.name}' not found in '{t_name}'")
                raise SemanticError(f"Column '{node.name}' not found in any registered tables")
            
            if len(matches) > 1:
                sorted_m = sorted([m.upper() for m in matches])
                raise SemanticError(f"Column '{node.name}' is ambiguous. Found in: {', '.join(sorted_m)}")

    # --- ZTA 輔助功能 ---

    def _register_scope(self, table_node, alias):
        real_t = table_node.name.upper()
        if not self.registry.has_table(real_t):
            raise SemanticError(f"Table '{table_node.name}' not found")
        self.active_tables.append(real_t)
        self.current_scopes[alias.upper() if alias else real_t] = real_t

    def _expand_global_star(self, stmt):
        expanded = []
        for scope_name, real_table in self.current_scopes.items():
            if scope_name == real_table and any(v == real_table and k != real_table for k, v in self.current_scopes.items()):
                continue
            cols = self.registry.get_columns(real_table)
            expanded.extend([IdentifierNode(name=c, qualifiers=[scope_name]) for c in cols])
        stmt.columns.extend(expanded)

    def _expand_qualified_star(self, stmt, prefix):
        up_prefix = prefix.upper()
        match_scope = up_prefix if up_prefix in self.current_scopes else up_prefix.split('.')[-1]
        if match_scope not in self.current_scopes:
            raise SemanticError(f"Unknown qualifier '{prefix}' in star expansion")
        real_table = self.current_scopes[match_scope]
        cols = self.registry.get_columns(real_table)
        stmt.columns.extend([IdentifierNode(name=c, qualifiers=[prefix]) for c in cols])