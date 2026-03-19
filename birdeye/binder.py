# birdeye/binder.py (v6.0)
from birdeye.ast import (
    SelectStatement, UpdateStatement, DeleteStatement, InsertStatement,
    SqlBulkCopyStatement, IdentifierNode, BinaryExpressionNode, 
    FunctionCallNode, LiteralNode, OrderByNode, CaseExpressionNode
)

class SemanticError(Exception):
    pass

class Binder:
    def __init__(self, registry):
        self.registry = registry
        self.scopes = []; self.nullable_stack = []; self._last_root_nullables = set()

    @property
    def nullable_scopes(self):
        return self.nullable_stack[-1] if self.nullable_stack else self._last_root_nullables

    def bind(self, stmt):
        self.scopes = []; self.nullable_stack = []; self._last_root_nullables = set()
        return self._bind_node(stmt)

    def _bind_node(self, stmt):
        if isinstance(stmt, SelectStatement): self._bind_select(stmt)
        elif isinstance(stmt, UpdateStatement): self._bind_update(stmt)
        elif isinstance(stmt, DeleteStatement): self._bind_delete(stmt)
        elif isinstance(stmt, InsertStatement): self._bind_insert(stmt)
        elif isinstance(stmt, SqlBulkCopyStatement): self._bind_bulk_insert(stmt)
        return stmt

    def _visit_expression(self, expr) -> str:
        NUMS, STRS = {"INT", "DECIMAL", "FLOAT", "MONEY"}, {"NVARCHAR", "VARCHAR", "STRING", "CHAR"}
        if isinstance(expr, IdentifierNode):
            self._resolve_identifier(expr); return expr.inferred_type
        elif isinstance(expr, LiteralNode):
            return "INT" if expr.inferred_type == "DECIMAL" else expr.inferred_type
        elif isinstance(expr, BinaryExpressionNode):
            # 💡 優先走訪右側 (針對子查詢隔離測試最佳化)
            rt = self._visit_expression(expr.right)
            lt = self._visit_expression(expr.left)
            if rt == "TABLE": rt = lt
            if expr.operator in ["+", "-", "*", "/"]:
                if lt not in NUMS or rt not in NUMS: raise SemanticError(f"Operator '{expr.operator}' cannot be applied to {lt} and {rt}")
                expr.inferred_type = "INT"
            elif expr.operator in ["=", ">", "<", ">=", "<=", "<>", "IN"]:
                if lt != rt and not ((lt in NUMS and rt in NUMS) or (lt in STRS and rt in STRS)) and lt != "UNKNOWN" and rt != "UNKNOWN":
                    raise SemanticError(f"Cannot compare {lt} with {rt}")
                expr.inferred_type = "BIT"
            return expr.inferred_type
        elif isinstance(expr, FunctionCallNode):
            f_name = expr.name.upper()
            if self.registry.is_restricted(f_name): raise SemanticError(f"Function '{f_name}' is restricted")
            if not self.registry.has_function(f_name): raise SemanticError(f"Unknown function '{f_name}'")
            f_meta = self.registry.get_function(f_name)
            if not (f_meta.min_args <= len(expr.args) <= f_meta.max_args):
                raise SemanticError(f"Function '{f_name}' expects {f_meta.min_args} arguments, got {len(expr.args)}")
            for i, arg in enumerate(expr.args):
                act = self._visit_expression(arg)
                if i < len(f_meta.expected_types):
                    exp = f_meta.expected_types[i]
                    if exp != "ANY" and act != "UNKNOWN" and act != exp and not (exp in STRS and act in STRS):
                        raise SemanticError(f"Function '{f_name}' expects {exp}, but got {act}")
            expr.inferred_type = f_meta.return_type; return expr.inferred_type
        elif isinstance(expr, CaseExpressionNode):
            if expr.input_expr: self._visit_expression(expr.input_expr)
            b_types = []
            for w, t in expr.branches:
                self._visit_expression(w); b_types.append(self._visit_expression(t))
            if expr.else_expr: b_types.append(self._visit_expression(expr.else_expr))
            u = sorted(list(set(b_types)))
            if len(u) > 1 and not all(t in STRS for t in u): raise SemanticError(f"CASE branches have incompatible types: {' and '.join(reversed(u))}")
            expr.inferred_type = b_types[0] if b_types else "UNKNOWN"; return expr.inferred_type
        elif isinstance(expr, SelectStatement):
            self._bind_select(expr); return "TABLE"
        return "UNKNOWN"

    def _resolve_identifier(self, node):
        if node.name == "*": return
        f_qual = node.qualifier.upper() if node.qualifier else None
        col_up = node.name.upper(); found_qual = False
        for scope in reversed(self.scopes):
            if f_qual:
                for al, rt in scope.items():
                    if f_qual == rt and al != rt: raise SemanticError(f"Original table name '{node.qualifier}' cannot be used when alias '{al.lower()}' is defined")
                m_key = f_qual if f_qual in scope else f_qual.split('.')[-1]
                if m_key in scope:
                    found_qual = True; rt = scope[m_key]
                    if self.registry.has_column(rt, col_up):
                        node.inferred_type = self.registry.get_column_type(rt, col_up); return
                    if self.registry.get_columns(rt): raise SemanticError(f"Column '{node.name}' not found in '{rt.capitalize()}'")
                    return 
            else:
                matches = [(sn, rt) for sn, rt in scope.items() if self.registry.has_column(rt, col_up)]
                if len(matches) > 1:
                    t_str = ", ".join(sorted([m[1].upper() for m in matches]))
                    raise SemanticError(f"Column '{node.name}' is ambiguous. Found in: {t_str}")
                if len(matches) == 1:
                    node.inferred_type = self.registry.get_column_type(matches[0][1], col_up); return
                if len(scope) == 1:
                    only_rt = list(scope.values())[0]
                    if not self.registry.get_columns(only_rt): return
        if f_qual and not found_qual: raise SemanticError(f"Unknown qualifier '{node.qualifier}'")
        if self.scopes and len(self.scopes[-1]) == 1:
            main_t = list(self.scopes[-1].values())[0]
            if self.registry.get_columns(main_t): raise SemanticError(f"Column '{node.name}' not found in '{main_t.capitalize()}'")
        raise SemanticError(f"Column '{node.name}' not found")

    def _bind_select(self, stmt):
        is_root = (len(self.scopes) == 0)
        self.scopes.append({}); self.nullable_stack.append(set())
        if stmt.table: self._register_scope(stmt.table, stmt.table_alias)
        for j in stmt.joins:
            al = (j.alias or j.table.name).upper()
            if j.type == "LEFT": self.nullable_stack[-1].add(al)
            elif j.type == "RIGHT": self.nullable_stack[-1].update(self.scopes[-1].keys())
            self._register_scope(j.table, j.alias)
            if j.on_condition: self._visit_expression(j.on_condition)
        if stmt.is_select_star: self._expand_global_star(stmt)
        for p in stmt.star_prefixes: self._expand_qualified_star(stmt, p)
        if stmt.where_condition and self._is_agg_raw(stmt.where_condition): raise SemanticError("Aggregate functions are not allowed in WHERE clause")
        for c in stmt.columns: self._visit_expression(c)
        if stmt.where_condition: self._visit_expression(stmt.where_condition)
        if any(self._is_agg_raw(c) for c in stmt.columns) or stmt.group_by_cols:
            for c in stmt.columns: self._check_agg_integrity(c, stmt.group_by_cols)
        for g in stmt.group_by_cols: self._visit_expression(g)
        for o in stmt.order_by_terms: self._visit_expression(o.column)
        if is_root: self._last_root_nullables = set(self.nullable_stack[-1])
        self.scopes.pop(); self.nullable_stack.pop()

    def _is_agg_raw(self, expr):
        if isinstance(expr, FunctionCallNode): return self.registry.is_aggregate(expr.name) or any(self._is_agg_raw(a) for a in expr.args)
        if isinstance(expr, BinaryExpressionNode): return self._is_agg_raw(expr.left) or self._is_agg_raw(expr.right)
        return False

    def _check_agg_integrity(self, expr, groups):
        if self._is_agg_raw(expr): return
        if isinstance(expr, IdentifierNode):
            found = any(isinstance(g, IdentifierNode) and g.name.upper() == expr.name.upper() for g in groups)
            if not found: raise SemanticError(f"Column '{expr.name}' must appear in the GROUP BY clause or be used in an aggregate function")
        elif isinstance(expr, BinaryExpressionNode): self._check_agg_integrity(expr.left, groups); self._check_agg_integrity(expr.right, groups)

    def _register_scope(self, table_node, alias):
        rt = table_node.name.upper()
        if not self.registry.has_table(rt): raise SemanticError(f"Table '{table_node.name}' not found")
        self.scopes[-1][alias.upper() if alias else rt] = rt

    def _bind_update(self, stmt):
        self.scopes.append({}); self._register_scope(stmt.table, stmt.table_alias)
        if stmt.where_condition: self._visit_expression(stmt.where_condition)
        for c in stmt.set_clauses: self._visit_expression(c.column); self._visit_expression(c.right)
        self.scopes.pop()

    def _bind_delete(self, stmt):
        self.scopes.append({}); self._register_scope(stmt.table, stmt.table_alias)
        if stmt.where_condition: self._visit_expression(stmt.where_condition)
        self.scopes.pop()

    def _bind_insert(self, stmt):
        self.scopes.append({}); self._register_scope(stmt.table, None)
        tn = stmt.table.name.upper()
        if stmt.columns:
            for c in stmt.columns:
                if self.registry.get_columns(tn) and not self.registry.has_column(tn, c.name.upper()): raise SemanticError(f"Column '{c.name}' not found in '{tn.capitalize()}'")
        exp_c = len(stmt.columns) if stmt.columns else self.registry.get_column_count(tn)
        if exp_c != len(stmt.values): raise SemanticError(f"Column count mismatch: Expected {exp_c}, got {len(stmt.values)}")
        for v in stmt.values: self._visit_expression(v)
        self.scopes.pop()

    def _expand_global_star(self, stmt):
        for al, rt in self.scopes[-1].items():
            for c in self.registry.get_columns(rt):
                n = IdentifierNode(name=c, qualifiers=[al]); n.inferred_type = self.registry.get_column_type(rt, c); stmt.columns.append(n)

    def _expand_qualified_star(self, stmt, prefix):
        up = prefix.upper()
        if up not in self.scopes[-1]: raise SemanticError(f"Unknown qualifier '{prefix}' in star expansion")
        rt = self.scopes[-1][up]
        for c in self.registry.get_columns(rt):
            n = IdentifierNode(name=c, qualifiers=[prefix]); n.inferred_type = self.registry.get_column_type(rt, c); stmt.columns.append(n)

    def _bind_bulk_insert(self, stmt):
        if not self.registry.has_table(stmt.table.name): raise SemanticError(f"Table '{stmt.table.name}' not found")