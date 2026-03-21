"""
birdeye/reconstructor.py
AST JSON → SQL 重建器

將 ASTSerializer 輸出的 JSON dict 轉回可執行的 SQL 字串。
"""
import json


class ASTReconstructor:
    """
    將 AST JSON（dict 或 JSON 字串）重建為 SQL 字串。
    """

    def from_json_str(self, json_str: str) -> str:
        """接受 JSON 字串，回傳 SQL"""
        return self.to_sql(json.loads(json_str))

    def to_sql(self, node: dict) -> str:
        """接受 dict，回傳 SQL"""
        if node is None:
            return ""
        nt = node.get("node_type", "")
        method = getattr(self, f"_sql_{nt}", None)
        if method:
            return method(node)
        return ""

    # ─── 語句節點 ───────────────────────────────────

    def _sql_SelectStatement(self, n: dict) -> str:
        parts = []

        # CTE
        ctes = n.get("ctes") or []
        if ctes:
            cte_parts = [f"{c['name']} AS ({self.to_sql(c['query'])})" for c in ctes]
            parts.append("WITH " + ", ".join(cte_parts))

        sel = "SELECT"
        if n.get("is_distinct"):
            sel += " DISTINCT"
        top = n.get("top")
        if top is not None:
            sel += f" TOP {top}"
            if n.get("top_percent"):
                sel += " PERCENT"
        parts.append(sel)

        # columns
        if n.get("is_star"):
            cols_sql = "*"
        else:
            cols = n.get("columns") or []
            cols_sql = ", ".join(self._sql_expr(c) for c in cols)
        parts.append(cols_sql)

        # INTO
        into = n.get("into_table")
        if into:
            parts.append(f"INTO {self.to_sql(into)}")

        # FROM
        table = n.get("table")
        if table:
            parts.append("FROM")
            tbl_sql = self._sql_table_ref(table, n.get("alias"))
            parts.append(tbl_sql)

        # JOINs
        for j in (n.get("joins") or []):
            parts.append(self._sql_JoinNode(j))

        # APPLY
        for ap in (n.get("applies") or []):
            parts.append(self._sql_ApplyNode(ap))

        # WHERE
        where = n.get("where")
        if where:
            parts.append(f"WHERE {self._sql_expr(where)}")

        # GROUP BY
        groups = n.get("group_by") or []
        if groups:
            parts.append("GROUP BY " + ", ".join(self._sql_expr(g) for g in groups))

        # HAVING
        having = n.get("having")
        if having:
            parts.append(f"HAVING {self._sql_expr(having)}")

        # ORDER BY
        orders = n.get("order_by") or []
        if orders:
            parts.append("ORDER BY " + ", ".join(self._sql_OrderByNode(o) for o in orders))

        # OFFSET / FETCH
        offset = n.get("offset_count")
        if offset is not None:
            parts.append(f"OFFSET {offset} ROWS")
            fetch = n.get("fetch_count")
            if fetch is not None:
                parts.append(f"FETCH NEXT {fetch} ROWS ONLY")

        return " ".join(parts)

    def _sql_UnionStatement(self, n: dict) -> str:
        left = self.to_sql(n["left"])
        right = self.to_sql(n["right"])
        op = n.get("op") or n.get("operator", "UNION")
        return f"{left} {op} {right}"

    def _sql_UpdateStatement(self, n: dict) -> str:
        parts = []
        ctes = n.get("ctes") or []
        if ctes:
            cte_parts = [f"{c['name']} AS ({self.to_sql(c['query'])})" for c in ctes]
            parts.append("WITH " + ", ".join(cte_parts))

        tbl = self._sql_table_ref(n["table"], n.get("alias"))
        sets = ", ".join(self._sql_AssignmentNode(s) for s in (n.get("set_clauses") or []))
        parts.append(f"UPDATE {tbl} SET {sets}")
        where = n.get("where_condition") or n.get("where")
        if where:
            parts.append(f"WHERE {self._sql_expr(where)}")
        return " ".join(parts)

    def _sql_DeleteStatement(self, n: dict) -> str:
        parts = []
        ctes = n.get("ctes") or []
        if ctes:
            cte_parts = [f"{c['name']} AS ({self.to_sql(c['query'])})" for c in ctes]
            parts.append("WITH " + ", ".join(cte_parts))

        tbl = self._sql_table_ref(n["table"], n.get("alias"))
        parts.append(f"DELETE FROM {tbl}")
        where = n.get("where_condition") or n.get("where")
        if where:
            parts.append(f"WHERE {self._sql_expr(where)}")
        return " ".join(parts)

    def _sql_InsertStatement(self, n: dict) -> str:
        tbl = self.to_sql(n["table"])
        cols = n.get("columns") or []
        col_list = ""
        if cols:
            col_list = " (" + ", ".join(self.to_sql(c) for c in cols) + ")"

        source = n.get("source")
        if source:
            return f"INSERT INTO {tbl}{col_list} {self.to_sql(source)}"

        rows = n.get("value_rows") or []
        if not rows:
            single = n.get("values") or []
            rows = [single] if single else []
        row_sqls = []
        for row in rows:
            row_sqls.append("(" + ", ".join(self._sql_expr(v) for v in row) + ")")
        return f"INSERT INTO {tbl}{col_list} VALUES {', '.join(row_sqls)}"

    def _sql_TruncateStatement(self, n: dict) -> str:
        return f"TRUNCATE TABLE {self.to_sql(n['table'])}"

    def _sql_DeclareStatement(self, n: dict) -> str:
        sql = f"DECLARE {n['var_name']} {n['var_type']}"
        if n.get("default_value"):
            sql += f" = {self._sql_expr(n['default_value'])}"
        return sql

    # ─── 表達式節點 ─────────────────────────────────

    def _sql_expr(self, node: dict) -> str:
        """統一表達式分派入口（支援別名）"""
        if node is None:
            return "NULL"
        if isinstance(node, list):
            return "(" + ", ".join(self._sql_expr(x) for x in node) + ")"
        nt = node.get("node_type", "")
        method = getattr(self, f"_sql_{nt}", None)
        sql = method(node) if method else self.to_sql(node)
        alias = node.get("alias")
        if alias:
            sql += f" AS {alias}"
        return sql

    def _sql_IdentifierNode(self, n: dict) -> str:
        parts = list(n.get("qualifiers") or []) + [n["name"]]
        return ".".join(parts)

    def _sql_LiteralNode(self, n: dict) -> str:
        v = n.get("value", "")
        t = n.get("type", "")
        if t == "STRING_LITERAL":
            # 加回單引號（若尚未有）
            if not (v.startswith("'") and v.endswith("'")):
                v = f"'{v}'"
        return v

    def _sql_BinaryExpressionNode(self, n: dict) -> str:
        op = n.get("op") or n.get("operator", "")
        left = self._sql_expr(n["left"])
        right_raw = n.get("right")

        if op in ("IS NULL", "IS NOT NULL"):
            return f"{left} {op}"

        if op in ("IN", "NOT IN"):
            if isinstance(right_raw, list):
                items = ", ".join(self._sql_expr(x) for x in right_raw)
                return f"{left} {op} ({items})"
            return f"{left} {op} ({self._sql_expr(right_raw)})"

        right = self._sql_expr(right_raw)
        # 加括號避免優先順序問題
        if op in ("AND", "OR"):
            return f"({left} {op} {right})"
        return f"{left} {op} {right}"

    def _sql_FunctionCallNode(self, n: dict) -> str:
        name = n["name"]
        args = n.get("args") or []
        # EXISTS / NOT EXISTS 特殊形式
        if name in ("EXISTS", "NOT EXISTS"):
            inner = self._sql_expr(args[0]) if args else ""
            return f"{name} ({inner})"
        args_sql = ", ".join(self._sql_expr(a) for a in args)
        return f"{name}({args_sql})"

    def _sql_CaseExpressionNode(self, n: dict) -> str:
        parts = ["CASE"]
        inp = n.get("input") or n.get("input_expr")
        if inp:
            parts.append(self._sql_expr(inp))
        for branch in (n.get("branches") or []):
            # serializer 輸出 {"when": ..., "then": ...}；也容忍 [when, then] tuple 格式
            if isinstance(branch, dict):
                when_expr, then_expr = branch["when"], branch["then"]
            else:
                when_expr, then_expr = branch[0], branch[1]
            parts.append(f"WHEN {self._sql_expr(when_expr)} THEN {self._sql_expr(then_expr)}")
        else_expr = n.get("else") or n.get("else_expr")
        if else_expr:
            parts.append(f"ELSE {self._sql_expr(else_expr)}")
        parts.append("END")
        return " ".join(parts)

    def _sql_BetweenExpressionNode(self, n: dict) -> str:
        expr = self._sql_expr(n.get("target") or n.get("expr"))
        low = self._sql_expr(n["low"])
        high = self._sql_expr(n["high"])
        not_str = "NOT " if n.get("is_not") else ""
        return f"{expr} {not_str}BETWEEN {low} AND {high}"

    def _sql_CastExpressionNode(self, n: dict) -> str:
        expr = self._sql_expr(n["expr"])
        target = n.get("target") or n.get("target_type", "")
        if n.get("is_convert"):
            return f"CONVERT({target}, {expr})"
        return f"CAST({expr} AS {target})"

    # ─── 結構輔助節點 ────────────────────────────────

    def _sql_JoinNode(self, n: dict) -> str:
        jt = n.get("join_type") or n.get("type", "INNER")
        if jt == "INNER":
            join_kw = "JOIN"
        elif jt == "CROSS":
            join_kw = "CROSS JOIN"
        elif jt == "FULL":
            join_kw = "FULL OUTER JOIN"
        else:
            join_kw = f"{jt} JOIN"

        tbl = self._sql_table_ref(n["table"], n.get("alias"))
        on = n.get("on") or n.get("on_condition")
        on_sql = f" ON {self._sql_expr(on)}" if on else ""
        return f"{join_kw} {tbl}{on_sql}"

    def _sql_ApplyNode(self, n: dict) -> str:
        apply_kw = f"{n.get('type', 'CROSS')} APPLY"
        subq = self.to_sql(n["subquery"])
        alias = n.get("alias") or ""
        alias_sql = f" AS {alias}" if alias else ""
        return f"{apply_kw} ({subq}){alias_sql}"

    def _sql_AssignmentNode(self, n: dict) -> str:
        col = self.to_sql(n["column"])
        val = self._sql_expr(n.get("expr") or n.get("right") or n.get("expression", {}))
        return f"{col} = {val}"

    def _sql_OrderByNode(self, n: dict) -> str:
        col = self._sql_expr(n["column"])
        direction = n.get("direction", "ASC")
        return f"{col} {direction}"

    def _sql_CTENode(self, n: dict) -> str:
        return f"{n['name']} AS ({self.to_sql(n['query'])})"

    # ─── 輔助 ────────────────────────────────────────

    def _sql_table_ref(self, table_node: dict, alias: str) -> str:
        """將 table node 輸出為 TABLE_SQL [AS alias] 形式"""
        if table_node is None:
            return ""
        nt = table_node.get("node_type", "")
        if nt in ("SelectStatement", "UnionStatement"):
            inner = self.to_sql(table_node)
            alias_sql = f" AS {alias}" if alias else ""
            return f"({inner}){alias_sql}"
        tbl_sql = self.to_sql(table_node)
        alias_sql = f" AS {alias}" if alias else ""
        return f"{tbl_sql}{alias_sql}"
