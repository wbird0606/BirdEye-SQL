import pytest
import json
from birdeye.mermaid_exporter import MermaidExporter

def test_mermaid_export_basic_nodes():
    """驗證 Mermaid 導出是否包含基礎節點標籤"""
    ast_dict = {
        "node_type": "SelectStatement",
        "table": {"node_type": "IdentifierNode", "name": "Users"},
        "columns": [{"node_type": "IdentifierNode", "name": "ID"}]
    }
    exporter = MermaidExporter()
    code = exporter.export(ast_dict)
    
    assert "graph TD" in code
    assert "ID: Users" in code
    assert "ID: ID" in code

def test_mermaid_export_advanced_nodes():
    """驗證 Mermaid 導出是否包含進階節點 (UNION, CTE, BETWEEN)"""
    ast_dict = {
        "node_type": "UnionStatement",
        "op": "UNION ALL",
        "left": {
            "node_type": "SelectStatement",
            "table": {"node_type": "IdentifierNode", "name": "T1"}
        },
        "right": {
            "node_type": "SelectStatement",
            "table": {"node_type": "IdentifierNode", "name": "T2"}
        }
    }
    exporter = MermaidExporter()
    code = exporter.export(ast_dict)
    
    assert "SET OP: UNION ALL" in code
    assert "ID: T1" in code
    assert "ID: T2" in code

def test_mermaid_export_cte():
    """驗證 CTE 節點的 Mermaid 導出"""
    ast_dict = {
        "node_type": "SelectStatement",
        "ctes": [{
            "node_type": "CTENode",
            "name": "MYCTE",
            "query": {"node_type": "SelectStatement"}
        }]
    }
    exporter = MermaidExporter()
    code = exporter.export(ast_dict)
    
    assert "CTE: MYCTE" in code
