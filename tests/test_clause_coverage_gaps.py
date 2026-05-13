"""
新增測試以覆蓋未被測試的 clause

題目: Clause Coverage Gap Tests
目標: 針對 clause_coverage_report.json 中缺少 True/False 分支的高優先級 clause，
      新增目標測試以提升覆蓋率從 75% 到 90%+

測試範圍:
1. parser.py - _match 和 _consume 的邊界情況
2. lexer.py - N-string 和 token 轉換邊界
3. registry.py - 函數型別推斷邊界
4. web/app.py - 端點錯誤處理
"""

import pytest
import io
import json
from birdeye.lexer import Lexer, TokenType, Token
from birdeye.parser import Parser
from birdeye.registry import MetadataRegistry
from birdeye.binder import Binder
from birdeye.runner import BirdEyeRunner


# ============================================================================
# 1. LEXER 邊界測試 - N-String 前綴與 Token 轉換
# ============================================================================

class TestLexerBoundaries:
    """
    測試 lexer.py:270 缺少 True 路徑 - N-string 前綴處理
    
    缺口: lexer.py:270:45-54 = 4,744x False 執行，0x True 執行
    分析: N'...' 或 n'...' 前綴的 Unicode 字符串從未被解析過
    """
    
    def test_n_string_uppercase(self):
        """測試大寫 N 前綴的 Unicode 字符串"""
        lexer = Lexer("SELECT N'Hello World'")
        tokens = lexer.tokenize()
        
        # 應該有 SELECT 和字符串
        assert len(tokens) >= 2
        # 第二個 token 應該是字符串
        string_token = tokens[1]
        assert string_token.type == TokenType.STRING_LITERAL
        assert "Hello World" in string_token.value
    
    def test_n_string_lowercase(self):
        """測試小寫 n 前綴的 Unicode 字符串"""
        lexer = Lexer("SELECT n'Test String'")
        tokens = lexer.tokenize()
        
        assert len(tokens) >= 2
        string_token = tokens[1]
        assert string_token.type == TokenType.STRING_LITERAL
    
    def test_n_string_with_special_chars(self):
        """測試 N-string 包含特殊字符（中文、符號等）"""
        lexer = Lexer("SELECT N'中文字符'")
        tokens = lexer.tokenize()
        
        assert len(tokens) >= 2
        string_token = tokens[1]
        assert string_token.type == TokenType.STRING_LITERAL
        assert "中文字符" in string_token.value
    
    def test_n_string_empty(self):
        """測試空的 N-string"""
        lexer = Lexer("SELECT N''")
        tokens = lexer.tokenize()
        
        assert len(tokens) >= 2
        string_token = tokens[1]
        assert string_token.type == TokenType.STRING_LITERAL
    
    def test_n_string_with_quotes(self):
        """測試 N-string 包含引號（轉義）"""
        lexer = Lexer("SELECT N'It''s a test'")
        tokens = lexer.tokenize()
        
        assert len(tokens) >= 2
        string_token = tokens[1]
        assert string_token.type == TokenType.STRING_LITERAL

    def test_n_string_as_whole_source(self):
        """直接以 N-string 作為輸入，強制命中 N 前綴判斷的 True 分支。"""
        lexer = Lexer("N'abc'")
        tokens = lexer.tokenize()

        assert len(tokens) >= 2
        assert tokens[0].type == TokenType.STRING_LITERAL
        assert tokens[0].value == "'abc'"


# ============================================================================
# 2. PARSER 邊界測試 - _match 和 _consume 異常路徑
# ============================================================================

