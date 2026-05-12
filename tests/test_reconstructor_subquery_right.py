from birdeye.reconstructor import ASTReconstructor


def test_binary_with_subquery_right():
    r = ASTReconstructor()
    node = {
        "node_type": "BinaryExpressionNode",
        "op": "=",
        "left": {"node_type": "IdentifierNode", "name": "col"},
        "right": {"node_type": "SelectStatement", "is_star": True},
    }

    sql = r.to_sql(node)
    assert sql == "col = (SELECT *)"
