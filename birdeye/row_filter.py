"""
RowFilterInjector: 將 Permission API 回傳的 RowFilter 條件注入 AST JSON 的 WHERE 子句，
實現 AP 與 DB 之間的零信任列層過濾（Row-Level Security）。

支援:
  ValueType=LITERAL  — =, <>, <, >, <=, >=, LIKE, IN, NOT IN
  ValueType=SUBQUERY — =, <>, IN, NOT IN；Value 需由 BirdEyeClient 預先解析為
                       SelectStatement AST dict（raw SQL 字串會觸發 ValueError）

適用語句: SelectStatement, UpdateStatement, DeleteStatement
遞迴範圍: ScriptNode, UnionStatement, IfStatement, CTE, FROM/JOIN/APPLY 子查詢,
          以及 WHERE / HAVING / ORDER BY / 投影欄位中的純量與 IN 子查詢
"""
from __future__ import annotations

import copy
import re

# 只接受 ASCII 整數、十進位小數、以及指數 ≤ 3 位的科學記號
# re.ASCII 確保 \d 只比對 [0-9]，避免全形數字（＄、４２）被誤判為數值
_NUMERIC_RE = re.compile(r'^-?\d+(\.\d+)?([eE][+-]?\d{1,3})?$', re.ASCII)


class RowFilterInjector:
    """
    走訪 ASTSerializer 輸出的 JSON dict，對每個查詢指定資料表的語句注入額外 WHERE 條件。
    不修改傳入的 ast_json；回傳 deep-copy 後注入結果的新 dict。
    """

    def inject(self, ast_json: dict, row_filters: list[dict]) -> dict:
        if not row_filters:
            return ast_json
        ast = copy.deepcopy(ast_json)
        self._walk(ast, row_filters)
        return ast

    # ── AST 走訪 ──────────────────────────────────────────────────────────────

    def _walk(self, node, row_filters: list[dict]) -> None:
        if node is None:
            return
        if isinstance(node, list):
            for item in node:
                self._walk(item, row_filters)
            return
        if not isinstance(node, dict):
            return

        nt = node.get("node_type", "")

        if nt == "ScriptNode":
            for stmt in (node.get("statements") or []):
                self._walk(stmt, row_filters)

        elif nt == "SelectStatement":
            # 先遞迴子查詢（CTE / FROM / JOIN / APPLY / 運算式），
            # 再對本語句自己的資料表注入條件（由內而外，避免重複注入）
            self._walk_subqueries_in_select(node, row_filters)
            entries = self._build_alias_entries(node)
            applicable = self._match_filters(entries, row_filters)
            if applicable:
                conds = [self._make_condition(f, entries) for f in applicable]
                node["where"] = self._and_conditions(node.get("where"), conds)

        elif nt in ("UpdateStatement", "DeleteStatement"):
            entries = self._build_alias_entries_dml(node)
            applicable = self._match_filters(entries, row_filters)
            if applicable:
                conds = [self._make_condition(f, entries) for f in applicable]
                node["where"] = self._and_conditions(node.get("where"), conds)

        elif nt == "UnionStatement":
            self._walk(node.get("left"),  row_filters)
            self._walk(node.get("right"), row_filters)

        elif nt == "IfStatement":
            for stmt in list(node.get("then_block") or []) + list(node.get("else_block") or []):
                self._walk(stmt, row_filters)

    def _walk_subqueries_in_select(self, node: dict, row_filters: list[dict]) -> None:
        for cte in (node.get("ctes") or []):
            self._walk(cte.get("query"), row_filters)

        tbl = node.get("table")
        if tbl and tbl.get("node_type") in ("SelectStatement", "UnionStatement"):
            self._walk(tbl, row_filters)

        for join in (node.get("joins") or []):
            jt = join.get("table")
            if jt and jt.get("node_type") in ("SelectStatement", "UnionStatement"):
                self._walk(jt, row_filters)

        for ap in (node.get("applies") or []):
            self._walk(ap.get("subquery"), row_filters)

        for col in (node.get("columns") or []):
            self._walk_expr(col, row_filters)
        self._walk_expr(node.get("where"),  row_filters)
        self._walk_expr(node.get("having"), row_filters)
        for ob in (node.get("order_by") or []):
            self._walk_expr(ob.get("column"), row_filters)

    def _walk_expr(self, node, row_filters: list[dict]) -> None:
        """走訪運算式節點，對內嵌子查詢遞迴注入 filter。"""
        if node is None:
            return
        if isinstance(node, list):
            for item in node:
                self._walk_expr(item, row_filters)
            return
        if not isinstance(node, dict):
            return

        nt = node.get("node_type", "")
        if nt in ("SelectStatement", "UnionStatement"):
            self._walk(node, row_filters)
        elif nt == "BinaryExpressionNode":
            self._walk_expr(node.get("left"), row_filters)
            right = node.get("right")
            if isinstance(right, list):
                for item in right:
                    self._walk_expr(item, row_filters)
            else:
                self._walk_expr(right, row_filters)
        elif nt == "FunctionCallNode":
            for arg in (node.get("args") or []):
                self._walk_expr(arg, row_filters)
        elif nt == "CastExpressionNode":
            self._walk_expr(node.get("expr"), row_filters)
        elif nt == "BetweenExpressionNode":
            for k in ("target", "low", "high"):
                self._walk_expr(node.get(k), row_filters)
        elif nt == "CaseExpressionNode":
            self._walk_expr(node.get("input"), row_filters)
            for branch in (node.get("branches") or []):
                self._walk_expr(branch.get("when"), row_filters)
                self._walk_expr(branch.get("then"), row_filters)
            self._walk_expr(node.get("else"), row_filters)

    # ── alias entries ──────────────────────────────────────────────────────────
    # 每個 entry: (schema_upper, table_upper, qualifier)
    # qualifier = alias（若有）否則資料表名稱原始大小寫

    def _build_alias_entries(self, select_node: dict) -> list[tuple[str, str, str]]:
        entries: list[tuple[str, str, str]] = []

        def _reg(tbl_node, alias):
            if not tbl_node or tbl_node.get("node_type") != "IdentifierNode":
                return
            quals = tbl_node.get("qualifiers") or []
            name  = tbl_node.get("name") or ""
            if not name:
                return
            schema = quals[0] if quals else ""
            entries.append((schema.upper(), name.upper(), alias or name))

        _reg(select_node.get("table"), select_node.get("alias"))
        for join in (select_node.get("joins") or []):
            _reg(join.get("table"), join.get("alias"))
        return entries

    def _build_alias_entries_dml(self, node: dict) -> list[tuple[str, str, str]]:
        tbl = node.get("table")
        if not tbl or tbl.get("node_type") != "IdentifierNode":
            return []
        quals  = tbl.get("qualifiers") or []
        name   = tbl.get("name") or ""
        if not name:
            return []
        schema = quals[0] if quals else ""
        return [(schema.upper(), name.upper(), node.get("alias") or name)]

    # ── filter matching ────────────────────────────────────────────────────────

    def _match_filters(
        self, entries: list[tuple[str, str, str]], row_filters: list[dict]
    ) -> list[dict]:
        result = []
        for f in row_filters:
            s_up = (f.get("Schema") or "").upper()
            t_up = (f.get("Table")  or "").upper()
            for (s, t, _q) in entries:
                if t == t_up and (not s_up or s == s_up):
                    result.append(f)
                    break
        return result

    # ── condition builder ──────────────────────────────────────────────────────

    def _make_condition(self, f: dict, entries: list[tuple[str, str, str]]) -> dict:
        schema   = (f.get("Schema")    or "").upper()
        table    = (f.get("Table")     or "").upper()
        column   = f.get("Column")     or ""
        operator = (f.get("Operator")  or "=").upper()
        vtype    = (f.get("ValueType") or "LITERAL").upper()
        value    = f.get("Value")      or ""

        qualifier = self._find_qualifier(schema, table, entries)
        col_node  = {
            "node_type":  "IdentifierNode",
            "name":       column,
            "qualifiers": [qualifier] if qualifier else [],
            "alias":      None,
        }

        if vtype == "SUBQUERY":
            if not isinstance(value, dict):
                raise ValueError(
                    f"RowFilter ValueType=SUBQUERY 需傳入預解析的 SelectStatement AST dict，"
                    f"請透過 BirdEyeClient.rewrite_sql() 呼叫（table={f.get('Table')}, "
                    f"column={column}）。收到型別：{type(value).__name__}"
                )
            right: dict | list = value
        elif operator in ("IN", "NOT IN"):
            items = [v.strip() for v in value.split(",") if v.strip()]
            right = [self._make_literal(v) for v in items]
        else:
            right = self._make_literal(value)

        return {
            "node_type": "BinaryExpressionNode",
            "op":        operator,
            "left":      col_node,
            "right":     right,
            "alias":     None,
        }

    @staticmethod
    def _make_literal(value: str) -> dict:
        if _NUMERIC_RE.fullmatch(value):
            return {"node_type": "LiteralNode", "value": value, "type": "NUMERIC_LITERAL", "alias": None}
        escaped = value.replace("'", "''")
        prefix = "N" if any(ord(c) > 127 for c in value) else ""
        return {"node_type": "LiteralNode", "value": f"{prefix}'{escaped}'", "type": "STRING_LITERAL", "alias": None}

    @staticmethod
    def _find_qualifier(schema_up: str, table_up: str, entries: list[tuple]) -> str:
        for (s, t, q) in entries:
            if t == table_up and (not schema_up or s == schema_up):
                return q
        return table_up

    @staticmethod
    def _and_conditions(existing, conditions: list[dict]):
        result = existing
        for cond in conditions:
            if result is None:
                result = cond
            else:
                result = {
                    "node_type": "BinaryExpressionNode",
                    "op":        "AND",
                    "left":      result,
                    "right":     cond,
                    "alias":     None,
                }
        return result
