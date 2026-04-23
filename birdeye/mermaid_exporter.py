class MermaidExporter:
    """
    將 AST JSON 結構轉換為 Mermaid.js 流程圖語語法。
    v1.3: 支援 UNION, CTE, CAST, BETWEEN, TRUNCATE 與值列表導出。
    """
    def __init__(self):
        self.node_count = 0
        self.lines = []

    def export(self, ast_dict):
        """主入口：傳入序列化後的 AST 字典，回傳 Mermaid 代碼"""
        self.lines = ["graph TD"]
        self.node_count = 0
        self._build_tree(ast_dict)
        return "\n".join(self.lines)

    def _clean_text(self, text):
        """清理文字以符合 Mermaid 語法 (移除引號與特殊符號)"""
        if not text: return ""
        return str(text).replace('"', '').replace("'", "").replace("[", "").replace("]", "").replace("(", "").replace(")", "")

    def _get_node_id(self):
        self.node_count += 1
        return f"node_{self.node_count}"

    def _build_tree(self, node):
        if node is None: return None
        if not isinstance(node, dict): return None

        node_type = node.get("node_type", "Unknown")
        node_id = self._get_node_id()

        # 根據節點類型決定標籤內容
        label = node_type
        if node_type == "ScriptNode":
            count = len(node.get("statements") or [])
            params = node.get("bound_params") or {}
            param_info = f", params={len(params)}" if params else ""
            label = f"SCRIPT ({count} stmts{param_info})"
        elif node_type == "IdentifierNode":
            qualifiers = node.get('qualifiers') or []
            full_name = ".".join(qualifiers + [node.get('name', '')])
            inferred = node.get("inferred_type")
            type_info = f" [{inferred}]" if inferred and inferred != "UNKNOWN" else ""
            label = f"ID: {full_name}{type_info}"
        elif node_type == "LiteralNode":
            type_name = node.get("inferred_type") or node.get("type")
            type_info = f" [{type_name}]" if type_name and type_name != "UNKNOWN" else ""
            label = f"LITERAL: {node.get('value')}{type_info}"
        elif node_type == "BinaryExpressionNode":
            inferred = node.get("inferred_type")
            type_info = f" [{inferred}]" if inferred and inferred != "UNKNOWN" else ""
            label = f"OP: {node.get('op')}{type_info}"
        elif node_type == "FunctionCallNode":
            inferred = node.get("inferred_type")
            type_info = f" [{inferred}]" if inferred and inferred != "UNKNOWN" else ""
            label = f"FUNC: {node.get('name')}{type_info}"
        elif node_type == "BetweenExpressionNode":
            label = "BETWEEN"
        elif node_type == "CastExpressionNode":
            label = f"CAST TO {node.get('target')}"
        elif node_type == "UnionStatement":
            label = f"SET OP: {node.get('op')}"
        elif node_type == "CTENode":
            label = f"CTE: {node.get('name')}"
        elif node_type == "TruncateStatement":
            label = "TRUNCATE"
        elif node_type == "DeclareStatement":
            label = f"DECLARE {node.get('var_name', '')} {node.get('var_type', '')}"
        elif node_type == "SetStatement":
            t = node.get("target")
            t_name = t.get("name", "?") if isinstance(t, dict) else (str(t) if t else "?")
            label = f"SET {t_name} ="
        elif node_type == "IfStatement":
            label = "IF"
        elif node_type == "MergeStatement":
            t = node.get("target")
            t_name = ".".join((t.get("qualifiers") or []) + [t.get("name", "")]) if isinstance(t, dict) else "?"
            a = node.get("target_alias")
            label = f"MERGE INTO {t_name}" + (f" AS {a}" if a else "")
        elif node_type == "MergeClauseNode":
            label = f"WHEN {node.get('match_type', '')} THEN {node.get('action', '')}"
        elif node_type == "CreateTableStatement":
            t = node.get("table")
            t_name = ".".join((t.get("qualifiers") or []) + [t.get("name", "")]) if isinstance(t, dict) else "?"
            label = f"CREATE TABLE {t_name}"
        elif node_type == "DropTableStatement":
            t = node.get("table")
            t_name = ".".join((t.get("qualifiers") or []) + [t.get("name", "")]) if isinstance(t, dict) else "?"
            label = f"DROP TABLE {t_name}"
        elif node_type == "AlterTableStatement":
            label = "ALTER TABLE"
        elif node_type == "ExecStatement":
            p = node.get("proc_name")
            p_name = ".".join((p.get("qualifiers") or []) + [p.get("name", "")]) if isinstance(p, dict) else "?"
            label = f"EXEC {p_name}"
        elif node_type == "PrintStatement":
            label = "PRINT"

        self.lines.append(f"  {node_id}[\"{self._clean_text(label)}\"];")

        # 遞迴處理子節點
        for key, value in node.items():
            if key in ["node_type", "alias", "direction", "op", "name", "target", "is_convert", "is_not", "is_star", "top"]:
                continue

            if isinstance(value, dict):
                child_id = self._build_tree(value)
                if child_id:
                    self.lines.append(f"  {node_id} -- \"{self._clean_text(key)}\" --> {child_id};")

            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        child_id = self._build_tree(item)
                        if child_id:
                            # ScriptNode 的 statements 用 STMT #N 標示，其餘維持原格式
                            if key == "statements":
                                label_key = f"STMT #{i + 1}"
                            else:
                                label_key = f"{key}_{i}"
                            self.lines.append(f"  {node_id} -- \"{self._clean_text(label_key)}\" --> {child_id};")
        
        return node_id
