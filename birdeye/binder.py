# birdeye/binder.py (v6.0)
from birdeye.ast import (
    SelectStatement, UpdateStatement, DeleteStatement, InsertStatement,
    SqlBulkCopyStatement, IdentifierNode, BinaryExpressionNode, 
    FunctionCallNode, LiteralNode, OrderByNode, CaseExpressionNode, 
    BetweenExpressionNode, CastExpressionNode, UnionStatement
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
        elif isinstance(stmt, UnionStatement): self._bind_union(stmt)
        elif isinstance(stmt, UpdateStatement): self._bind_update(stmt)
        elif isinstance(stmt, DeleteStatement): self._bind_delete(stmt)
        elif isinstance(stmt, InsertStatement): self._bind_insert(stmt)
        elif isinstance(stmt, SqlBulkCopyStatement): self._bind_bulk_insert(stmt)
        return stmt

    def _bind_union(self, stmt):
        """🛡️ ZTA 政策：驗證 UNION 集合運算的結構完整性"""
        # 1. 分別走訪左側與右側
        self._bind_node(stmt.left)
        self._bind_node(stmt.right)
        
        # 2. 取得兩側的投影欄位清單 (處理嵌套的 UNION)
        def get_cols(node):
            if isinstance(node, SelectStatement): return node.columns
            if isinstance(node, UnionStatement): return node.columns
            return []

        left_cols = get_cols(stmt.left)
        right_cols = get_cols(stmt.right)
        
        # 3. 資安校驗：欄位數量必須完全一致
        if len(left_cols) != len(right_cols):
            raise SemanticError(f"All queries combined using a {stmt.operator} operator must have an equal number of expressions in their target lists. Got {len(left_cols)} vs {len(right_cols)}")
            
        # 4. 資安校驗：對應位置的型別家族必須相容
        stmt.columns = []
        for i in range(len(left_cols)):
            lt = left_cols[i].inferred_type
            rt = right_cols[i].inferred_type
            
            if not self._is_type_compatible(lt, rt):
                raise SemanticError(f"Incompatible types in {stmt.operator}: Column {i+1} has types {lt} and {rt}")
            
            # 建立一個虛擬的結果欄位 (用於嵌套 UNION 的後續推導)
            new_col = IdentifierNode(name=left_cols[i].alias or f"col_{i+1}")
            new_col.inferred_type = lt if lt != "UNKNOWN" else rt
            stmt.columns.append(new_col)

    def _visit_between(self, node):
        """🛡️ ZTA 政策：驗證 BETWEEN 三元運算子的型別相容性"""
        target_type = self._visit_expression(node.expr)
        low_type = self._visit_expression(node.low)
        high_type = self._visit_expression(node.high)
        if not self._is_type_compatible(target_type, low_type) or not self._is_type_compatible(target_type, high_type):
            raise SemanticError(f"Incompatible types in BETWEEN: Cannot compare {target_type} with {low_type} and {high_type}")
        node.inferred_type = "BIT"
        return "BIT"

    def _visit_cast(self, node):
        """💡 TDD New: 支援顯式轉型 (Issue #46)"""
        self._visit_expression(node.expr)
        node.inferred_type = node.target_type
        return node.target_type

    def _is_type_compatible(self, type1, type2):
        if type1 == type2 or type1 == "UNKNOWN" or type2 == "UNKNOWN" or type1 == "TABLE" or type2 == "TABLE":
            return True
        NUMS = {"INT", "DECIMAL", "FLOAT", "MONEY", "SMALLINT", "TINYINT", "BIGINT", "NUMERIC", "REAL", "SMALLMONEY", "BIT", "FLAG", "NAMESTYLE"}
        STRS = {"NVARCHAR", "VARCHAR", "STRING", "CHAR", "NCHAR", "SYSNAME", "UNIQUEIDENTIFIER", "HIERARCHYID", "NAME", "ORDERNUMBER", "ACCOUNTNUMBER", "PHONE", "GEOGRAPHY"}
        DATES = {"DATETIME", "DATE", "TIME", "DATETIME2", "SMALLDATETIME", "DATETIMEOFFSET"}
        if type1 in NUMS and type2 in NUMS: return True
        if type1 in STRS and type2 in STRS: return True
        if type1 in DATES and type2 in DATES: return True
        if (type1 in DATES and type2 in STRS) or (type1 in STRS and type2 in DATES): return True
        return False

    def _visit_expression(self, expr) -> str:
        if isinstance(expr, IdentifierNode):
            self._resolve_identifier(expr); return expr.inferred_type
        elif isinstance(expr, LiteralNode):
            return "INT" if expr.inferred_type == "DECIMAL" else expr.inferred_type
        elif isinstance(expr, BinaryExpressionNode):
            rt = self._visit_expression(expr.right)
            lt = self._visit_expression(expr.left)
            if rt == "TABLE": rt = lt
            if expr.operator in ["+", "-", "*", "/"]:
                if expr.operator == "+":
                    is_num = self._is_type_compatible(lt, "INT") and self._is_type_compatible(rt, "INT")
                    is_str = self._is_type_compatible(lt, "NVARCHAR") and self._is_type_compatible(rt, "NVARCHAR")
                    if not (is_num or is_str): raise SemanticError(f"Operator '+' cannot be applied to {lt} and {rt}")
                    expr.inferred_type = "INT" if is_num else "NVARCHAR"
                else:
                    if not self._is_type_compatible(lt, "INT") or not self._is_type_compatible(rt, "INT"): raise SemanticError(f"Operator '{expr.operator}' cannot be applied to {lt} and {rt}")
                    expr.inferred_type = "INT"
            elif expr.operator in ["=", ">", "<", ">=", "<=", "<>", "IN", "LIKE", "NOT LIKE"]:
                if not self._is_type_compatible(lt, rt): raise SemanticError(f"Cannot compare {lt} with {rt}")
                expr.inferred_type = "BIT"
            elif expr.operator in ["IS NULL", "IS NOT NULL"]: expr.inferred_type = "BIT"
            return expr.inferred_type
        elif isinstance(expr, FunctionCallNode):
            f_name = expr.name.upper()
            if self.registry.is_restricted(f_name): raise SemanticError(f"Function '{f_name}' is restricted")
            if not self.registry.has_function(f_name): raise SemanticError(f"Unknown function '{f_name}'")
            f_meta = self.registry.get_function(f_name)
            if not (f_meta.min_args <= len(expr.args) <= f_meta.max_args): raise SemanticError(f"Function '{f_name}' expects {f_meta.min_args} arguments, got {len(expr.args)}")
            for i, arg in enumerate(expr.args):
                act = self._visit_expression(arg)
                if i < len(f_meta.expected_types):
                    exp = f_meta.expected_types[i]
                    if exp != "ANY" and act != "UNKNOWN" and act != exp and not self._is_type_compatible(exp, act): raise SemanticError(f"Function '{f_name}' expects {exp}, but got {act}")
            expr.inferred_type = f_meta.return_type; return expr.inferred_type
        elif isinstance(expr, CaseExpressionNode):
            if expr.input_expr: self._visit_expression(expr.input_expr)
            b_types = []
            for w, t in expr.branches: self._visit_expression(w); b_types.append(self._visit_expression(t))
            if expr.else_expr: b_types.append(self._visit_expression(expr.else_expr))
            u = sorted(list(set(b_types)))
            if len(u) > 1:
                base_type = u[0]
                if not all(self._is_type_compatible(base_type, t) for t in u):
                    raise SemanticError(f"CASE branches have incompatible types: {' and '.join(reversed(u))}")
            expr.inferred_type = b_types[0] if b_types else "UNKNOWN"; return expr.inferred_type
        elif isinstance(expr, BetweenExpressionNode): return self._visit_between(expr)
        elif isinstance(expr, CastExpressionNode): return self._visit_cast(expr)
        elif isinstance(expr, SelectStatement): self._bind_select(expr); return "TABLE"
        elif isinstance(expr, UnionStatement): self._bind_union(expr); return "TABLE"
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
                    if self.registry.has_column(rt, col_up): node.inferred_type = self.registry.get_column_type(rt, col_up); return
                    if self.registry.get_columns(rt): raise SemanticError(f"Column '{node.name}' not found in '{rt.capitalize()}'")
                    return 
            else:
                matches = [(sn, rt) for sn, rt in scope.items() if self.registry.has_column(rt, col_up)]
                if len(matches) > 1:
                    t_str = ", ".join(sorted([m[1].upper() for m in matches]))
                    raise SemanticError(f"Column '{node.name}' is ambiguous. Found in: {t_str}")
                if len(matches) == 1: node.inferred_type = self.registry.get_column_type(matches[0][1], col_up); return
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
        projected_aliases = {c.alias.upper(): c.inferred_type for c in stmt.columns if hasattr(c, 'alias') and c.alias}
        for o in stmt.order_by_terms:
            if isinstance(o.column, IdentifierNode) and o.column.name.upper() in projected_aliases: o.column.inferred_type = projected_aliases[o.column.name.upper()]
            else: self._visit_expression(o.column)
        if is_root: self._last_root_nullables = set(self.nullable_stack[-1])
        self.scopes.pop(); self.nullable_stack.pop()

    def _is_agg_raw(self, expr):
        if isinstance(expr, FunctionCallNode): return self.registry.is_aggregate(expr.name) or any(self._is_agg_raw(a) for a in expr.args)
        if isinstance(expr, BinaryExpressionNode): return self._is_agg_raw(expr.left) or self._is_agg_raw(expr.right)
        return False

    def _check_agg_integrity(self, expr, groups):
        if self._is_agg_raw(expr): return
        from birdeye.serializer import ASTSerializer
        def _get_clean_json(node):
            serializer = ASTSerializer(); data = serializer._serialize(node)
            if isinstance(data, dict) and "alias" in data: del data["alias"]
            return data
        expr_json = _get_clean_json(expr)
        for g in groups:
            if _get_clean_json(g) == expr_json: return
        if isinstance(expr, IdentifierNode):
            found = any(isinstance(g, IdentifierNode) and g.name.upper() == expr.name.upper() for g in groups)
            if not found: raise SemanticError(f"Column '{expr.name}' must appear in the GROUP BY clause or be used in an aggregate function")
        elif isinstance(expr, BinaryExpressionNode): self._check_agg_integrity(expr.left, groups); self._check_agg_integrity(expr.right, groups)
        elif isinstance(expr, FunctionCallNode):
            for arg in expr.args: self._check_agg_integrity(arg, groups)
        elif isinstance(expr, CaseExpressionNode):
            if expr.input_expr: self._check_agg_integrity(expr.input_expr, groups)
            for w, t in expr.branches: self._check_agg_integrity(w, groups); self._check_agg_integrity(t, groups)
            if expr.else_expr: self._check_agg_integrity(expr.else_expr, groups)

    def _register_scope(self, table_node, alias):
        rt = table_node.name.upper()
        if not self.registry.has_table(rt): raise SemanticError(f"Table '{table_node.name}' not found")
        self.scopes[-1][alias.upper() if alias else rt] = rt

    def _bind_update(self, stmt):
        self.scopes.append({}); self._register_scope(stmt.table, stmt.table_alias)
        if stmt.where_condition: self._visit_expression(stmt.where_condition)
        for c in stmt.set_clauses:
            lt = self._visit_expression(c.column); rt = self._visit_expression(c.right)
            self._check_type_compatibility(lt, rt, "SET assignment")
        self.scopes.pop()

    def _bind_delete(self, stmt):
        self.scopes.append({}); self._register_scope(stmt.table, stmt.table_alias)
        if stmt.where_condition: self._visit_expression(stmt.where_condition)
        self.scopes.pop()

    def _bind_insert(self, stmt):
        self.scopes.append({}); self._register_scope(stmt.table, None); tn = stmt.table.name.upper()
        if stmt.columns:
            for c in stmt.columns:
                if self.registry.get_columns(tn) and not self.registry.has_column(tn, c.name.upper()): raise SemanticError(f"Column '{c.name}' not found in '{tn.capitalize()}'")
        col_names = [c.name.upper() for c in stmt.columns] if stmt.columns else self.registry.get_columns(tn)
        if len(col_names) != len(stmt.values): raise SemanticError(f"Column count mismatch: Expected {len(col_names)}, got {len(stmt.values)}")
        for i, v in enumerate(stmt.values):
            rt = self._visit_expression(v)
            if col_names: lt = self.registry.get_column_type(tn, col_names[i]); self._check_type_compatibility(lt, rt, f"INSERT into '{col_names[i]}'")
        self.scopes.pop()

    def _check_type_compatibility(self, lt, rt, context):
        if not self._is_type_compatible(lt, rt): raise SemanticError(f"Incompatible types for {context}: Cannot compare {lt} with {rt}")

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