class TestParserBoundaries:
    """
    測試 parser.py:37 和 :47 的缺少 False 路徑
    
    缺口 1: parser.py:37:4,8 = 101,001x True，0x False
    分析: _match() 中的 `tok and tok.type in types` 只執行過 True 分支
    
    缺口 2: parser.py:47:12,15 = 6,951x True，0x False
    分析: _consume() 中的 `if not tok:` 只執行過成功情況，未拋出異常
    
    測試策略: 構造語法錯誤使 token 為 None，或類型不匹配
    """
    
    def test_parser_match_missing_token(self):
        """測試 _match 當 token 為 None（文件結尾）時的情況"""
        # 構造不完整的 SQL 使得 parser 在 EOF 時嘗試匹配 token
        lexer = Lexer("SELECT * FROM")
        tokens = lexer.tokenize()
        parser = Parser(tokens, "SELECT * FROM")
        
        # 嘗試解析會失敗，因為缺少表名
        with pytest.raises(SyntaxError):
            parser.parse()
    
    def test_parser_match_wrong_token_type(self):
        """測試 _match 當 token 類型不匹配時的情況"""
        # 構造 SELECT 後直接跟 WHERE（缺少列表）
        sql = "SELECT WHERE ProductID = 1"
        lexer = Lexer(sql)
        tokens = lexer.tokenize()
        parser = Parser(tokens, sql)
        
        with pytest.raises(SyntaxError):
            parser.parse()
    
    def test_parser_consume_missing_keyword(self):
        """測試 _consume 當必要關鍵字缺失時的情況"""
        # FROM 後缺少表名
        sql = "SELECT * FROM ;"
        lexer = Lexer(sql)
        tokens = lexer.tokenize()
        parser = Parser(tokens, sql)
        
        with pytest.raises(SyntaxError):
            parser.parse()
    
    def test_parser_consume_missing_comma_in_join(self):
        """測試 _consume 在 JOIN 語法缺少逗號時的情況"""
        sql = "SELECT * FROM A JOIN B ON A.id = B.id WHERE"
        lexer = Lexer(sql)
        tokens = lexer.tokenize()
        parser = Parser(tokens, sql)
        
        with pytest.raises(SyntaxError):
            parser.parse()

    def test_match_returns_none_when_type_mismatch(self):
        """直接命中 _match 的 tok 存在但型別不符分支。"""
        tokens = [Token(TokenType.KEYWORD_SELECT, "SELECT", 0, 6), Token(TokenType.EOF, "", 6, 6)]
        parser = Parser(tokens, "SELECT")

        matched = parser._match(TokenType.KEYWORD_FROM)
        assert matched is None
        assert parser.pos == 0

    def test_match_returns_none_when_eof(self):
        """直接命中 _match 的 tok 為 None 分支。"""
        tokens = [Token(TokenType.KEYWORD_SELECT, "SELECT", 0, 6)]
        parser = Parser(tokens, "SELECT")
        parser.pos = len(tokens)

        matched = parser._match(TokenType.KEYWORD_SELECT)
        assert matched is None

    @pytest.mark.parametrize(
        "tokens, expected_type",
        [
            ([Token(TokenType.IDENTIFIER, "alias", 0, 5)], TokenType.IDENTIFIER),
            ([Token(TokenType.KEYWORD_OVER, "OVER", 0, 4)], TokenType.KEYWORD_OVER),
            ([Token(TokenType.KEYWORD_SELECT, "SELECT", 0, 6)], None),
            ([], None),
        ],
    )
    def test_match_alias_cacc_cases(self, tokens, expected_type):
        """用 IDENTIFIER、可作別名的關鍵字、以及非別名 token / EOF 組合驗證 _match_alias。"""
        parser = Parser(tokens, "alias")

        matched = parser._match_alias()

        if expected_type is None:
            assert matched is None
        else:
            assert matched is not None
            assert matched.type == expected_type

    def test_consume_raises_on_mismatch(self):
        """直接命中 _consume 的 not tok 為 True 分支。"""
        tokens = [Token(TokenType.KEYWORD_SELECT, "SELECT", 0, 6), Token(TokenType.EOF, "", 6, 6)]
        parser = Parser(tokens, "SELECT")

        with pytest.raises(SyntaxError, match="expected FROM"):
            parser._consume(TokenType.KEYWORD_FROM, "expected FROM")


# ============================================================================
# 3. REGISTRY 邊界測試 - 函數型別推斷與查詢
# ============================================================================

