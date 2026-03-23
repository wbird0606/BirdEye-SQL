"""
IntentExtractor: 走訪 ASTSerializer 產出的 JSON dict，萃取每個欄位的操作意圖。

流程：
  SQL → parser.parse() → ASTSerializer.to_json() → json.loads() → IntentExtractor.extract()

Intent 類型：
  READ   — SELECT 投影欄位（直接讀取）
  FILTER — WHERE / JOIN ON / HAVING / GROUP BY / ORDER BY（推理攻擊面）
  INSERT — INSERT 欄位清單
  UPDATE — UPDATE SET 目標欄位
  DELETE — 資料表層級（column=None）
"""

import json

INTENT_READ   = "READ"
INTENT_FILTER = "FILTER"
INTENT_INSERT = "INSERT"
INTENT_UPDATE = "UPDATE"
INTENT_DELETE = "DELETE"


class IntentExtractor:
    """
    從 AST JSON dict（或 JSON 字串）萃取欄位意圖清單（已去重）。

    用法：
        ast_json = serializer.to_json(ast)
        intents  = IntentExtractor().extract(json.loads(ast_json))
    或直接傳字串：
        intents  = IntentExtractor().extract_from_str(ast_json_str)
    """

    def extract(self, ast_dict):
        """
        入口：傳入 AST JSON dict（單一語句或 list），
        回傳 list of dict:
          [{"schema": str, "table": str, "column": str|None, "intent": str}, ...]
        """
        self._seen = set()
        intents = []
        self._walk(ast_dict, intents, cte_names=set())
        return intents

    def extract_from_str(self, json_str):
        """從 JSON 字串萃取（便利方法）。"""
        return self.extract(json.loads(json_str))

    def extract_tables(self, ast_dict):
        """
        第一遍掃描：收集 SQL 中所有真實資料表引用的 (schema, table) 集合。
        在 parse_only() 之後、執行 binder 之前呼叫，用來向 schema API 查詢欄位清單。
        回傳 list of (schema: str, table: str)。
        """
        tables = set()
        self._collect_tables(ast_dict, tables, cte_names=set())
        return list(tables)

    def _collect_tables(self, node, tables, cte_names):
        """遞迴收集所有 table 引用（含子查詢）。"""
        if not node or not isinstance(node, dict):
            return

        nt = node.get("node_type", "")

        if nt == "SelectStatement":
            local_ctes = set(cte_names)
            for cte in (node.get("ctes") or []):
                local_ctes.add(cte["name"].upper())
                self._collect_tables(cte.get("query"), tables, local_ctes)

            for key in ("table",):
                t = node.get(key)
                if t and isinstance(t, dict):
                    nt2 = t.get("node_type", "")
                    if nt2 == "IdentifierNode":
                        schema, table = self._table_info(t)
                        if table and table.upper() not in local_ctes:
                            tables.add((schema, table))
                    else:
                        self._collect_tables(t, tables, local_ctes)

            for join in (node.get("joins") or []):
                jt = join.get("table")
                if jt and jt.get("node_type") == "IdentifierNode":
                    schema, table = self._table_info(jt)
                    if table and table.upper() not in local_ctes:
                        tables.add((schema, table))

            # 走訪所有可能含子查詢的運算式
            for key in ("where", "having"):
                self._collect_tables(node.get(key), tables, local_ctes)
            for item in (node.get("group_by") or []):
                self._collect_tables(item, tables, local_ctes)
            for ob in (node.get("order_by") or []):
                self._collect_tables(ob.get("column"), tables, local_ctes)
            for ap in (node.get("applies") or []):
                self._collect_tables(ap.get("subquery"), tables, local_ctes)
            for col in (node.get("columns") or []):
                self._collect_tables(col, tables, local_ctes)

        elif nt == "UnionStatement":
            self._collect_tables(node.get("left"),  tables, cte_names)
            self._collect_tables(node.get("right"), tables, cte_names)

        elif nt in ("UpdateStatement", "DeleteStatement", "TruncateStatement"):
            t = node.get("table")
            if t and t.get("node_type") == "IdentifierNode":
                schema, table = self._table_info(t)
                if table and table.upper() not in cte_names:
                    tables.add((schema, table))
            self._collect_tables(node.get("where"), tables, cte_names)
            for asgn in (node.get("set") or []):
                self._collect_tables(asgn.get("expr"), tables, cte_names)

        elif nt == "InsertStatement":
            t = node.get("table")
            if t and t.get("node_type") == "IdentifierNode":
                schema, table = self._table_info(t)
                if table and table.upper() not in cte_names:
                    tables.add((schema, table))
            if node.get("source"):
                self._collect_tables(node["source"], tables, cte_names)

        # 運算式節點：遞迴找子查詢
        elif nt == "BinaryExpressionNode":
            self._collect_tables(node.get("left"),  tables, cte_names)
            self._collect_tables(node.get("right"), tables, cte_names)

        elif nt == "FunctionCallNode":
            for arg in (node.get("args") or []):
                self._collect_tables(arg, tables, cte_names)

        elif nt in ("CastExpressionNode",):
            self._collect_tables(node.get("expr"), tables, cte_names)

        elif nt == "BetweenExpressionNode":
            for key in ("target", "low", "high"):
                self._collect_tables(node.get(key), tables, cte_names)

        elif nt == "CaseExpressionNode":
            self._collect_tables(node.get("input"), tables, cte_names)
            for branch in (node.get("branches") or []):
                self._collect_tables(branch.get("when"), tables, cte_names)
                self._collect_tables(branch.get("then"), tables, cte_names)
            self._collect_tables(node.get("else"), tables, cte_names)

    # ── Top-level dispatch ────────────────────────────────────────

    def _walk(self, node, intents, cte_names):
        if node is None:
            return
        if isinstance(node, list):
            for item in node:
                self._walk(item, intents, cte_names)
            return

        nt = node.get("node_type", "")

        if nt == "SelectStatement":
            self._walk_select(node, intents, cte_names)
        elif nt == "UnionStatement":
            self._walk(node.get("left"),  intents, cte_names)
            self._walk(node.get("right"), intents, cte_names)
        elif nt == "UpdateStatement":
            self._walk_update(node, intents, cte_names)
        elif nt == "DeleteStatement":
            self._walk_delete(node, intents, cte_names)
        elif nt == "InsertStatement":
            self._walk_insert(node, intents, cte_names)
        elif nt == "TruncateStatement":
            schema, table = self._table_info(node.get("table"))
            if table and table not in cte_names:
                self._add(intents, schema, table, None, INTENT_DELETE)

    # ── SelectStatement ───────────────────────────────────────────

    def _walk_select(self, node, intents, cte_names, parent_alias_map=None):
        # 先處理 CTE，把 CTE 名稱加入本地 scope
        # CTE 名稱統一轉大寫比較（parser 可能大/小寫不一致）
        local_ctes = set(cte_names)
        for cte in (node.get("ctes") or []):
            local_ctes.add(cte["name"].upper())
            self._walk(cte.get("query"), intents, local_ctes)

        alias_map, derived_aliases = self._build_alias_map(node, local_ctes, intents)
        # 相關子查詢：合併外層 alias_map（內層優先）
        if parent_alias_map:
            merged = dict(parent_alias_map)
            merged.update(alias_map)
            alias_map = merged

        # SELECT * → table-level READ（排除 derived alias）
        if node.get("is_star"):
            emitted = set()
            for _key, (schema, table) in alias_map.items():
                if (schema, table) not in emitted:
                    emitted.add((schema, table))
                    self._add(intents, schema, table, None, INTENT_READ)
        else:
            for col in (node.get("columns") or []):
                self._walk_expr(col, alias_map, INTENT_READ, intents, local_ctes, derived_aliases)

        # SELECT INTO → table-level INSERT
        into = node.get("into_table")
        if into:
            schema, table = self._table_info(into)
            if table and table not in local_ctes:
                self._add(intents, schema, table, None, INTENT_INSERT)

        # WHERE → FILTER
        self._walk_expr(node.get("where"), alias_map, INTENT_FILTER, intents, local_ctes, derived_aliases)

        # JOIN ON → FILTER
        for join in (node.get("joins") or []):
            self._walk_expr(join.get("on"), alias_map, INTENT_FILTER, intents, local_ctes, derived_aliases)

        # GROUP BY → FILTER
        for col in (node.get("group_by") or []):
            self._walk_expr(col, alias_map, INTENT_FILTER, intents, local_ctes, derived_aliases)

        # HAVING → FILTER
        self._walk_expr(node.get("having"), alias_map, INTENT_FILTER, intents, local_ctes, derived_aliases)

        # ORDER BY → FILTER
        for ob in (node.get("order_by") or []):
            self._walk_expr(ob.get("column"), alias_map, INTENT_FILTER, intents, local_ctes, derived_aliases)

        # CROSS/OUTER APPLY — 傳遞外層 alias_map 供橫向參考解析
        for apply in (node.get("applies") or []):
            self._walk_subquery(apply.get("subquery"), intents, local_ctes, alias_map)

    # ── UpdateStatement ───────────────────────────────────────────

    def _walk_update(self, node, intents, cte_names):
        schema, table = self._table_info(node.get("table"))
        if not table or table in cte_names:
            return

        alias_map = {table: (schema, table)}
        alias = node.get("alias")
        if alias:
            alias_map[alias] = (schema, table)

        # SET col = expr → col 是 UPDATE，expr RHS 視為 READ
        for asgn in (node.get("set") or []):
            col_node = asgn.get("column")
            if col_node and col_node.get("node_type") == "IdentifierNode":
                c_schema, c_table, c_name = self._resolve_col(col_node, alias_map)
                self._add(intents, c_schema or schema, c_table or table, c_name, INTENT_UPDATE)
            self._walk_expr(asgn.get("expr"), alias_map, INTENT_READ, intents, cte_names)

        # WHERE → FILTER
        self._walk_expr(node.get("where"), alias_map, INTENT_FILTER, intents, cte_names)

    # ── DeleteStatement ───────────────────────────────────────────

    def _walk_delete(self, node, intents, cte_names):
        schema, table = self._table_info(node.get("table"))
        if not table or table in cte_names:
            return

        alias_map = {table: (schema, table)}
        alias = node.get("alias")
        if alias:
            alias_map[alias] = (schema, table)

        self._add(intents, schema, table, None, INTENT_DELETE)
        self._walk_expr(node.get("where"), alias_map, INTENT_FILTER, intents, cte_names)

    # ── InsertStatement ───────────────────────────────────────────

    def _walk_insert(self, node, intents, cte_names):
        schema, table = self._table_info(node.get("table"))
        if not table or table in cte_names:
            return

        cols = node.get("columns") or []
        if cols:
            for col_node in cols:
                if col_node and col_node.get("node_type") == "IdentifierNode":
                    self._add(intents, schema, table, col_node["name"], INTENT_INSERT)
        else:
            self._add(intents, schema, table, None, INTENT_INSERT)

        # INSERT-SELECT
        if node.get("source"):
            self._walk(node["source"], intents, cte_names)

    # ── Expression walker ─────────────────────────────────────────

    def _walk_expr(self, expr, alias_map, intent_type, intents, cte_names,
                   derived_aliases=None):
        if expr is None:
            return

        nt = expr.get("node_type", "") if isinstance(expr, dict) else ""

        if nt == "IdentifierNode":
            # derived table alias 的欄位引用無法歸屬來源 table，跳過
            qualifiers = expr.get("qualifiers") or []
            if derived_aliases and len(qualifiers) == 1 and qualifiers[0] in derived_aliases:
                return
            schema, table, col = self._resolve_col(expr, alias_map)
            if table:
                self._add(intents, schema or '', table, col, intent_type)

        elif nt == "BinaryExpressionNode":
            self._walk_expr(expr.get("left"),  alias_map, intent_type, intents, cte_names)
            self._walk_expr(expr.get("right"), alias_map, intent_type, intents, cte_names)

        elif nt == "FunctionCallNode":
            for arg in (expr.get("args") or []):
                self._walk_expr(arg, alias_map, intent_type, intents, cte_names)

        elif nt == "CastExpressionNode":
            self._walk_expr(expr.get("expr"), alias_map, intent_type, intents, cte_names)

        elif nt == "BetweenExpressionNode":
            self._walk_expr(expr.get("target"), alias_map, intent_type, intents, cte_names)
            self._walk_expr(expr.get("low"),    alias_map, intent_type, intents, cte_names)
            self._walk_expr(expr.get("high"),   alias_map, intent_type, intents, cte_names)

        elif nt == "CaseExpressionNode":
            self._walk_expr(expr.get("input"), alias_map, intent_type, intents, cte_names)
            for branch in (expr.get("branches") or []):
                self._walk_expr(branch.get("when"), alias_map, intent_type, intents, cte_names)
                self._walk_expr(branch.get("then"), alias_map, intent_type, intents, cte_names)
            self._walk_expr(expr.get("else"), alias_map, intent_type, intents, cte_names)

        elif nt in ("SelectStatement", "UnionStatement"):
            # 純量子查詢 / IN 子查詢 → 傳遞外層 alias_map 供相關子查詢解析
            self._walk_subquery(expr, intents, cte_names, alias_map)

    # ── Subquery helper ───────────────────────────────────────────

    def _walk_subquery(self, node, intents, cte_names, parent_alias_map):
        """
        走訪子查詢，並將外層 alias_map 傳入供相關子查詢（correlated）解析。
        """
        if node is None:
            return
        nt = node.get("node_type", "") if isinstance(node, dict) else ""
        if nt == "SelectStatement":
            self._walk_select(node, intents, cte_names, parent_alias_map)
        elif nt == "UnionStatement":
            self._walk_subquery(node.get("left"),  intents, cte_names, parent_alias_map)
            self._walk_subquery(node.get("right"), intents, cte_names, parent_alias_map)
        else:
            self._walk(node, intents, cte_names)

    # ── Alias map builder ─────────────────────────────────────────

    def _build_alias_map(self, select_node, cte_names, intents=None):
        """
        回傳 ({alias_or_table_name: (schema, table)}, derived_aliases: set)。
        derived_aliases 包含所有衍生資料表（子查詢）的 alias，
        用於在 _resolve_col 中跳過無法歸屬的欄位引用。
        若傳入 intents，會立即走訪衍生資料表內部產生 intent。
        """
        alias_map = {}
        derived_aliases = set()

        def _register(table_node, alias):
            if not table_node:
                return
            nt = table_node.get("node_type", "")
            if nt in ("SelectStatement", "UnionStatement"):
                # 衍生資料表：走訪內部產生 intent，alias 加入排除清單
                if alias:
                    derived_aliases.add(alias)
                if intents is not None:
                    self._walk(table_node, intents, cte_names)
                return
            schema, table = self._table_info(table_node)
            if not table or table.upper() in cte_names:
                return
            alias_map[table] = (schema, table)
            if alias:
                alias_map[alias] = (schema, table)

        _register(select_node.get("table"), select_node.get("alias"))

        for join in (select_node.get("joins") or []):
            _register(join.get("table"), join.get("alias"))

        return alias_map, derived_aliases

    # ── Helpers ───────────────────────────────────────────────────

    def _table_info(self, id_node):
        """從資料表引用 dict 取出 (schema, table)。"""
        if not id_node:
            return '', ''
        qualifiers = id_node.get("qualifiers") or []
        name = id_node.get("name") or ''
        schema = qualifiers[0] if qualifiers else ''
        return schema, name

    def _resolve_col(self, id_node, alias_map):
        """
        從欄位引用 dict 解析出 (schema, table, column)。
        若無法解析出 table 則回傳 (None, None, col)。

        優先順序：
          1. qualifiers >= 2  → schema.table.col
          2. qualifiers == 1  → alias_map 查詢
          3. resolved_table   → binder 已解析的非限定欄位（多表情境）
          4. 唯一 table fallback
        """
        qualifiers = id_node.get("qualifiers") or []
        col = id_node.get("name") or ''

        if len(qualifiers) >= 2:
            return qualifiers[0], qualifiers[1], col

        if len(qualifiers) == 1:
            q = qualifiers[0]
            if q in alias_map:
                schema, table = alias_map[q]
                return schema, table, col
            else:
                return '', q, col

        # 無 qualifier：優先使用 binder 寫入的 resolved_table
        resolved = id_node.get("resolved_table")
        if resolved:
            # 從 alias_map 反查 schema（大小寫不敏感）
            resolved_up = resolved.upper()
            for key, (schema, table) in alias_map.items():
                if table.upper() == resolved_up:
                    return schema, table, col
            return '', resolved, col

        # Fallback：scope 內唯一資料表
        unique = list(dict.fromkeys(alias_map.values()))
        if len(unique) == 1:
            schema, table = unique[0]
            return schema, table, col

        return None, None, col

    def _add(self, intents, schema, table, column, intent):
        if not table:
            return
        key = (schema or '', table, column or '', intent)
        if key not in self._seen:
            self._seen.add(key)
            intents.append({
                "schema": schema or '',
                "table":  table,
                "column": column,
                "intent": intent,
            })
