class MermaidExporter:
    """
    將 AST JSON 結構轉換為 Mermaid.js 流程圖語法。
    v1.2: 強化語法分隔，修復連線標籤與換行造成的解析錯誤。
    """
    def __init__(self):
        self.node_count = 0
        self.lines = []

    def export(self, ast_dict) -> str:
        # 使用 graph TD 並確保每一行都有分號作為明確分隔
        self.lines = ["graph TD;"]
        self.node_count = 0
        self._traverse(ast_dict)
        return "\n".join(self.lines)

    def _get_id(self):
        self.node_count += 1
        return f"n{self.node_count}"

    def _clean_text(self, text):
        """🛡️ 強力清理：移除所有可能干擾 Mermaid 解析的特殊符號"""
        if text is None: return ""
        s = str(text)
        # 移除中括號、小括號、引號、換行與分號
        forbidden = ['"', '[', ']', '(', ')', '{', '}', '>', '<', '|', ';', '\n']
        for char in forbidden:
            s = s.replace(char, " ")
        return s.strip()

    def _traverse(self, node):
        if node is None or not isinstance(node, dict):
            return None

        current_id = self._get_id()
        node_type = node.get("node_type", "Node")
        
        # 組合顯示內容 (例如 SelectStatement, IdentifierNode: UserID)
        name = node.get("name") or node.get("value") or node.get("op") or ""
        label = f"{node_type} {name}".strip()
        clean_label = self._clean_text(label)
        
        # 定義節點：ID["Label"];
        self.lines.append(f"  {current_id}[\"{clean_label}\"];")

        # 遞迴處理子屬性
        for key, value in node.items():
            # 跳過元數據欄位
            if key in ["node_type", "name", "value", "op", "type", "qualifiers", "alias", "join_type", "direction"]:
                continue
            
            # 處理單一子節點 (如 table, where)
            if isinstance(value, dict):
                child_id = self._traverse(value)
                if child_id:
                    clean_key = self._clean_text(key)
                    self.lines.append(f"  {current_id} -- \"{clean_key}\" --> {child_id};")
            
            # 處理列表節點 (如 columns, joins)
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    child_id = self._traverse(item)
                    if child_id:
                        # 標註索引，如 columns_0
                        clean_key = self._clean_text(f"{key}_{i}")
                        self.lines.append(f"  {current_id} -- \"{clean_key}\" --> {child_id};")
        
        return current_id