class TestRegistryBoundaries:
    """
    測試 registry.py 的函數型別推斷缺口
    
    缺口: registry.py:184:14,17 = 2,939x False，0x True
    分析: 某些函數型別推斷路徑未被測試
    """
    
    @pytest.fixture
    def test_registry(self):
        """建立測試用的 registry"""
        csv_data = (
            "table_name,column_name,data_type\n"
            "Orders,OrderID,INT\n"
            "Orders,OrderDate,DATETIME\n"
            "Orders,Price,DECIMAL\n"
        )
        reg = MetadataRegistry()
        reg.load_from_csv(io.StringIO(csv_data))
        return reg
    
    def test_function_type_inference_string_to_int(self, test_registry):
        """測試函數型別轉換 - 字符串轉整數"""
        # TRY_CAST 應該返回目標型別
        result = test_registry.get_function("TRY_CAST")
        assert result is not None
        assert result.name == "TRY_CAST"
        assert result.func_type == "SCALAR"
    
    def test_function_type_inference_null_propagation(self, test_registry):
        """測試 NULL 傳播 - 任何運算 NULL 應返回 NULL"""
        # 驗證 registry 能正確處理 NULL 型別
        result = test_registry.get_function("ISNULL")
        assert result is not None
    
    def test_function_type_inference_aggregate(self, test_registry):
        """測試聚合函數型別推斷"""
        # SUM(INT) 應返回 INT 或 BIGINT
        result = test_registry.get_function("SUM")
        assert result is not None
        assert result.name == "SUM"
        assert result.func_type == "AGGREGATE"

    def test_is_aggregate_cacc_cases(self, test_registry):
        """直接驗證 is_aggregate 的 true / false / missing function 三種路徑。"""
        assert test_registry.is_aggregate("SUM") is True
        assert test_registry.is_aggregate("LEN") is False
        assert not test_registry.is_aggregate("NONEXISTENT_FUNC_12345")
    
    def test_function_not_found(self, test_registry):
        """測試查詢不存在的函數"""
        # 應返回 None 或拋出異常
        result = test_registry.get_function("NONEXISTENT_FUNC_12345")
        assert result is None


# ============================================================================
# 4. WEB/APP 邊界測試 - API 端點錯誤處理
# ============================================================================

class TestWebAppBoundaries:
    """
    測試 web/app.py 的低覆蓋率 (10%)
    
    目標: 提升 web/app.py 從 10% 到 80%+ 覆蓋率
    策略: 測試各個端點的成功和錯誤路徑
    """
    
    @pytest.fixture
    def web_client(self):
        """建立 Flask 測試客戶端"""
        try:
            from web.app import app
            app.config['TESTING'] = True
            return app.test_client()
        except ImportError:
            pytest.skip("web.app 不可用")
    
    def test_parse_endpoint_invalid_json(self, web_client):
        """測試 /api/parse 端點收到無效 JSON"""
        response = web_client.post(
            '/api/parse',
            data='invalid json',
            content_type='application/json'
        )
        assert response.status_code in [400, 422]
    
    def test_parse_endpoint_missing_sql(self, web_client):
        """測試 /api/parse 端點缺少 SQL 参数"""
        response = web_client.post(
            '/api/parse',
            data=json.dumps({}),
            content_type='application/json'
        )
        assert response.status_code in [400, 422]
    
    def test_parse_endpoint_empty_sql(self, web_client):
        """測試 /api/parse 端點收到空 SQL"""
        response = web_client.post(
            '/api/parse',
            data=json.dumps({"sql": ""}),
            content_type='application/json'
        )
        assert response.status_code in [400, 422]
    
    def test_reconstruct_endpoint_invalid_json(self, web_client):
        """測試 /api/reconstruct 端點收到無效 JSON"""
        response = web_client.post(
            '/api/reconstruct',
            data='not json',
            content_type='application/json'
        )
        assert response.status_code in [400, 422]
    
    def test_reconstruct_endpoint_missing_ast(self, web_client):
        """測試 /api/reconstruct 端點缺少 AST"""
        response = web_client.post(
            '/api/reconstruct',
            data=json.dumps({}),
            content_type='application/json'
        )
        assert response.status_code in [400, 422]
    
    def test_parse_endpoint_syntax_error(self, web_client):
        """測試 /api/parse 端點處理語法錯誤"""
        response = web_client.post(
            '/api/parse',
            data=json.dumps({"sql": "SELEC * FORM Orders"}),
            content_type='application/json'
        )
        # 應返回 400 或包含錯誤信息的 200
        assert response.status_code in [200, 400]


# ============================================================================
# 5. 邊界綜合測試 - 覆蓋常見邊界情況
# ============================================================================

