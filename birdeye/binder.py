# birdeye/binder.py (v6.7)
from birdeye.ast import (
    SelectStatement, UpdateStatement, DeleteStatement, InsertStatement,
    SqlBulkCopyStatement, IdentifierNode, BinaryExpressionNode,
    FunctionCallNode, LiteralNode, OrderByNode, CaseExpressionNode,
    BetweenExpressionNode, CastExpressionNode, UnionStatement, CTENode,
    TruncateStatement, DeclareStatement, ApplyNode,
    IfStatement, ExecStatement, SetStatement,
    CreateTableStatement, DropTableStatement, AlterTableStatement,
    MergeStatement, MergeClauseNode, PrintStatement
)

class SemanticError(Exception):
    pass

class Binder:
    def __init__(self, registry):
        self.registry = registry
        self.scopes = []; self.nullable_stack = []; self._last_root_nullables = set()
        self.cte_schemas = {}
        self.variable_scope = {}  # Issue #51: @var_name.upper() → type str
        self.temp_schemas = {}    # Issue #52: #TABLE_NAME.upper() → {COL: type}

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
        elif isinstance(stmt, DeclareStatement): self._bind_declare(stmt)
        elif isinstance(stmt, IfStatement): self._bind_if(stmt)
        elif isinstance(stmt, ExecStatement): self._bind_exec(stmt)
        elif isinstance(stmt, SetStatement): self._bind_set(stmt)
        elif isinstance(stmt, CreateTableStatement): self._bind_create_table(stmt)
        elif isinstance(stmt, DropTableStatement): pass  # no semantic check needed
        elif isinstance(stmt, AlterTableStatement): pass  # no semantic check needed
        elif isinstance(stmt, MergeStatement): self._bind_merge(stmt)
        elif isinstance(stmt, PrintStatement): self._bind_print(stmt)
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
        if stmt.table: self._register_scope_node(stmt.table, stmt.table_alias)
        for j in stmt.joins:
            al = (j.alias or j.table.name).upper()
            if j.type == "LEFT": self.nullable_stack[-1].add(al)
            elif j.type == "RIGHT": self.nullable_stack[-1].update(self.scopes[-1].keys())
            elif j.type == "FULL": self.nullable_stack[-1].add(al); self.nullable_stack[-1].update(self.scopes[-1].keys())
            self._register_scope_node(j.table, j.alias)
            if j.on_condition: self._visit_expression(j.on_condition)
        # Issue #53: APPLY — 橫向作用域：子查詢在外側 scope 已存在時綁定，可見外側欄位
        for apply in (stmt.applies if hasattr(stmt, 'applies') else []):
            self._bind_apply(apply)
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
        # Issue #52: SELECT INTO → 動態註冊臨時表 schema
        if hasattr(stmt, 'into_table') and stmt.into_table:
            schema = {}
            for col in stmt.columns:
                col_name = (col.alias if hasattr(col, 'alias') and col.alias else col.name).upper()
                schema[col_name] = col.inferred_type
            self.temp_schemas[stmt.into_table.name.upper()] = schema
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
            lc = left_cols[i]
            col_name = (lc.alias if lc.alias else
                        (lc.name if isinstance(lc, IdentifierNode) else None) or f"col_{i+1}")
            new_col = IdentifierNode(name=col_name)
            new_col.inferred_type = lt if lt != "UNKNOWN" else rt
            stmt.columns.append(new_col)

    def _virtual_schema(self, rt):
        """Issue #52: 回傳 CTE 或臨時表的 schema dict，兩者皆無則回傳 None。"""
        if rt in self.cte_schemas: return self.cte_schemas[rt]
        if rt in self.temp_schemas: return self.temp_schemas[rt]
        return None

    def _register_scope_node(self, table_node, alias):
        """統一處理 IdentifierNode 與衍生資料表 (SelectStatement) 的 scope 註冊"""
        if isinstance(table_node, (SelectStatement, UnionStatement)):
            # 衍生資料表：先綁定子查詢，再用 alias 註冊其投影欄位
            self._bind_select(table_node) if isinstance(table_node, SelectStatement) else self._bind_union(table_node)
            schema = {}
            cols = table_node.columns if hasattr(table_node, 'columns') else []
            for col in cols:
                col_name = (col.alias if hasattr(col, 'alias') and col.alias else col.name).upper()
                schema[col_name] = col.inferred_type
            key = alias.upper() if alias else "DERIVED"
            self.cte_schemas[key] = schema
            self.scopes[-1][key] = key
        else:
            self._register_scope(table_node, alias)

    @staticmethod
    def _table_key(table_node) -> str:
        """Build registry lookup key: 'SCHEMA.TABLE' or 'TABLE'."""
        name_up = table_node.name.upper()
        if table_node.qualifiers:
            return f"{table_node.qualifiers[0].upper()}.{name_up}"
        return name_up

    def _register_scope(self, table_node, alias):
        rt = self._table_key(table_node)
        table_name_up = table_node.name.upper()
        is_temp = table_name_up.startswith('#')
        if not is_temp and self._virtual_schema(rt) is None and not self.registry.has_table(rt):
            raise SemanticError(f"Table '{table_node.name}' not found")
        scope_key = alias.upper() if alias else table_name_up
        self.scopes[-1][scope_key] = rt

    # T-SQL 日期部分識別符，作為 DATEADD/DATEDIFF/DATEPART 等函數的第一個參數
    _DATE_PARTS = {
        "YEAR","QUARTER","MONTH","DAYOFYEAR","DAY","WEEK","WEEKDAY",
        "HOUR","MINUTE","SECOND","MILLISECOND","MICROSECOND","NANOSECOND",
        "YY","YYYY","QQ","Q","MM","M","DY","Y","DD","D","WK","WW","DW","W",
        "HH","MI","N","SS","S","MS","MCS","NS","TZO","ISO_WEEK","ISOWK","ISOWW"
    }

    def _resolve_identifier(self, node):
        if node.name == "*": return
        # 日期部分識別符：不走欄位解析，直接視為合法字面值
        if node.name.upper() in self._DATE_PARTS and not node.qualifiers:
            node.inferred_type = "NVARCHAR"; return
        # Issue #51: @var 走變數作用域，不走欄位解析
        if node.name.startswith("@"):
            key = node.name.upper()
            if key in self.variable_scope:
                node.inferred_type = self.variable_scope[key]
                return
            raise SemanticError(f"Variable '{node.name}' is not declared")
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
                    vs = self._virtual_schema(rt)
                    if vs is not None:
                        if col_up in vs: node.inferred_type = vs[col_up]; return
                        raise SemanticError(f"Column '{node.name}' not found in '{rt.capitalize()}'")
                    if self.registry.has_column(rt, col_up):
                        node.inferred_type = self.registry.get_column_type(rt, col_up); return
                    if self.registry.get_columns(rt):
                        raise SemanticError(f"Column '{node.name}' not found in '{rt.capitalize()}'")
                    return
            else:
                matches = []
                for sn, rt in scope.items():
                    vs = self._virtual_schema(rt)
                    if vs is not None:
                        if col_up in vs: matches.append((sn, rt))
                    elif self.registry.has_column(rt, col_up):
                        matches.append((sn, rt))
                if len(matches) > 1:
                    t_str = ", ".join(sorted([m[1].upper() for m in matches]))
                    raise SemanticError(f"Column '{node.name}' is ambiguous. Found in: {t_str}")
                if len(matches) == 1:
                    rt = matches[0][1]
                    vs = self._virtual_schema(rt)
                    node.inferred_type = vs[col_up] if vs is not None else self.registry.get_column_type(rt, col_up)
                    # 僅保留不含 schema 的 table name，讓 intent_extractor 能
                    # 正確從 alias_map 反查 (schema, table)。
                    node.resolved_table = rt.split('.')[-1]
                    return
                if len(scope) == 1:
                    sn, rt = list(scope.items())[0]
                    vs = self._virtual_schema(rt)
                    if vs is not None:
                        if col_up in vs:
                            node.inferred_type = vs[col_up]  # pragma: no cover
                            return  # pragma: no cover
                        if vs:  # 有 schema 但欄位不存在
                            raise SemanticError(f"Column '{node.name}' not found in '{rt.capitalize()}'")
                        return  # 空 schema (未知臨時表) → 放行
                    elif self.registry.has_column(rt, col_up):
                        node.inferred_type = self.registry.get_column_type(rt, col_up)  # pragma: no cover
                        return  # pragma: no cover
                    elif self.registry.get_columns(rt):
                        raise SemanticError(f"Column '{node.name}' not found in '{rt.capitalize()}'")
        if f_qual and not found_qual: raise SemanticError(f"Unknown qualifier '{node.qualifier}'")
        raise SemanticError(f"Column '{node.name}' not found")

    def _is_type_compatible(self, type1, type2):
        if type1 == type2 or type1 == "UNKNOWN" or type2 == "UNKNOWN" or type1 == "TABLE" or type2 == "TABLE": return True
        NUMS    = {"INT", "DECIMAL", "FLOAT", "MONEY", "SMALLINT", "TINYINT", "BIGINT", "NUMERIC", "REAL", "SMALLMONEY", "BIT", "FLAG", "NAMESTYLE"}
        STRS    = {"NVARCHAR", "VARCHAR", "STRING", "CHAR", "NCHAR", "SYSNAME", "UNIQUEIDENTIFIER", "HIERARCHYID", "NAME", "ORDERNUMBER", "ACCOUNTNUMBER", "PHONE", "TEXT", "NTEXT"}
        DATES   = {"DATETIME", "DATE", "TIME", "DATETIME2", "SMALLDATETIME", "DATETIMEOFFSET"}
        SPATIAL = {"GEOGRAPHY", "GEOMETRY"}               # Issue #54
        BINARY  = {"VARBINARY", "BINARY", "IMAGE"}        # Issue #54
        XML_T   = {"XML"}                                 # Issue #54
        if type1 in NUMS    and type2 in NUMS:    return True
        if type1 in STRS    and type2 in STRS:    return True
        if type1 in DATES   and type2 in DATES:   return True
        if type1 in SPATIAL and type2 in SPATIAL: return True
        if type1 in BINARY  and type2 in BINARY:  return True
        if type1 in XML_T   and type2 in XML_T:   return True
        if (type1 in DATES and type2 in STRS) or (type1 in STRS and type2 in DATES): return True
        return False

    def _visit_expression(self, expr) -> str:
        if isinstance(expr, IdentifierNode): self._resolve_identifier(expr); return expr.inferred_type
        elif isinstance(expr, LiteralNode): return "INT" if expr.inferred_type == "DECIMAL" else expr.inferred_type
        elif isinstance(expr, BinaryExpressionNode):
            rt_raw = self._visit_expression(expr.right)
            lt = self._visit_expression(expr.left)
            rt = lt if rt_raw == "TABLE" else rt_raw
            
            if expr.operator in ["+", "-", "*", "/", "%", "&", "|", "^", "~"]:
                if expr.operator == "+":
                    is_num = self._is_type_compatible(lt, "INT") and self._is_type_compatible(rt, "INT")
                    is_str = self._is_type_compatible(lt, "NVARCHAR") and self._is_type_compatible(rt, "NVARCHAR")
                    if not (is_num or is_str): raise SemanticError(f"Operator '+' cannot be applied to {lt} and {rt}")
                    expr.inferred_type = "INT" if is_num else "NVARCHAR"
                else:
                    if not self._is_type_compatible(lt, "INT") or not self._is_type_compatible(rt, "INT"): raise SemanticError(f"Operator '{expr.operator}' cannot be applied")
                    expr.inferred_type = "INT"
            elif expr.operator in ["=", ">", "<", ">=", "<=", "<>", "IN", "NOT IN", "LIKE", "NOT LIKE", "IS NULL", "IS NOT NULL"] or " ANY" in expr.operator or " ALL" in expr.operator:
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
                elif expr.operator in ["IN", "NOT IN"]:
                    # Issue #60: IN / NOT IN list or subquery
                    if isinstance(expr.right, list):
                        for item in expr.right:
                            it = self._visit_expression(item)
                            if not self._is_type_compatible(lt, it):
                                raise SemanticError(f"Incompatible types in {expr.operator}: {lt} vs {it}")
                    elif isinstance(expr.right, (SelectStatement, UnionStatement)):
                        self._bind_node(expr.right)
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
            # MAX/MIN: 回傳型別跟著第一個參數的型別
            if f_meta.return_type == "ANY" and expr.args:
                arg_type = self._visit_expression(expr.args[0]) if not hasattr(expr.args[0], 'inferred_type') or expr.args[0].inferred_type == "UNKNOWN" else expr.args[0].inferred_type
                expr.inferred_type = arg_type if arg_type != "UNKNOWN" else "ANY"
            else:
                expr.inferred_type = f_meta.return_type
            return expr.inferred_type
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
        elif isinstance(expr, SelectStatement):
            self._bind_select(expr)
            # 純量子查詢：取第一個投影欄位的型別
            if expr.columns and len(expr.columns) == 1:
                expr.inferred_type = expr.columns[0].inferred_type
            else:
                expr.inferred_type = "UNKNOWN"
            return expr.inferred_type
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
        for cte in (stmt.ctes if hasattr(stmt, 'ctes') else []):
            self._bind_node(cte.query)
            cols = {(c.alias or c.name).upper(): c.inferred_type for c in cte.query.columns}
            self.cte_schemas[cte.name.upper()] = cols
        self.scopes.append({}); self._register_scope(stmt.table, stmt.table_alias)
        if stmt.where_condition: self._visit_expression(stmt.where_condition)
        for c in stmt.set_clauses: self._check_type_compatibility(self._visit_expression(c.column), self._visit_expression(c.right), "SET assignment")
        self.scopes.pop()

    def _bind_delete(self, stmt):
        for cte in (stmt.ctes if hasattr(stmt, 'ctes') else []):
            self._bind_node(cte.query)
            cols = {(c.alias or c.name).upper(): c.inferred_type for c in cte.query.columns}
            self.cte_schemas[cte.name.upper()] = cols
        self.scopes.append({}); self._register_scope(stmt.table, stmt.table_alias)
        if stmt.where_condition: self._visit_expression(stmt.where_condition)
        self.scopes.pop()

    def _bind_insert(self, stmt):
        self.scopes.append({}); self._register_scope(stmt.table, None); tn = self._table_key(stmt.table)
        if stmt.columns:
            for c in stmt.columns:
                if self.registry.get_columns(tn) and not self.registry.has_column(tn, c.name.upper()):
                    raise SemanticError(f"Column '{c.name}' not found in '{tn.capitalize()}'")
        col_names = [c.name.upper() for c in stmt.columns] if stmt.columns else self.registry.get_columns(tn)
        # Issue #57: INSERT-SELECT
        if stmt.source is not None:
            self._bind_node(stmt.source)
            src_cols = stmt.source.columns if hasattr(stmt.source, 'columns') else []
            if col_names and len(col_names) != len(src_cols):
                raise SemanticError(f"Column count mismatch: Expected {len(col_names)}, got {len(src_cols)}")
            for i, col in enumerate(src_cols):
                if col_names:
                    lt = self.registry.get_column_type(tn, col_names[i])
                    self._check_type_compatibility(lt, col.inferred_type, f"INSERT into '{col_names[i]}'")
            self.scopes.pop(); return
        # Issue #58: Multi-row VALUES
        rows = stmt.value_rows if stmt.value_rows else [stmt.values]
        for row in rows:
            if col_names and len(col_names) != len(row):
                raise SemanticError(f"Column count mismatch: Expected {len(col_names)}, got {len(row)}")
            for i, v in enumerate(row):
                rt = self._visit_expression(v)
                if col_names:
                    lt = self.registry.get_column_type(tn, col_names[i])
                    self._check_type_compatibility(lt, rt, f"INSERT into '{col_names[i]}'")
        self.scopes.pop()

    def _bind_truncate(self, stmt):
        rt = self._table_key(stmt.table)
        if not self.registry.has_table(rt): raise SemanticError(f"Table '{stmt.table.name}' not found")

    def _bind_bulk_insert(self, stmt):
        if not self.registry.has_table(self._table_key(stmt.table)): raise SemanticError(f"Table '{stmt.table.name}' not found")

    def _bind_declare(self, stmt):
        """Issue #51: 將 @var 及其型別寫入 variable_scope"""
        self.variable_scope[stmt.var_name.upper()] = stmt.var_type
        if stmt.default_value:
            self._visit_expression(stmt.default_value)

    def _bind_if(self, stmt):
        """Bind IF/ELSE block — recursively bind condition and sub-statements."""
        if stmt.condition:
            self._visit_expression(stmt.condition)
        for s in (stmt.then_block or []):
            self._bind_node(s)
        for s in (stmt.else_block or []):
            self._bind_node(s)

    def _bind_exec(self, stmt):
        """ZTA enforcement: block dangerous stored procedures."""
        BLOCKED = {"XP_CMDSHELL", "SP_EXECUTESQL", "SP_OA_CREATE", "SP_OA_METHOD",
                   "SP_OA_GETPROPERTY", "SP_CONFIGURE", "OPENROWSET", "OPENQUERY"}
        proc_name_str = stmt.proc_name.name if hasattr(stmt.proc_name, 'name') else str(stmt.proc_name)
        if proc_name_str.upper() in BLOCKED:
            raise SemanticError(f"Stored procedure '{proc_name_str}' is blocked by ZTA policy")
        for a in (stmt.args or []):
            self._visit_expression(a)

    def _bind_set(self, stmt):
        """Bind SET @var = expr; update variable_scope if setting a declared variable."""
        if not stmt.is_option and stmt.target and hasattr(stmt.target, 'name'):
            var_key = stmt.target.name.upper()
            if stmt.value:
                t = self._visit_expression(stmt.value)
                self.variable_scope[var_key] = t or self.variable_scope.get(var_key, "UNKNOWN")
        elif stmt.value:
            self._visit_expression(stmt.value)

    def _bind_create_table(self, stmt):
        """Register temp table schema so subsequent queries can reference it."""
        if stmt.table and hasattr(stmt.table, 'name'):
            tname = stmt.table.name.upper()
            if tname.startswith('#'):
                schema = {}
                for col in (stmt.columns or []):
                    schema[col.name.upper()] = col.data_type.upper()
                self.temp_schemas[tname] = schema

    def _bind_merge(self, stmt):
        """Bind MERGE statement — check source/target tables and clause expressions."""
        if stmt.on_condition:
            self._visit_expression(stmt.on_condition)
        for clause in (stmt.clauses or []):
            if clause.condition:
                self._visit_expression(clause.condition)
            for sc in (clause.set_clauses or []):
                if hasattr(sc, 'right') and sc.right:
                    self._visit_expression(sc.right)

    def _bind_print(self, stmt):
        """Bind PRINT expression."""
        if stmt.expr:
            self._visit_expression(stmt.expr)

    def _bind_apply(self, apply):
        """
        Issue #53: 綁定 CROSS/OUTER APPLY 子查詢。
        橫向作用域：子查詢在外側 scope 仍在堆疊上時進行綁定，
        因此子查詢的 WHERE 條件可以參照外側表的欄位。
        綁定完成後，將子查詢投影欄位注冊為 cte_schemas，使外側查詢可存取。
        """
        # 直接呼叫 _bind_select（不呼叫 bind() 以免重置 scope stack）
        self._bind_select(apply.subquery)
        # 收集子查詢的投影欄位作為 schema
        schema = {}
        for col in apply.subquery.columns:
            col_name = (col.alias if hasattr(col, 'alias') and col.alias else col.name).upper()
            schema[col_name] = col.inferred_type
        apply.columns = list(apply.subquery.columns)
        # 用 alias 注冊到 cte_schemas，讓外側 SELECT 可以 sub.City 方式存取
        if apply.alias:
            alias_up = apply.alias.upper()
            self.cte_schemas[alias_up] = schema
            self.scopes[-1][alias_up] = alias_up
            if apply.type == "OUTER":
                self.nullable_stack[-1].add(alias_up)

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
        def _strip(d):
            if isinstance(d, dict):
                d.pop("alias", None)
                d.pop("resolved_table", None)   # 排除 binder 運行時序造成的差異
                for v in d.values(): _strip(v)
            elif isinstance(d, list):
                for item in d: _strip(item)
        def _c(n):
            s = ASTSerializer(); d = s._serialize(n)
            _strip(d); return d
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
            vs = self._virtual_schema(rt)
            cols = vs.keys() if vs is not None else self.registry.get_columns(rt)
            for c in cols:
                n = IdentifierNode(name=c, qualifiers=[al])
                n.inferred_type = vs[c] if vs is not None else self.registry.get_column_type(rt, c)
                stmt.columns.append(n)

    def _expand_qualified_star(self, stmt, prefix):
        up = prefix.upper()
        if up not in self.scopes[-1]: raise SemanticError(f"Unknown qualifier '{prefix}' in star expansion")
        rt = self.scopes[-1][up]
        vs = self._virtual_schema(rt)
        cols = vs.keys() if vs is not None else self.registry.get_columns(rt)
        for c in cols:
            n = IdentifierNode(name=c, qualifiers=[prefix])
            n.inferred_type = vs[c] if vs is not None else self.registry.get_column_type(rt, c)
            stmt.columns.append(n)
