from birdeye.ast import (
    SelectStatement, UpdateStatement, DeleteStatement,
    InsertStatement, SqlBulkCopyStatement,
    IdentifierNode, LiteralNode, BinaryExpressionNode,
    FunctionCallNode, JoinNode, AssignmentNode,
    OrderByNode, CaseExpressionNode, BetweenExpressionNode,
    CastExpressionNode, UnionStatement, CTENode, TruncateStatement,
    DeclareStatement, ApplyNode, OverClauseNode, ScriptNode,
    CreateTableStatement, DropTableStatement, AlterTableStatement,
    IfStatement, ExecStatement, SetStatement,
    MergeStatement, MergeClauseNode, PrintStatement,
)

class ASTVisualizer:
    """
    將 AST 轉換為樹狀文字結構，支援 DQL、DML、集合運算與 CTE。
    v1.9.0: 支援 UNION, CTE, CAST, BETWEEN 的視覺化呈現。
    """

    def __init__(self):
        self.lines = []

    def dump(self, node) -> str:
        """主入口：傳入 AST 根節點，回傳格式化後的樹狀字串"""
        self.lines = []
        self._visit(node, 0, "ROOT")
        return "\n".join(self.lines)

    def _visit(self, node, indent: int, label: str):
        prefix = "  " * indent + "└── " if indent > 0 else ""
        current_indent = "  " * indent

        # --- 0. 多語句腳本根節點 ---

        if isinstance(node, ScriptNode):
            param_info = ""
            if hasattr(node, "bound_params") and node.bound_params:
                param_info = f", params={len(node.bound_params)}"
            self.lines.append(f"{prefix}SCRIPT ({len(node.statements)} statements{param_info})")
            if hasattr(node, "bound_params") and node.bound_params:
                self.lines.append(f"{current_indent}  ├── BOUND PARAMS")
                for name, type_name in sorted(node.bound_params.items()):
                    self.lines.append(f"{current_indent}  │   └── {name}: {type_name}")
            for i, stmt in enumerate(node.statements):
                connector = "├── " if i < len(node.statements) - 1 else "└── "
                self.lines.append(f"{current_indent}  {connector}STATEMENT #{i + 1}")
                self._visit(stmt, indent + 2, f"STMT{i+1}")
            return

        # --- 1. 語句類節點 (Statements) ---

        if isinstance(node, SelectStatement):
            param_info = ""
            if hasattr(node, "bound_params") and node.bound_params:
                param_info = f" [Params: {len(node.bound_params)}]"
            self.lines.append(f"{prefix}SELECT_STATEMENT{param_info}")
            if hasattr(node, "bound_params") and node.bound_params:
                self.lines.append(f"{current_indent}  ├── BOUND PARAMS (types)")
                for name, type_name in sorted(node.bound_params.items()):
                    self.lines.append(f"{current_indent}  │   └── {name}: {type_name}")
            if hasattr(node, "bound_param_values") and node.bound_param_values:
                self.lines.append(f"{current_indent}  ├── BOUND PARAM VALUES")
                for name, value in sorted(node.bound_param_values.items()):
                    self.lines.append(f"{current_indent}  │   └── {name}: {repr(value)}")
            
            # 💡 視覺化 CTE
            if hasattr(node, 'ctes') and node.ctes:
                self.lines.append(f"{current_indent}  ├── WITH (CTEs)")
                for cte in node.ctes:
                    self._visit(cte, indent + 2, "CTE")

            if hasattr(node, 'is_distinct') and node.is_distinct:
                self.lines.append(f"{current_indent}  ├── DISTINCT")

            if node.top_count is not None:
                percent_str = " PERCENT" if getattr(node, 'top_percent', False) else ""
                self.lines.append(f"{current_indent}  ├── TOP: {node.top_count}{percent_str}")
            
            if node.is_select_star and not node.columns:
                self.lines.append(f"{current_indent}  ├── COLUMNS: *")
            else:
                self.lines.append(f"{current_indent}  ├── COLUMNS")
                for col in node.columns:
                    self._visit(col, indent + 2, "COL")
            
            if node.table:
                self.lines.append(f"{current_indent}  ├── FROM")
                self._visit(node.table, indent + 2, "TABLE")
                if node.table_alias:
                    self.lines.append(f"{current_indent}    └── ALIAS: {node.table_alias}")
            else:
                self.lines.append(f"{current_indent}  ├── FROM: <DUAL/NONE> (Scalar/Literal Query)")

            if node.joins:
                self.lines.append(f"{current_indent}  ├── JOINS")
                for j in node.joins:
                    self._visit(j, indent + 2, "JOIN")

            if hasattr(node, 'applies') and node.applies:
                self.lines.append(f"{current_indent}  ├── APPLY")
                for ap in node.applies:
                    self._visit(ap, indent + 2, "APPLY")

            if hasattr(node, 'into_table') and node.into_table:
                self.lines.append(f"{current_indent}  ├── INTO: {node.into_table.name}")

            if node.where_condition:
                self.lines.append(f"{current_indent}  ├── WHERE")
                self._visit(node.where_condition, indent + 2, "COND")
            
            if node.group_by_cols:
                self.lines.append(f"{current_indent}  ├── GROUP BY")
                for g_col in node.group_by_cols:
                    self._visit(g_col, indent + 2, "G_COL")

            if node.having_condition:
                self.lines.append(f"{current_indent}  ├── HAVING")
                self._visit(node.having_condition, indent + 2, "COND")

            if node.order_by_terms:
                self.lines.append(f"{current_indent}  ├── ORDER BY")
                for order in node.order_by_terms:
                    self._visit(order, indent + 2, "ORDER")

            if hasattr(node, 'offset_count') and node.offset_count is not None:
                self.lines.append(f"{current_indent}  ├── OFFSET: {node.offset_count}")
            if hasattr(node, 'fetch_count') and node.fetch_count is not None:
                self.lines.append(f"{current_indent}  └── FETCH NEXT: {node.fetch_count}")

        elif isinstance(node, UnionStatement):
            self.lines.append(f"{prefix}SET_OPERATION: {node.operator}")
            self.lines.append(f"{current_indent}  ├── LEFT")
            self._visit(node.left, indent + 2, "QUERY")
            self.lines.append(f"{current_indent}  └── RIGHT")
            self._visit(node.right, indent + 2, "QUERY")

        elif isinstance(node, CTENode):
            self.lines.append(f"{prefix}CTE: {node.name}")
            self.lines.append(f"{current_indent}  └── QUERY")
            self._visit(node.query, indent + 2, "SUBQUERY")

        elif isinstance(node, UpdateStatement):
            self.lines.append(f"{prefix}UPDATE_STATEMENT")
            self.lines.append(f"{current_indent}  ├── TABLE: {node.table.name}")
            if node.table_alias:
                self.lines.append(f"{current_indent}  ├── ALIAS: {node.table_alias}")
            self.lines.append(f"{current_indent}  ├── SET")
            for clause in node.set_clauses:
                self._visit(clause, indent + 2, "CLAUSE")
            self.lines.append(f"{current_indent}  └── WHERE (MANDATORY)")
            self._visit(node.where_condition, indent + 2, "COND")

        elif isinstance(node, DeleteStatement):
            self.lines.append(f"{prefix}DELETE_STATEMENT")
            self.lines.append(f"{current_indent}  ├── FROM: {node.table.name}")
            if node.table_alias:
                self.lines.append(f"{current_indent}  ├── ALIAS: {node.table_alias}")
            self.lines.append(f"{current_indent}  └── WHERE (MANDATORY)")
            self._visit(node.where_condition, indent + 2, "COND")

        elif isinstance(node, InsertStatement):
            self.lines.append(f"{prefix}INSERT_STATEMENT")
            self.lines.append(f"{current_indent}  ├── INTO: {node.table.name}")
            if node.columns:
                self.lines.append(f"{current_indent}  ├── COLUMNS")
                for col in node.columns:
                    self.lines.append(f"{current_indent}  │   └── {col.name}")
            if node.source is not None:
                self.lines.append(f"{current_indent}  └── SOURCE")
                self._visit(node.source, indent + 2, "SELECT")
            elif node.value_rows:
                for i, row in enumerate(node.value_rows):
                    self.lines.append(f"{current_indent}  ├── VALUES ROW #{i+1}")
                    for val in row:
                        self._visit(val, indent + 3, "VAL")
            else:
                self.lines.append(f"{current_indent}  └── VALUES")
                for val in node.values:
                    self._visit(val, indent + 2, "VAL")

        elif isinstance(node, TruncateStatement):
            self.lines.append(f"{prefix}TRUNCATE_STATEMENT")
            self.lines.append(f"{current_indent}  └── TABLE: {node.table.name}")

        elif isinstance(node, DropTableStatement):
            if_exists = " IF EXISTS" if node.if_exists else ""
            self.lines.append(f"{prefix}DROP_TABLE_STATEMENT{if_exists}")
            if node.table:
                self.lines.append(f"{current_indent}  └── TABLE: {node.table.name}")

        elif isinstance(node, CreateTableStatement):
            if_not_exists = " IF NOT EXISTS" if node.if_not_exists else ""
            self.lines.append(f"{prefix}CREATE_TABLE_STATEMENT{if_not_exists}")
            if node.table:
                self.lines.append(f"{current_indent}  ├── TABLE: {node.table.name}")
            if node.columns:
                self.lines.append(f"{current_indent}  └── COLUMNS ({len(node.columns)})")

        elif isinstance(node, AlterTableStatement):
            self.lines.append(f"{prefix}ALTER_TABLE_STATEMENT")
            if node.table:
                self.lines.append(f"{current_indent}  ├── TABLE: {node.table.name}")
            if node.action:
                self.lines.append(f"{current_indent}  ├── ACTION: {node.action}")
            if node.column:
                self._visit(node.column, indent + 2, "COLUMN")

        elif isinstance(node, SqlBulkCopyStatement):
            self.lines.append(f"{prefix}BULK_COPY_STATEMENT")
            self.lines.append(f"{current_indent}  └── TARGET TABLE: {node.table.name}")

        elif isinstance(node, SetStatement):
            if node.is_option:
                self.lines.append(f"{prefix}SET_OPTION")
                if node.target:
                    self._visit(node.target, indent + 1, "OPTION")
            else:
                self.lines.append(f"{prefix}SET_STATEMENT")
                if node.target:
                    self._visit(node.target, indent + 1, "TARGET")
                if node.value is not None:
                    self.lines.append(f"{current_indent}  └── VALUE")
                    self._visit(node.value, indent + 2, "EXPR")

        elif isinstance(node, IfStatement):
            self.lines.append(f"{prefix}IF_STATEMENT")
            if node.condition is not None:
                self.lines.append(f"{current_indent}  ├── CONDITION")
                self._visit(node.condition, indent + 2, "COND")
            if node.then_block:
                self.lines.append(f"{current_indent}  ├── THEN ({len(node.then_block)} stmt(s))")
                for i, stmt in enumerate(node.then_block):
                    self._visit(stmt, indent + 2, f"THEN#{i+1}")
            if node.else_block:
                self.lines.append(f"{current_indent}  └── ELSE ({len(node.else_block)} stmt(s))")
                for i, stmt in enumerate(node.else_block):
                    self._visit(stmt, indent + 2, f"ELSE#{i+1}")

        elif isinstance(node, ExecStatement):
            if node.proc_name and hasattr(node.proc_name, 'name'):
                qualifiers = getattr(node.proc_name, 'qualifiers', [])
                proc = ".".join(qualifiers + [node.proc_name.name])
            else:
                proc = str(node.proc_name) if node.proc_name else "?"
            self.lines.append(f"{prefix}EXEC_STATEMENT: {proc}")
            if node.return_var:
                self.lines.append(f"{current_indent}  ├── RETURN_VAR: {node.return_var}")
            for i, arg in enumerate(node.args or []):
                self._visit(arg, indent + 1, f"ARG#{i+1}")
            for i, kv in enumerate(node.named_args or []):
                self._visit(kv, indent + 1, f"PARAM#{i+1}")

        elif isinstance(node, MergeStatement):
            self.lines.append(f"{prefix}MERGE_STATEMENT")
            if node.target:
                alias = f" AS {node.target_alias}" if node.target_alias else ""
                self.lines.append(f"{current_indent}  ├── TARGET: {node.target.name if hasattr(node.target, 'name') else '?'}{alias}")
            if node.source is not None:
                self.lines.append(f"{current_indent}  ├── USING")
                self._visit(node.source, indent + 2, "SOURCE")
                if node.source_alias:
                    self.lines.append(f"{current_indent}    └── ALIAS: {node.source_alias}")
            if node.on_condition is not None:
                self.lines.append(f"{current_indent}  ├── ON")
                self._visit(node.on_condition, indent + 2, "COND")
            for i, clause in enumerate(node.clauses or []):
                self._visit(clause, indent + 1, f"CLAUSE#{i+1}")

        elif isinstance(node, MergeClauseNode):
            self.lines.append(f"{prefix}MERGE_CLAUSE: {node.match_type or '?'} / {node.action or '?'}")
            if node.condition is not None:
                self._visit(node.condition, indent + 1, "AND COND")
            for asgn in (node.set_clauses or []):
                self._visit(asgn, indent + 1, "SET")

        elif isinstance(node, PrintStatement):
            self.lines.append(f"{prefix}PRINT_STATEMENT")
            if node.expr is not None:
                self._visit(node.expr, indent + 1, "EXPR")

        # --- 2. 表達式與函數節點 ---

        elif isinstance(node, FunctionCallNode):
            alias = f" AS {node.alias}" if hasattr(node, 'alias') and node.alias else ""
            type_info = f" [Type: {node.inferred_type}]" if hasattr(node, 'inferred_type') and node.inferred_type != "UNKNOWN" else ""
            arg_info = f" ({len(node.args)} args)" if node.args else " ()"
            self.lines.append(f"{prefix}FUNCTION: {node.name}{arg_info}{type_info}{alias}")
            
            # 顯示函數參數
            for i, arg in enumerate(node.args):
                self._visit(arg, indent + 1, f"ARG#{i+1}")
            
            # 顯示 OVER 子句（窗函數）
            if hasattr(node, 'over_clause') and node.over_clause:
                self._visit(node.over_clause, indent + 1, "OVER")

        elif isinstance(node, CaseExpressionNode):
            type_info = f" [Type: {node.inferred_type}]" if hasattr(node, 'inferred_type') and node.inferred_type != "UNKNOWN" else ""
            self.lines.append(f"{prefix}CASE_EXPRESSION{type_info}")
            if node.input_expr:
                self._visit(node.input_expr, indent + 2, "INPUT")
            for i, (when_expr, then_expr) in enumerate(node.branches):
                self.lines.append(f"{current_indent}  ├── BRANCH #{i+1}")
                self._visit(when_expr, indent + 3, "WHEN")
                self._visit(then_expr, indent + 3, "THEN")
            if node.else_expr:
                self.lines.append(f"{current_indent}  ├── ELSE")
                self._visit(node.else_expr, indent + 2, "RESULT")
            if hasattr(node, 'alias') and node.alias:
                self.lines.append(f"{current_indent}  └── ALIAS: {node.alias}")

        elif isinstance(node, BinaryExpressionNode):
            type_info = f" [Type: {node.inferred_type}]" if hasattr(node, 'inferred_type') and node.inferred_type != "UNKNOWN" else ""
            self.lines.append(f"{prefix}EXPRESSION: {node.operator}{type_info}")
            self._visit(node.left, indent + 1, "LEFT")
            # 💡 TDD Fix: 處理右側可能是列表的情況 (如 IN 或 ANY/ALL)
            if isinstance(node.right, list):
                self.lines.append(f"  " * (indent + 1) + "└── LIST")
                for i, item in enumerate(node.right):
                    self.lines.append(f"  " * (indent + 2) + f"├── ITEM#{i+1}")
                    self._visit(item, indent + 3, "")
            else:
                self._visit(node.right, indent + 1, "RIGHT")

        elif isinstance(node, BetweenExpressionNode):
            type_info = f" [Type: {node.inferred_type}]" if hasattr(node, 'inferred_type') and node.inferred_type != "UNKNOWN" else ""
            op = "NOT BETWEEN" if node.is_not else "BETWEEN"
            self.lines.append(f"{prefix}EXPRESSION: {op}{type_info}")
            self.lines.append(f"{current_indent}  ├── TARGET")
            self._visit(node.expr, indent + 2, "TARGET")
            self.lines.append(f"{current_indent}  ├── LOW")
            self._visit(node.low, indent + 2, "LOW")
            self.lines.append(f"{current_indent}  └── HIGH")
            self._visit(node.high, indent + 2, "HIGH")

        elif isinstance(node, CastExpressionNode):
            type_info = f" [Type: {node.inferred_type}]" if hasattr(node, 'inferred_type') and node.inferred_type != "UNKNOWN" else ""
            func = "CONVERT" if node.is_convert else "CAST"
            self.lines.append(f"{prefix}{func} TO {node.target_type}{type_info}")
            self.lines.append(f"{current_indent}  └── EXPR")
            self._visit(node.expr, indent + 2, "EXPR")

        elif isinstance(node, IdentifierNode):
            full_name = ".".join(node.qualifiers + [node.name]) if node.qualifiers else node.name
            alias = f" AS {node.alias}" if hasattr(node, 'alias') and node.alias else ""
            type_info = f" [Type: {node.inferred_type}]" if hasattr(node, 'inferred_type') and node.inferred_type != "UNKNOWN" else ""
            resolved = f" → {node.resolved_table}" if getattr(node, "resolved_table", None) else ""
            self.lines.append(f"{prefix}IDENTIFIER: {full_name}{resolved}{type_info}{alias}")

        elif isinstance(node, LiteralNode):
            type_info = f" [Type: {node.inferred_type}]" if hasattr(node, 'inferred_type') and node.inferred_type != "UNKNOWN" else ""
            self.lines.append(f"{prefix}LITERAL: {node.value}{type_info}")

        # --- 3. 結構輔助節點 ---

        elif isinstance(node, JoinNode):
            self.lines.append(f"{prefix}{node.type}_JOIN")
            self._visit(node.table, indent + 1, "TABLE")
            if node.alias:
                self.lines.append(f"{current_indent}    └── ALIAS: {node.alias}")
            if node.on_condition:
                self.lines.append(f"{current_indent}    └── ON")
                self._visit(node.on_condition, indent + 3, "COND")

        elif isinstance(node, OrderByNode):
            self.lines.append(f"{prefix}SORT_BY: {node.direction}")
            self._visit(node.column, indent + 1, "COL")

        elif isinstance(node, AssignmentNode):
            self.lines.append(f"{prefix}SET_OP: =")
            self._visit(node.column, indent + 1, "TARGET")
            self._visit(node.right, indent + 1, "VALUE")

        elif isinstance(node, DeclareStatement):
            self.lines.append(f"{prefix}DECLARE_STATEMENT")
            self.lines.append(f"{current_indent}  ├── VAR: {node.var_name}")
            self.lines.append(f"{current_indent}  ├── TYPE: {node.var_type}")
            if node.default_value is not None:
                self.lines.append(f"{current_indent}  └── DEFAULT")
                self._visit(node.default_value, indent + 2, "EXPR")

        elif isinstance(node, ApplyNode):
            self.lines.append(f"{prefix}{node.type}_APPLY")
            if node.alias:
                self.lines.append(f"{current_indent}  ├── ALIAS: {node.alias}")
            self.lines.append(f"{current_indent}  └── SUBQUERY")
            self._visit(node.subquery, indent + 2, "SUBQUERY")

        elif isinstance(node, OverClauseNode):
            self.lines.append(f"{prefix}OVER_CLAUSE")
            
            # 顯示 PARTITION BY
            if node.partition_by:
                self.lines.append(f"{current_indent}  ├── PARTITION_BY")
                for i, expr in enumerate(node.partition_by):
                    self._visit(expr, indent + 2, f"EXPR#{i+1}")
            
            # 顯示 ORDER BY
            if node.order_by:
                self.lines.append(f"{current_indent}  ├── ORDER_BY")
                for order_by_node in node.order_by:
                    self._visit(order_by_node, indent + 2, "COL")
            
            # 顯示 Frame 規範
            if node.frame_type:
                self.lines.append(f"{current_indent}  └── FRAME: {node.frame_type}")
                if node.frame_start:
                    self.lines.append(f"{current_indent}      ├── START: {node.frame_start}")
                if node.frame_end:
                    self.lines.append(f"{current_indent}      └── END: {node.frame_end}")