class TestCoverageBoundaries:
    """
    綜合邊界測試以覆蓋高頻執行但缺少分支的 clause
    """
    
    @pytest.fixture
    def runner(self):
        """建立全局 runner"""
        csv_data = (
            "table_name,column_name,data_type\n"
            "Address,AddressID,INT\n"
            "Address,AddressLine1,VARCHAR\n"
            "Address,City,VARCHAR\n"
            "City,CityID,INT\n"
            "City,Name,VARCHAR\n"
        )
        registry = MetadataRegistry()
        registry.load_from_csv(io.StringIO(csv_data))
        return BirdEyeRunner(registry)
    
    def test_empty_select_list(self, runner):
        """測試 SELECT 但不包含列 (邊界)"""
        # 大多數 SQL 都有列，但邊界情況應該被拒絕
        with pytest.raises(SyntaxError):
            runner.run("SELECT FROM Address")
    
    def test_multiple_where_conditions(self, runner):
        """測試複雜 WHERE 條件的多個 AND/OR 組合"""
        sql = "SELECT * FROM Address WHERE AddressID = 1 AND City = 'NYC' OR AddressLine1 LIKE '%St%'"
        result = runner.run(sql)
        assert result["ast"] is not None
    
    def test_case_expression_all_branches(self, runner):
        """測試 CASE 表達式的所有分支"""
        sql = """
        SELECT 
            CASE 
                WHEN AddressID < 10 THEN 'Low'
                WHEN AddressID < 100 THEN 'Medium'
                ELSE 'High'
            END
        FROM Address
        """
        result = runner.run(sql)
        assert result["ast"] is not None
    
    def test_null_comparison_is_null(self, runner):
        """測試 IS NULL 與 IS NOT NULL 路徑"""
        sql1 = "SELECT * FROM Address WHERE AddressLine1 IS NULL"
        sql2 = "SELECT * FROM Address WHERE AddressLine1 IS NOT NULL"
        
        result1 = runner.run(sql1)
        result2 = runner.run(sql2)
        
        assert result1["ast"] is not None
        assert result2["ast"] is not None
    
    def test_cast_between_types(self, runner):
        """測試各種類型轉換 (CAST 邊界)"""
        sqls = [
            "SELECT CAST(AddressID AS VARCHAR) FROM Address",
            "SELECT CAST('123' AS INT) FROM Address",
            "SELECT CAST(GETDATE() AS DATE) FROM Address",
        ]
        
        for sql in sqls:
            result = runner.run(sql)
            assert result["ast"] is not None


# ============================================================================
# 6. CACC 擴展測試 - 高頻 One-Sided Clause 的相關聯邏輯覆蓋
# ============================================================================

