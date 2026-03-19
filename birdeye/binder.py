from birdeye.ast import (
    SelectStatement, UpdateStatement, DeleteStatement, InsertStatement,
    SqlBulkCopyStatement, IdentifierNode, BinaryExpressionNode, 
    FunctionCallNode, LiteralNode, OrderByNode, CaseExpressionNode
)

class SemanticError(Exception):
    """語意錯誤：當 SQL 語法正確但邏輯/權限不符元數據時拋出"""
    pass

class Binder:
    """
    語意綁定器：執行標識符解析、星號展開與 ZTA 政策強制執行。
    v1.6.9: 支援 CASE WHEN 遞迴校驗與無表常數查詢 (SELECT 1)。
    """
    def __init__(self, registry):
        self.registry = registry
        self.scopes = [] # Stack: [ {level0}, {level1}, ... ]
        self.nullable_stack = [] 
        self._last_root_nullables = set() # 保存根查詢狀態供測試檢查
        self._aggregate_funcs = {"SUM", "COUNT", "AVG", "MIN", "MAX"}

    @property
    def nullable_scopes(self):
        """向下相容：讓舊有 JOIN 測試能存取最後一層或根層級的空值作用域"""
        if self.nullable_stack:
            return self.nullable_stack[-1]
        return self._last_root_nullables

    def bind(self, stmt):
        """主入口：執行語意檢查並返回綁定後的 AST"""
        self.scopes = []
        self.nullable_stack = []
        self._last_root_nullables = set()

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

    # --- 核心語意遞迴邏輯 ---

    def _bind_select(self, stmt):
        is_root = (len(self.scopes) == 0)
        self.scopes.append({})
        self.nullable_stack.append(set())

        # 💡 修復：僅在有來源表時註冊作用域 (支援 SELECT 1)
        if stmt.table:
            self._register_scope(stmt.table, stmt.table_alias)
        
        # 處理 JOIN 作用域
        for join in stmt.joins:
            current_nullable = self.nullable_stack[-1]
            if join.type == "LEFT":
                current_nullable.add(join.alias.upper() if join.alias else join.table.name.upper())
            elif join.type == "RIGHT":
                current_nullable.update(self.scopes[-1].keys())
            
            self._register_scope(join.table, join.alias)
            if join.on_condition:
                self._visit_expression(join.on_condition)

        # 星號展開
        if stmt.is_select_star:
            self._expand_global_star(stmt)
        for prefix in stmt.star_prefixes:
            self._expand_qualified_star(stmt, prefix)

        # 條件與分組校驗
        if stmt.where_condition:
            if self._has_aggregate(stmt.where_condition):
                raise SemanticError("Aggregate functions are not allowed in WHERE clause")
            self._visit_expression(stmt.where_condition)

        for g_col in stmt.group_by_cols:
            self._visit_expression(g_col)

        # 🛡️ ZTA 聚合完整性檢查 (包含 CASE 內部檢查)
        is_agg_query = len(stmt.group_by_cols) > 0 or any(self._has_aggregate(c) for c in stmt.columns)
        for col_expr in stmt.columns:
            self._visit_expression(col_expr)
            if is_agg_query:
                self._validate_aggregate_integrity(col_expr, stmt.group_by_cols)

        if stmt.having_condition:
            self._visit_expression(stmt.having_condition)

        for term in stmt.order_by_terms:
            self._visit_expression(term.column)

        if is_root:
            self._last_root_nullables = set(self.nullable_stack[-1])

        self.scopes.pop()
        self.nullable_stack.pop()

    def _bind_update(self, stmt):
        self.scopes.append({})
        self._register_scope(stmt.table, stmt.table_alias)
        for clause in stmt.set_clauses:
            self._visit_expression(clause.column)
            self._visit_expression(clause.right) 
        if stmt.where_condition:
            self._visit_expression(stmt.where_condition)
        self.scopes.pop()

    def _bind_delete(self, stmt):
        self.scopes.append({})
        self._register_scope(stmt.table, stmt.table_alias)
        if stmt.where_condition:
            self._visit_expression(stmt.where_condition)
        self.scopes.pop()

    def _bind_insert(self, stmt):
        self.scopes.append({})
        self._register_scope(stmt.table, stmt.table_alias)
        for col in stmt.columns:
            self._resolve_identifier(col)
        for val in stmt.values:
            self._visit_expression(val)
        
        expected = len(stmt.columns) if stmt.columns else self.registry.get_column_count(stmt.table.name)
        if expected != len(stmt.values):
            raise SemanticError(f"Column count mismatch: Expected {expected}, got {len(stmt.values)}")
        self.scopes.pop()

    def _bind_bulk_insert(self, stmt):
        if not self.registry.has_table(stmt.table.name):
            raise SemanticError(f"Table '{stmt.table.name}' not found")

    # --- 標識符解析引擎 (Scope Stack) ---

    def _visit_expression(self, expr):
        if isinstance(expr, IdentifierNode):
            self._resolve_identifier(expr)
        elif isinstance(expr, BinaryExpressionNode):
            if expr.operator == "IN" and isinstance(expr.right, SelectStatement):
                self._visit_expression(expr.right)
                self._visit_expression(expr.left)
            else:
                self._visit_expression(expr.left)
                self._visit_expression(expr.right)
        elif isinstance(expr, FunctionCallNode):
            for arg in expr.args: self._visit_expression(arg)
        elif isinstance(expr, SelectStatement):
            self._bind_select(expr)
        elif isinstance(expr, CaseExpressionNode):
            # 💡 CASE 語句遞迴走訪
            if expr.input_expr: self._visit_expression(expr.input_expr)
            for w, t in expr.branches:
                self._visit_expression(w)
                self._visit_expression(t)
            if expr.else_expr: self._visit_expression(expr.else_expr)
        elif isinstance(expr, list):
            for e in expr: self._visit_expression(e)

    def _resolve_identifier(self, node):
        if node.name == "*": return
        full_qual = node.qualifier.upper() if node.qualifier else None

        for scope in reversed(self.scopes):
            if full_qual:
                # 🛡️ ZTA 政策：別名失效檢查
                for alias_key, real_table_val in scope.items():
                    if full_qual == real_table_val and alias_key != real_table_val:
                        raise SemanticError(f"Original table name '{node.qualifier}' cannot be used when alias '{alias_key.lower()}' is defined")
                
                match_scope = full_qual if full_qual in scope else full_qual.split('.')[-1]
                if match_scope in scope:
                    real_table = scope[match_scope]
                    if self.registry.has_column(real_table, node.name): return
                    raise SemanticError(f"Column '{node.name}' not found in '{real_table.capitalize()}'")
            else:
                matches = []
                for scope_name, real_table in scope.items():
                    if scope_name == real_table and any(v == real_table and k != real_table for k, v in scope.items()):
                        continue
                    if self.registry.has_column(real_table, node.name): matches.append(real_table)
                
                if len(matches) > 1:
                    raise SemanticError(f"Column '{node.name}' is ambiguous. Found in: {', '.join(sorted([m.upper() for m in matches]))}")
                if len(matches) == 1: return

        # 💡 報錯精準化：若當前作用域只有一張表，錯誤訊息應指向該表
        if not full_qual and len(self.scopes) > 0:
            current_scope = self.scopes[-1]
            if len(current_scope) == 1:
                t_name = list(current_scope.values())[0].capitalize()
                raise SemanticError(f"Column '{node.name}' not found in '{t_name}'")

        if full_qual: raise SemanticError(f"Unknown qualifier '{node.qualifier}'")
        raise SemanticError(f"Column '{node.name}' not found in any registered tables")

    # --- 聚合輔助方法 ---

    def _has_aggregate(self, expr):
        if isinstance(expr, FunctionCallNode):
            if expr.name.upper() in self._aggregate_funcs: return True
            return any(self._has_aggregate(arg) for arg in expr.args)
        elif isinstance(expr, BinaryExpressionNode):
            return self._has_aggregate(expr.left) or self._has_aggregate(expr.right)
        elif isinstance(expr, CaseExpressionNode):
            if expr.input_expr and self._has_aggregate(expr.input_expr): return True
            for w, t in expr.branches:
                if self._has_aggregate(w) or self._has_aggregate(t): return True
            return self._has_aggregate(expr.else_expr) if expr.else_expr else False
        return False

    def _validate_aggregate_integrity(self, expr, group_by_cols):
        if self._has_aggregate(expr): return
        
        if isinstance(expr, IdentifierNode):
            if expr.name == "*": return
            found = any(isinstance(g, IdentifierNode) and g.name.upper() == expr.name.upper() and g.qualifier == expr.qualifier for g in group_by_cols)
            if not found: raise SemanticError(f"Column '{expr.name}' must appear in the GROUP BY clause or be used in an aggregate function")
        elif isinstance(expr, BinaryExpressionNode):
            self._validate_aggregate_integrity(expr.left, group_by_cols)
            self._validate_aggregate_integrity(expr.right, group_by_cols)
        elif isinstance(expr, FunctionCallNode):
            for arg in expr.args: self._validate_aggregate_integrity(arg, group_by_cols)
        elif isinstance(expr, CaseExpressionNode):
            if expr.input_expr: self._validate_aggregate_integrity(expr.input_expr, group_by_cols)
            for w, t in expr.branches:
                self._validate_aggregate_integrity(w, group_by_cols)
                self._validate_aggregate_integrity(t, group_by_cols)
            if expr.else_expr: self._validate_aggregate_integrity(expr.else_expr, group_by_cols)

    # --- ZTA 輔助功能 (展開與註冊) ---

    def _register_scope(self, table_node, alias):
        real_t = table_node.name.upper()
        if not self.registry.has_table(real_t):
            raise SemanticError(f"Table '{table_node.name}' not found")
        self.scopes[-1][alias.upper() if alias else real_t] = real_t

    def _expand_global_star(self, stmt):
        current_scope = self.scopes[-1]
        for scope_name, real_table in current_scope.items():
            if scope_name == real_table and any(v == real_table and k != real_table for k, v in current_scope.items()): continue
            cols = self.registry.get_columns(real_table)
            stmt.columns.extend([IdentifierNode(name=c, qualifiers=[scope_name]) for c in cols])

    def _expand_qualified_star(self, stmt, prefix):
        current_scope = self.scopes[-1]
        up_prefix = prefix.upper()
        match_scope = up_prefix if up_prefix in current_scope else up_prefix.split('.')[-1]
        if match_scope not in current_scope: raise SemanticError(f"Unknown qualifier '{prefix}' in star expansion")
        cols = self.registry.get_columns(current_scope[match_scope])
        stmt.columns.extend([IdentifierNode(name=c, qualifiers=[prefix]) for c in cols])