# birdeye/binder.py (v6.7)
from birdeye.ast import (
    SelectStatement, UpdateStatement, DeleteStatement, InsertStatement,
    SqlBulkCopyStatement, IdentifierNode, BinaryExpressionNode, 
    FunctionCallNode, LiteralNode, OrderByNode, CaseExpressionNode, 
    BetweenExpressionNode, CastExpressionNode, UnionStatement, CTENode, TruncateStatement
)

class SemanticError(Exception):
    pass

class Binder:
    def __init__(self, registry):
        self.registry = registry
        self.scopes = []; self.nullable_stack = []; self._last_root_nullables = set()
        self.cte_schemas = {} 

    @property
    def nullable_scopes(self):
        return self.nullable_stack[-1] if self.nullable_stack else self._last_root_nullables

    def bind(self, stmt):
        self.scopes = []; self.nullable_stack = []; self._last_root_nullables = set()
        self.cte_schemas = {}
        return self._bind_node(stmt)

    def _bind_node(self, stmt):
        if isinstance(stmt, SelectStatement): self._bind_select(stmt)
        elif isinstance(stmt, UnionStatement): self._bind_union(stmt)
        elif isinstance(stmt, UpdateStatement): self._bind_update(stmt)
        elif isinstance(stmt, DeleteStatement): self._bind_delete(stmt)
        elif isinstance(stmt, InsertStatement): self._bind_insert(stmt)
        elif isinstance(stmt, TruncateStatement): self._bind_truncate(stmt)
        elif isinstance(stmt, SqlBulkCopyStatement): self._bind_bulk_insert(stmt)
        return stmt

    def _bind_select(self, stmt):
        is_root = (len(self.scopes) == 0)
        if hasattr(stmt, 'ctes') and stmt.ctes:
            for cte in stmt.ctes:
                self._bind_node(cte.query)
                cols = {}
                source_cols = cte.query.columns
                for c in source_cols:
                    name = c.alias.upper() if hasattr(c, 'alias') and c.alias else c.name.upper()
                    cols[name] = c.inferred_type
                self.cte_schemas[cte.name.upper()] = cols

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
            if isinstance(o.column, IdentifierNode) and o.column.name.upper() in projected_aliases:
                o.column.inferred_type = projected_aliases[o.column.name.upper()]
            else: self._visit_expression(o.column)
        if is_root: self._last_root_nullables = set(self.nullable_stack[-1])
        self.scopes.pop(); self.nullable_stack.pop()

    def _bind_union(self, stmt):
        self._bind_node(stmt.left); self._bind_node(stmt.right)
        def get_cols(node):
            if isinstance(node, SelectStatement): return node.columns
            if isinstance(node, UnionStatement): return node.columns
            return []
        left_cols = get_cols(stmt.left); right_cols = get_cols(stmt.right)
        if len(left_cols) != len(right_cols):
            raise SemanticError(f"All queries combined using a {stmt.operator} operator must have an equal number of expressions in their target lists. Got {len(left_cols)} vs {len(right_cols)}")
        stmt.columns = []
        for i in range(len(left_cols)):
            lt, rt = left_cols[i].inferred_type, right_cols[i].inferred_type
            if not self._is_type_compatible(lt, rt):
                raise SemanticError(f"Incompatible types in {stmt.operator}: Column {i+1} has types {lt} and {rt}")
            new_col = IdentifierNode(name=left_cols[i].alias or f"col_{i+1}")
            new_col.inferred_type = lt if lt != "UNKNOWN" else rt
            stmt.columns.append(new_col)

    def _register_scope(self, table_node, alias):
        rt = table_node.name.upper()
        if rt not in self.cte_schemas and not self.registry.has_table(rt):
            raise SemanticError(f"Table '{table_node.name}' not found")
        self.scopes[-1][alias.upper() if alias else rt] = rt

    def _resolve_identifier(self, node):
        if node.name == "*": return
        f_qual = node.qualifier.upper() if node.qualifier else None
        col_up = node.name.upper(); found_qual = False
        for scope in reversed(self.scopes):
            if f_qual:
                for al, rt in scope.items():
                    if f_qual == rt and al != rt:
                        raise SemanticError(f"Original table name '{node.qualifier}' cannot be used when alias '{al.lower()}' is defined")
                m_key = f_qual if f_qual in scope else f_qual.split('.')[-1]
                if m_key in scope:
                    found_qual = True; rt = scope[m_key]
                    if rt in self.cte_schemas:
                        if col_up in self.cte_schemas[rt]: node.inferred_type = self.cte_schemas[rt][col_up]; return
                        raise SemanticError(f"Column '{node.name}' not found in CTE '{rt.capitalize()}'")
                    if self.registry.has_column(rt, col_up):
                        node.inferred_type = self.registry.get_column_type(rt, col_up); return
                    if self.registry.get_columns(rt):
                        raise SemanticError(f"Column '{node.name}' not found in '{rt.capitalize()}'")
                    return 
            else:
                matches = []
                for sn, rt in scope.items():
                    if rt in self.cte_schemas:
                        if col_up in self.cte_schemas[rt]: matches.append((sn, rt))
                    elif self.registry.has_column(rt, col_up):
                        matches.append((sn, rt))
                if len(matches) > 1:
                    t_str = ", ".join(sorted([m[1].upper() for m in matches]))
                    raise SemanticError(f"Column '{node.name}' is ambiguous. Found in: {t_str}")
                if len(matches) == 1:
                    rt = matches[0][1]
                    node.inferred_type = self.cte_schemas[rt][col_up] if rt in self.cte_schemas else self.registry.get_column_type(rt, col_up)
                    return
                if len(scope) == 1:
                    sn, rt = list(scope.items())[0]
                    if rt in self.cte_schemas:
                        if col_up in self.cte_schemas[rt]:
                            node.inferred_type = self.cte_schemas[rt][col_up]
                            return
                        raise SemanticError(f"Column '{node.name}' not found in CTE '{rt.capitalize()}'")
                    elif self.registry.has_column(rt, col_up):
                        node.inferred_type = self.registry.get_column_type(rt, col_up)
                        return
                    elif self.registry.get_columns(rt):
                        raise SemanticError(f"Column '{node.name}' not found in '{rt.capitalize()}'")
        if f_qual and not found_qual: raise SemanticError(f"Unknown qualifier '{node.qualifier}'")
        raise SemanticError(f"Column '{node.name}' not found")

    def _is_type_compatible(self, type1, type2):
        if type1 == type2 or type1 == "UNKNOWN" or type2 == "UNKNOWN" or type1 == "TABLE" or type2 == "TABLE": return True
        NUMS = {"INT", "DECIMAL", "FLOAT", "MONEY", "SMALLINT", "TINYINT", "BIGINT", "NUMERIC", "REAL", "SMALLMONEY", "BIT", "FLAG", "NAMESTYLE"}
        STRS = {"NVARCHAR", "VARCHAR", "STRING", "CHAR", "NCHAR", "SYSNAME", "UNIQUEIDENTIFIER", "HIERARCHYID", "NAME", "ORDERNUMBER", "ACCOUNTNUMBER", "PHONE", "GEOGRAPHY", "TEXT", "NTEXT"}
        DATES = {"DATETIME", "DATE", "TIME", "DATETIME2", "SMALLDATETIME", "DATETIMEOFFSET"}
        if type1 in NUMS and type2 in NUMS: return True
        if type1 in STRS and type2 in STRS: return True
        if type1 in DATES and type2 in DATES: return True
        if (type1 in DATES and type2 in STRS) or (type1 in STRS and type2 in DATES): return True
        return False

    def _visit_expression(self, expr) -> str:
        if isinstance(expr, IdentifierNode): self._resolve_identifier(expr); return expr.inferred_type
        elif isinstance(expr, LiteralNode): return "INT" if expr.inferred_type == "DECIMAL" else expr.inferred_type
        elif isinstance(expr, BinaryExpressionNode):
            rt_raw = self._visit_expression(expr.right)
            lt = self._visit_expression(expr.left)
            rt = lt if rt_raw == "TABLE" else rt_raw
            
            if expr.operator in ["+", "-", "*", "/"]:
                if expr.operator == "+":
                    is_num = self._is_type_compatible(lt, "INT") and self._is_type_compatible(rt, "INT")
                    is_str = self._is_type_compatible(lt, "NVARCHAR") and self._is_type_compatible(rt, "NVARCHAR")
                    if not (is_num or is_str): raise SemanticError(f"Operator '+' cannot be applied to {lt} and {rt}")
                    expr.inferred_type = "INT" if is_num else "NVARCHAR"
                else:
                    if not self._is_type_compatible(lt, "INT") or not self._is_type_compatible(rt, "INT"): raise SemanticError(f"Operator '{expr.operator}' cannot be applied")
                    expr.inferred_type = "INT"
            elif expr.operator in ["=", ">", "<", ">=", "<=", "<>", "IN", "LIKE", "NOT LIKE", "IS NULL", "IS NOT NULL"] or " ANY" in expr.operator or " ALL" in expr.operator:
                # 💡 TDD Fix: 針對 ANY / ALL 進行深度型別解析
                if " ANY" in expr.operator or " ALL" in expr.operator:
                    if isinstance(expr.right, list):
                        for item in expr.right:
                            it = self._visit_expression(item)
                            if not self._is_type_compatible(lt, it):
                                raise SemanticError(f"Incompatible types in {expr.operator}: {lt} vs {it}")
                    elif isinstance(expr.right, (SelectStatement, UnionStatement)):
                        self._bind_node(expr.right)
                        if hasattr(expr.right, 'columns') and expr.right.columns:
                            # 💡 關鍵：確保子查詢內部已完整推導
                            sub_rt = expr.right.columns[0].inferred_type
                            if not self._is_type_compatible(lt, sub_rt):
                                raise SemanticError(f"Incompatible types in {expr.operator}: {lt} vs {sub_rt}")
                    expr.inferred_type = "BIT"
                elif expr.operator not in ["IS NULL", "IS NOT NULL"]:
                    if not self._is_type_compatible(lt, rt):
                        raise SemanticError(f"Cannot compare {lt} with {rt}")
                    expr.inferred_type = "BIT"
                else:
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
                    if exp != "ANY" and act != "UNKNOWN" and not self._is_type_compatible(exp, act):
                        raise SemanticError(f"Function '{f_name}' expects {exp}, but got {act}")
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

    def _visit_between(self, node):
        t, l, h = self._visit_expression(node.expr), self._visit_expression(node.low), self._visit_expression(node.high)
        if not self._is_type_compatible(t, l) or not self._is_type_compatible(t, h):
            raise SemanticError(f"Incompatible types in BETWEEN: Cannot compare {t} with {l} and {h}")
        node.inferred_type = "BIT"; return "BIT"

    def _visit_cast(self, node):
        self._visit_expression(node.expr); node.inferred_type = node.target_type; return node.target_type

    def _bind_update(self, stmt):
        self.scopes.append({}); self._register_scope(stmt.table, stmt.table_alias)
        if stmt.where_condition: self._visit_expression(stmt.where_condition)
        for c in stmt.set_clauses: self._check_type_compatibility(self._visit_expression(c.column), self._visit_expression(c.right), "SET assignment")
        self.scopes.pop()

    def _bind_delete(self, stmt):
        self.scopes.append({}); self._register_scope(stmt.table, stmt.table_alias)
        if stmt.where_condition: self._visit_expression(stmt.where_condition)
        self.scopes.pop()

    def _bind_insert(self, stmt):
        self.scopes.append({}); self._register_scope(stmt.table, None); tn = stmt.table.name.upper()
        if stmt.columns:
            for c in stmt.columns:
                if self.registry.get_columns(tn) and not self.registry.has_column(tn, c.name.upper()):
                    raise SemanticError(f"Column '{c.name}' not found in '{tn.capitalize()}'")
        col_names = [c.name.upper() for c in stmt.columns] if stmt.columns else self.registry.get_columns(tn)
        if len(col_names) != len(stmt.values):
            raise SemanticError(f"Column count mismatch: Expected {len(col_names)}, got {len(stmt.values)}")
        for i, v in enumerate(stmt.values):
            rt = self._visit_expression(v)
            if col_names:
                lt = self.registry.get_column_type(tn, col_names[i])
                self._check_type_compatibility(lt, rt, f"INSERT into '{col_names[i]}'")
        self.scopes.pop()

    def _bind_truncate(self, stmt):
        rt = stmt.table.name.upper()
        if not self.registry.has_table(rt): raise SemanticError(f"Table '{stmt.table.name}' not found")

    def _bind_bulk_insert(self, stmt):
        if not self.registry.has_table(stmt.table.name.upper()): raise SemanticError(f"Table '{stmt.table.name}' not found")

    def _check_type_compatibility(self, lt, rt, ctx):
        if not self._is_type_compatible(lt, rt): raise SemanticError(f"Incompatible types for {ctx}: Cannot compare {lt} with {rt}")

    def _is_agg_raw(self, expr):
        if isinstance(expr, FunctionCallNode): return self.registry.is_aggregate(expr.name) or any(self._is_agg_raw(a) for a in expr.args)
        if isinstance(expr, BinaryExpressionNode): return self._is_agg_raw(expr.left) or self._is_agg_raw(expr.right)
        if isinstance(expr, CaseExpressionNode):
            if expr.input_expr and self._is_agg_raw(expr.input_expr): return True
            for w, t in expr.branches:
                if self._is_agg_raw(w) or self._is_agg_raw(t): return True
            return self._is_agg_raw(expr.else_expr) if expr.else_expr else False
        return False

    def _check_agg_integrity(self, expr, groups):
        if self._is_agg_raw(expr):
            if isinstance(expr, CaseExpressionNode):
                if expr.input_expr: self._check_agg_integrity(expr.input_expr, groups)
                for w, t in expr.branches: 
                    self._check_agg_integrity(w, groups)
                    if not self._is_agg_raw(t): self._check_agg_integrity(t, groups)
                if expr.else_expr and not self._is_agg_raw(expr.else_expr): self._check_agg_integrity(expr.else_expr, groups)
            return
        from birdeye.serializer import ASTSerializer
        def _c(n):
            s = ASTSerializer(); d = s._serialize(n)
            if isinstance(d, dict) and "alias" in d: del d["alias"]
            return d
        e_j = _c(expr)
        for g in groups:
            if _c(g) == e_j: return
        if isinstance(expr, IdentifierNode):
            if not any(isinstance(g, IdentifierNode) and g.name.upper() == expr.name.upper() for g in groups):
                raise SemanticError(f"Column '{expr.name}' must appear in the GROUP BY clause or be used in an aggregate function")
        elif isinstance(expr, BinaryExpressionNode): self._check_agg_integrity(expr.left, groups); self._check_agg_integrity(expr.right, groups)
        elif isinstance(expr, FunctionCallNode):
            for a in expr.args: self._check_agg_integrity(a, groups)
        elif isinstance(expr, CaseExpressionNode):
            if expr.input_expr: self._check_agg_integrity(expr.input_expr, groups)
            for w, t in expr.branches: self._check_agg_integrity(w, groups); self._check_agg_integrity(t, groups)
            if expr.else_expr: self._check_agg_integrity(expr.else_expr, groups)

    def _expand_global_star(self, stmt):
        for al, rt in self.scopes[-1].items():
            cols = self.cte_schemas[rt].keys() if rt in self.cte_schemas else self.registry.get_columns(rt)
            for c in cols:
                n = IdentifierNode(name=c, qualifiers=[al])
                n.inferred_type = self.cte_schemas[rt][c] if rt in self.cte_schemas else self.registry.get_column_type(rt, c)
                stmt.columns.append(n)

    def _expand_qualified_star(self, stmt, prefix):
        up = prefix.upper()
        if up not in self.scopes[-1]: raise SemanticError(f"Unknown qualifier '{prefix}' in star expansion")
        rt = self.scopes[-1][up]
        cols = self.cte_schemas[rt].keys() if rt in self.cte_schemas else self.registry.get_columns(rt)
        for c in cols:
            n = IdentifierNode(name=c, qualifiers=[prefix])
            n.inferred_type = self.cte_schemas[rt][c] if rt in self.cte_schemas else self.registry.get_column_type(rt, c)
            stmt.columns.append(n)