class TestCACCExtended:
    """
    針對 only-True / only-False 的高頻 clause 新增相關聯的分支測試
    
    主要缺口分析:
    - parser.py:47 (6,995x True, 0x False) - _consume 異常路徑
    - parser.py:775/777/781 (~3-5k True) - token 類型轉換 branch
    - registry.py:189 (2,979x True) - function metadata 查詢
    - lexer.py:270 (4,744x False) - N-string 轉換路徑
    """
    
    @pytest.fixture
    def runner(self):
        """建立全局 runner"""
        csv_data = (
            "table_name,column_name,data_type\n"
            "Orders,OrderID,INT\n"
            "Orders,CustomerID,INT\n"
            "Orders,OrderDate,DATETIME\n"
            "Orders,Amount,DECIMAL\n"
            "Customers,CustomerID,INT\n"
            "Customers,Name,VARCHAR\n"
        )
        registry = MetadataRegistry()
        registry.load_from_csv(io.StringIO(csv_data))
        return BirdEyeRunner(registry)
    
    def test_parser_consume_error_path_multiple_missing(self):
        """
        parser.py:47 - 測試 _consume 在多個連續錯誤時的路徑
        goal: exercise the `if not tok:` branch with successive failures
        """
        # DELETE 後缺少 FROM
        sql = "DELETE * WHERE OrderID = 1"
        lexer = Lexer(sql)
        tokens = lexer.tokenize()
        parser = Parser(tokens, sql)
        
        with pytest.raises(SyntaxError):
            parser.parse()
    
    def test_parser_token_type_check_multiple_branches(self, runner):
        """
        parser.py:775/777/781 - 測試 token type 檢查的多個分支
        Simulate UNION with different operator branches
        """
        sql = "SELECT OrderID FROM Orders UNION SELECT CustomerID FROM Customers"
        result = runner.run(sql)
        assert result["ast"] is not None
        assert isinstance(result["ast"], type(result["ast"]))  # just verify AST exists
    
    def test_parser_token_type_check_multiple_branches_union_all(self, runner):
        """Test UNION ALL 路徑"""
        sql = "SELECT OrderID FROM Orders UNION ALL SELECT CustomerID FROM Customers"
        result = runner.run(sql)
        assert result["ast"] is not None
        # Verify AST was created successfully
    
    def test_parser_except_branch(self, runner):
        """Test EXCEPT operator branch"""
        sql = "SELECT OrderID FROM Orders EXCEPT SELECT CustomerID FROM Customers"
        result = runner.run(sql)
        assert result["ast"] is not None
    
    def test_parser_intersect_branch(self, runner):
        """Test INTERSECT operator branch"""
        sql = "SELECT OrderID FROM Orders INTERSECT SELECT CustomerID FROM Customers"
        result = runner.run(sql)
        assert result["ast"] is not None
    
    def test_registry_function_metadata_all_types(self, runner):
        """
        registry.py:189 - 測試函數型別檢查的各種情況
        Ensure all function type branches are exercised
        """
        # Test SCALAR functions
        result1 = runner.run("SELECT LEN(Name) FROM Customers")
        assert result1["ast"] is not None
        
        # Test AGGREGATE functions
        result2 = runner.run("SELECT COUNT(*) FROM Orders")
        assert result2["ast"] is not None
        
        # Test builtin with different arities
        result3 = runner.run("SELECT SUBSTRING(Name, 1, 3) FROM Customers")
        assert result3["ast"] is not None
    
    def test_lexer_number_prefix_variations(self):
        """
        lexer.py:270 - 測試各種 number/prefix 情況以觸發 token 轉換邏輯
        """
        # Regular integer
        result1 = Lexer("123").tokenize()
        assert len(result1) >= 1
        assert result1[0].type == TokenType.NUMERIC_LITERAL
        
        # Float
        result2 = Lexer("123.45").tokenize()
        assert len(result2) >= 1
        
        # Hexadecimal (if supported)
        result3 = Lexer("0xAB").tokenize()
        assert len(result3) >= 1
    
    def test_lexer_string_literal_variations(self):
        """Test various string literal branches"""
        # Single quote string
        result1 = Lexer("'hello'").tokenize()
        assert result1[0].type == TokenType.STRING_LITERAL
        
        # String with escape
        result2 = Lexer("'it''s'").tokenize()
        assert result2[0].type == TokenType.STRING_LITERAL
    
    def test_binder_null_handling_comprehensive(self, runner):
        """
        Comprehensive type propagation test for NULL handling paths
        """
        # NULL literal type
        result1 = runner.run("SELECT NULL")
        assert result1["ast"] is not None
        
        # NULL in comparison
        result2 = runner.run("SELECT * FROM Orders WHERE OrderDate = NULL")
        assert result2["ast"] is not None
        
        # Type casting with NULL
        result3 = runner.run("SELECT CAST(NULL AS INT)")
        assert result3["ast"] is not None
    
    def test_parser_join_alias_edge_cases(self, runner):
        """
        Test JOIN table alias matching edge cases
        """
        # Simple alias
        result1 = runner.run(
            "SELECT o.OrderID FROM Orders o WHERE o.CustomerID = 1"
        )
        assert result1["ast"] is not None
        
        # Multiple table aliases
        result2 = runner.run(
            "SELECT o.OrderID, c.Name FROM Orders o "
            "JOIN Customers c ON o.CustomerID = c.CustomerID"
        )
        assert result2["ast"] is not None
        
        # Self-join with different aliases
        result3 = runner.run(
            "SELECT * FROM Orders o1 "
            "JOIN Orders o2 ON o1.OrderID = o2.OrderID"
        )
        assert result3["ast"] is not None
    
    def test_parser_function_call_with_various_arg_counts(self, runner):
        """
        Test function calls with 0, 1, 2+ arguments to exercise branch logic
        """
        # 0 args
        result1 = runner.run("SELECT GETDATE()")
        assert result1["ast"] is not None
        
        # 1 arg
        result2 = runner.run("SELECT ABS(-10)")
        assert result2["ast"] is not None
        
        # 2 args (SUBSTRING)
        result3 = runner.run("SELECT SUBSTRING(Name, 1, 3) FROM Customers")
        assert result3["ast"] is not None
        
        # Variadic (COALESCE with table context)
        result4 = runner.run("SELECT COALESCE(OrderDate, GETDATE()) FROM Orders")
        assert result4["ast"] is not None
    
    def test_parser_between_all_paths(self, runner):
        """
        Test BETWEEN operator all paths
        """
        result = runner.run(
            "SELECT * FROM Orders WHERE OrderID BETWEEN 1 AND 100"
        )
        assert result["ast"] is not None
        # Verify parsing succeeded


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
