from birdeye.ast import (
    SelectStatement, UpdateStatement, DeleteStatement, InsertStatement,
    SqlBulkCopyStatement, IdentifierNode, BinaryExpressionNode, 
    FunctionCallNode, LiteralNode, OrderByNode # 💡 v1.6.1 新增
)

class SemanticError(Exception):
    """語意錯誤：當 SQL 語法正確但邏輯/權限不符元數據時拋出"""
    pass

class Binder:
    """
    語意綁定器：執行標識符解析、星號展開與 ZTA 政策強制執行。
    v1.6.1: 支援 Issue #30 - 排序欄位的作用域綁定與歧義檢查。
    """
    def __init__(self, registry):
        self.registry = registry
        self.current_scopes = {}    # 作用域名稱 (別名或表名) -> 原始大寫表名
        self.active_tables = []     # 當前查詢涉及的原始表名清單
        self.nullable_scopes = set() # 標記為 Nullable 的作用域 (用於 Join)

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
        # 1. 註冊主表
        self._register_scope(stmt.table, stmt.table_alias)

        # 2. 註冊 JOIN 表 (依序註冊以支援前向引用)
        for join in stmt.joins:
            if join.type == "LEFT":
                self.nullable_scopes.add(join.alias.upper() if join.alias else join.table.name.upper())
            elif join.type == "RIGHT":
                self.nullable_scopes.update(self.current_scopes.keys())

            self._register_scope(join.table, join.alias)
            if join.on_condition:
                self._visit_expression(join.on_condition)

        # 3. 處理星號展開
        if stmt.is_select_star:
            self._expand_global_star(stmt)
        for prefix in stmt.star_prefixes:
            self._expand_qualified_star(stmt, prefix)

        # 4. 綁定投影欄位與 WHERE
        for col in stmt.columns:
            self._visit_expression(col)
        if stmt.where_condition:
            self._visit_expression(stmt.where_condition)

        # 💡 Issue #30: 綁定 ORDER BY 欄位
        # 排序欄位必須在已註冊的作用域內，且遵循相同的 ZTA 歧義與別名政策
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
        
        # 🛡️ ZTA 數量校驗
        expected = len(stmt.columns) if stmt.columns else self.registry.get_column_count(stmt.table.name)
        actual = len(stmt.values)
        if expected != actual:
            raise SemanticError(f"Column count mismatch: Expected {expected}, got {actual}")

    def _bind_bulk_insert(self, stmt):
        if not self.registry.has_table(stmt.table.name):
            raise SemanticError(f"Table '{stmt.table.name}' not found")

    # --- 表達式走訪 ---

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

    # --- 標識符解析引擎 (ZTA 核心政策) ---

    def _resolve_identifier(self, node):
        if node.name == "*": return

        full_qual = node.qualifier.upper() if node.qualifier else None

        if full_qual:
            # 🛡️ ZTA 政策：一旦定義別名，禁止再使用原始表名
            for alias_key, real_table_val in self.current_scopes.items():
                if full_qual == real_table_val and alias_key != real_table_val:
                    raise SemanticError(f"Original table name '{node.qualifier}' cannot be used when alias '{alias_key.lower()}' is defined")
            
            match_scope = None
            if full_qual in self.current_scopes:
                match_scope = full_qual
            else:
                parts = full_qual.split('.')
                if parts[-1] in self.current_scopes:
                    match_scope = parts[-1]
            
            if not match_scope:
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
        if alias:
            self.current_scopes[alias.upper()] = real_t
        else:
            self.current_scopes[real_t] = real_t

    def _expand_global_star(self, stmt):
        expanded = []
        for scope_name, real_table in self.current_scopes.items():
            if scope_name == real_table and any(v == real_table and k != real_table for k, v in self.current_scopes.items()):
                continue
            cols = self.registry.get_columns(real_table)
            for c in cols:
                expanded.append(IdentifierNode(name=c, qualifiers=[scope_name]))
        stmt.columns.extend(expanded)

    def _expand_qualified_star(self, stmt, prefix):
        up_prefix = prefix.upper()
        match_scope = up_prefix if up_prefix in self.current_scopes else up_prefix.split('.')[-1]
        
        if match_scope not in self.current_scopes:
            raise SemanticError(f"Unknown qualifier '{prefix}' in star expansion")
            
        real_table = self.current_scopes[match_scope]
        cols = self.registry.get_columns(real_table)
        stmt.columns.extend([IdentifierNode(name=c, qualifiers=[prefix]) for c in cols])