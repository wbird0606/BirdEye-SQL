import json
from birdeye.ast import (
    SelectStatement, UpdateStatement, DeleteStatement,
    InsertStatement, SqlBulkCopyStatement,
    IdentifierNode, LiteralNode, BinaryExpressionNode,
    FunctionCallNode, JoinNode, AssignmentNode,
    OrderByNode, CaseExpressionNode, BetweenExpressionNode,
    CastExpressionNode, UnionStatement, CTENode, TruncateStatement,
    DeclareStatement, ApplyNode
)

class ASTSerializer:
    """
    將 AST 轉換為標準 JSON 格式。
    v1.8.0: 支援全節點遞迴序列化，包括 UNION, CTE, CAST, BETWEEN。
    """

    def to_json(self, node, indent=2) -> str:
        """主入口：將 AST 根節點轉換為 JSON 字串"""
        return json.dumps(self._serialize(node), indent=indent, ensure_ascii=False)

    def _serialize(self, node):
        """遞迴將節點物件轉換為 dict"""
        if node is None:
            return None
        
        # 處理列表
        if isinstance(node, list):
            return [self._serialize(item) for item in node]
        
        # 處理元組
        if isinstance(node, tuple):
            return [self._serialize(item) for item in node]

        res = {"node_type": node.__class__.__name__}

        if isinstance(node, SelectStatement):
            res.update({
                "ctes": self._serialize(node.ctes) if hasattr(node, 'ctes') else [],
                "top": node.top_count,
                "is_distinct": node.is_distinct if hasattr(node, 'is_distinct') else False,
                "is_star": node.is_select_star,
                "columns": self._serialize(node.columns),
                "table": self._serialize(node.table),
                "alias": node.table_alias,
                "joins": self._serialize(node.joins),
                "applies": self._serialize(node.applies) if hasattr(node, 'applies') else [],
                "into_table": self._serialize(node.into_table) if hasattr(node, 'into_table') else None,
                "where": self._serialize(node.where_condition),
                "group_by": self._serialize(node.group_by_cols),
                "having": self._serialize(node.having_condition),
                "order_by": self._serialize(node.order_by_terms)
            })

        elif isinstance(node, UnionStatement):
            res.update({
                "op": node.operator,
                "left": self._serialize(node.left),
                "right": self._serialize(node.right),
                "columns": self._serialize(node.columns)
            })

        elif isinstance(node, CTENode):
            res.update({
                "name": node.name,
                "query": self._serialize(node.query)
            })

        elif isinstance(node, BetweenExpressionNode):
            res.update({
                "target": self._serialize(node.expr),
                "low": self._serialize(node.low),
                "high": self._serialize(node.high),
                "is_not": node.is_not
            })

        elif isinstance(node, CastExpressionNode):
            res.update({
                "expr": self._serialize(node.expr),
                "target": node.target_type,
                "is_convert": node.is_convert
            })

        elif isinstance(node, UpdateStatement):
            res.update({
                "table": self._serialize(node.table),
                "alias": node.table_alias,
                "set": self._serialize(node.set_clauses),
                "where": self._serialize(node.where_condition)
            })

        elif isinstance(node, DeleteStatement):
            res.update({
                "table": self._serialize(node.table),
                "alias": node.table_alias,
                "where": self._serialize(node.where_condition)
            })

        elif isinstance(node, InsertStatement):
            res.update({
                "table": self._serialize(node.table),
                "columns": self._serialize(node.columns),
                "values": None if node.source else (self._serialize(node.values) if not node.value_rows or len(node.value_rows) <= 1 else None),
                "value_rows": self._serialize(node.value_rows) if node.value_rows else None,
                "source": self._serialize(node.source) if node.source else None,
            })

        elif isinstance(node, TruncateStatement):
            res.update({
                "table": self._serialize(node.table)
            })

        elif isinstance(node, IdentifierNode):
            res.update({
                "name": node.name,
                "qualifiers": node.qualifiers,
                "alias": node.alias
            })

        elif isinstance(node, LiteralNode):
            res.update({
                "value": node.value,
                "type": node.type.name if hasattr(node.type, 'name') else str(node.type)
            })

        elif isinstance(node, BinaryExpressionNode):
            res.update({
                "op": node.operator,
                "left": self._serialize(node.left),
                "right": self._serialize(node.right)
            })

        elif isinstance(node, FunctionCallNode):
            res.update({
                "name": node.name,
                "args": self._serialize(node.args),
                "alias": node.alias
            })

        elif isinstance(node, CaseExpressionNode):
            res.update({
                "input": self._serialize(node.input_expr),
                "branches": [
                    {"when": self._serialize(b[0]), "then": self._serialize(b[1])} 
                    for b in node.branches
                ],
                "else": self._serialize(node.else_expr),
                "alias": node.alias
            })

        elif isinstance(node, JoinNode):
            res.update({
                "join_type": node.type,
                "table": self._serialize(node.table),
                "alias": node.alias,
                "on": self._serialize(node.on_condition)
            })

        elif isinstance(node, OrderByNode):
            res.update({
                "column": self._serialize(node.column),
                "direction": node.direction
            })

        elif isinstance(node, AssignmentNode):
            res.update({
                "column": self._serialize(node.column),
                "expr": self._serialize(node.right)
            })

        elif isinstance(node, DeclareStatement):
            res.update({
                "var_name": node.var_name,
                "var_type": node.var_type,
                "default_value": self._serialize(node.default_value)
            })

        elif isinstance(node, ApplyNode):
            res.update({
                "apply_type": node.type,
                "subquery": self._serialize(node.subquery),
                "alias": node.alias
            })

        return res