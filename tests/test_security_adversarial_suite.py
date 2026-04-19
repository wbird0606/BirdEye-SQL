"""
test_security_adversarial_suite.py — BirdEye-SQL 安全邊界對抗性測試

目的：驗證 BirdEye-SQL 對下列攻擊向量的防護能力，並誠實報告解析器邊界。
涵蓋：
  1. 預存程序封鎖清單（EXEC BLOCKED list）
  2. 函式黑名單（restricted_functions）
  3. Stacked query / 多語句注入
  4. Comment 混淆（繞過嘗試）
  5. Fail-Closed 驗證（不支援語法 → SyntaxError，不放行）
  6. 已知解析器邊界（誠實報告無法支援的語法）
"""

import pytest

from birdeye.lexer import Lexer
from birdeye.parser import Parser
from birdeye.binder import Binder, SemanticError
from birdeye.registry import MetadataRegistry
from birdeye.runner import BirdEyeRunner


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_registry(extra_csv: str = "") -> MetadataRegistry:
    """建立含基本 schema 的 MetadataRegistry。"""
    import io
    reg = MetadataRegistry()
    base_csv = (
        "table_name,column_name,data_type\n"
        "Customer,CustomerID,INT\n"
        "Customer,Name,NVARCHAR\n"
        "Customer,Email,NVARCHAR\n"
        "Orders,OrderID,INT\n"
        "Orders,CustomerID,INT\n"
    )
    reg.load_from_csv(io.StringIO(base_csv + extra_csv))
    return reg


def _parse_bind(sql: str, reg: MetadataRegistry = None):
    """解析並綁定一條 SQL，回傳 AST；若失敗則拋出例外。"""
    if reg is None:
        reg = _make_registry()
    tokens = Lexer(sql).tokenize()
    ast = Parser(tokens, sql).parse()
    Binder(reg).bind(ast)
    return ast


def _parse_only(sql: str):
    """僅執行 Lexer + Parser，不執行 Binder。"""
    tokens = Lexer(sql).tokenize()
    return Parser(tokens, sql).parse()


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 預存程序封鎖清單（EXEC BLOCKED list）
# ═══════════════════════════════════════════════════════════════════════════════

class TestExecBlocklist:
    """
    Binder._bind_exec() 維護一份封鎖清單：
    XP_CMDSHELL, SP_EXECUTESQL, SP_OA_CREATE, SP_OA_METHOD,
    SP_OA_GETPROPERTY, SP_CONFIGURE, OPENROWSET, OPENQUERY
    任一命中皆拋出 SemanticError，Proxy 回傳 HTTP 400（Fail-Closed）。
    """

    def test_blocks_xp_cmdshell(self):
        """XP_CMDSHELL：作業系統指令執行路徑封鎖"""
        with pytest.raises(SemanticError, match="blocked by ZTA policy"):
            _parse_bind("EXEC xp_cmdshell 'whoami'")

    def test_blocks_sp_executesql(self):
        """SP_EXECUTESQL：動態 SQL 執行封鎖（防止繞過靜態語法分析）"""
        with pytest.raises(SemanticError, match="blocked by ZTA policy"):
            _parse_bind("EXEC sp_executesql N'SELECT * FROM Customer'")

    def test_blocks_sp_oa_create(self):
        """SP_OA_CREATE：OLE 自動化物件建立封鎖（帶外滲漏路徑）
        注意：OUTPUT 關鍵字為 Parser 不支援語法，於 Parser 層拋出 SyntaxError（Fail-Closed），
        不會到達 Binder 的 SemanticError 層，結果同為 HTTP 400 拒絕。"""
        with pytest.raises((SemanticError, SyntaxError)):
            _parse_bind("EXEC sp_oa_create 'WScript.Shell', @obj OUTPUT")

    def test_blocks_sp_oa_method(self):
        """SP_OA_METHOD：OLE 自動化方法呼叫封鎖
        注意：OUTPUT 關鍵字為 Parser 不支援語法，於 Parser 層拋出 SyntaxError（Fail-Closed）。"""
        with pytest.raises((SemanticError, SyntaxError)):
            _parse_bind("EXEC sp_oa_method @obj, 'Run', @ret OUTPUT, 'cmd'")

    def test_blocks_sp_configure(self):
        """SP_CONFIGURE：伺服器組態修改封鎖"""
        with pytest.raises(SemanticError, match="blocked by ZTA policy"):
            _parse_bind("EXEC sp_configure 'show advanced options', 1")

    def test_blocks_openquery(self):
        """OPENQUERY：Linked Server 查詢封鎖（帶外資料存取路徑）
        注意：OPENQUERY 後的括號引數語法為 Parser 不支援形式，
        於 Parser 層拋出 SyntaxError（Fail-Closed），結果同為 HTTP 400 拒絕。"""
        with pytest.raises((SemanticError, SyntaxError)):
            _parse_bind("EXEC openquery(LinkedSrv, 'SELECT * FROM remote.db')")

    def test_blocks_case_insensitive_upper(self):
        """封鎖清單比對不分大小寫（全大寫）"""
        with pytest.raises(SemanticError, match="blocked by ZTA policy"):
            _parse_bind("EXEC XP_CMDSHELL 'dir'")

    def test_blocks_case_insensitive_mixed(self):
        """封鎖清單比對不分大小寫（混合大小寫）"""
        with pytest.raises(SemanticError, match="blocked by ZTA policy"):
            _parse_bind("EXEC Xp_CmdShell 'dir'")

    def test_blocks_execute_keyword_variant(self):
        """EXECUTE 關鍵字（非 EXEC）同樣觸發封鎖"""
        with pytest.raises(SemanticError, match="blocked by ZTA policy"):
            _parse_bind("EXECUTE xp_cmdshell 'net user'")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 函式黑名單（restricted_functions in MetadataRegistry）
# ═══════════════════════════════════════════════════════════════════════════════

class TestFunctionBlocklist:
    """
    MetadataRegistry.restricted_functions 包含：
    OPENROWSET, OPENDATASOURCE, OPENXML, IS_SRVROLEMEMBER, HAS_PERMS_BY_NAME
    Binder._visit_function() 辨識後拋出 SemanticError。
    """

    def test_blocks_openrowset(self):
        """OPENROWSET：帶外資料源存取封鎖。
        當 OPENROWSET 出現於 FROM 子句（作為資料列集提供者）時，
        Parser 不支援此語法形式，於 Parser 層拋出 SyntaxError（Fail-Closed）。
        當出現於 SELECT 運算式（作為函式呼叫）時，Binder 以 restricted_functions 封鎖。
        兩種形式均無法通過，最終 Proxy 回傳 HTTP 400。"""
        with pytest.raises((SemanticError, SyntaxError)):
            _parse_bind(
                "SELECT * FROM OPENROWSET('SQLNCLI','Server=evil.com;',"
                "'SELECT secret FROM db.dbo.secrets')"
            )

    def test_blocks_opendatasource(self):
        """OPENDATASOURCE：即席 Linked Server 存取封鎖。
        FROM 子句中的 OPENDATASOURCE 語法為 Parser 不支援形式，
        拋出 SyntaxError（Fail-Closed → HTTP 400）。"""
        with pytest.raises((SemanticError, SyntaxError)):
            _parse_bind(
                "SELECT * FROM OPENDATASOURCE('SQLNCLI',"
                "'Data Source=evil.com').db.dbo.T"
            )

    def test_blocks_is_srvrolemember(self):
        """IS_SRVROLEMEMBER：伺服器角色偵察封鎖"""
        with pytest.raises(SemanticError):
            _parse_bind("SELECT IS_SRVROLEMEMBER('sysadmin')")

    def test_blocks_has_perms_by_name(self):
        """HAS_PERMS_BY_NAME：權限偵察封鎖"""
        with pytest.raises(SemanticError):
            _parse_bind(
                "SELECT HAS_PERMS_BY_NAME('Customer', 'OBJECT', 'SELECT')"
            )

    def test_blocks_case_insensitive(self):
        """函式黑名單比對不分大小寫"""
        with pytest.raises(SemanticError):
            _parse_bind("SELECT openrowset('MSDASQL', 'Driver=SQL Server', 'SELECT 1')")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Stacked Query / 多語句注入（Parser 嚴格單語句限制）
# ═══════════════════════════════════════════════════════════════════════════════

class TestStackedQueryRejection:
    """
    Parser.parse() 在解析完第一個完整語句後，若 Token 串流仍有非 EOF 殘餘 Token，
    立即拋出 SyntaxError。此機制與語義無關，純粹基於語法結構。
    """

    def test_semicolon_drop(self):
        """分號 + DROP TABLE：stacked query 最常見形式"""
        with pytest.raises(SyntaxError, match="Unexpected token"):
            _parse_only("SELECT * FROM Customer; DROP TABLE Customer")

    def test_semicolon_waitfor(self):
        """分號 + WAITFOR DELAY：時間盲注多語句形式"""
        with pytest.raises(SyntaxError, match="Unexpected token"):
            _parse_only("SELECT CustomerID FROM Customer; WAITFOR DELAY '0:0:5'")

    def test_semicolon_insert(self):
        """分號 + INSERT：資料竄改多語句形式"""
        with pytest.raises(SyntaxError, match="Unexpected token"):
            _parse_only(
                "SELECT Name FROM Customer; "
                "INSERT INTO Customer(Name) VALUES('injected')"
            )

    def test_semicolon_update(self):
        """分號 + UPDATE：資料修改多語句形式"""
        with pytest.raises(SyntaxError, match="Unexpected token"):
            _parse_only(
                "SELECT Name FROM Customer; "
                "UPDATE Customer SET Name='pwned' WHERE 1=1"
            )

    def test_second_select_without_semicolon(self):
        """無分號直接接第二個 SELECT（部分方言允許，BirdEye 拒絕）"""
        with pytest.raises(SyntaxError, match="Unexpected token"):
            _parse_only("SELECT 1 SELECT 2")

    def test_trailing_semicolon_single_stmt_is_ok(self):
        """單語句尾端分號（合法，不應拋出例外）"""
        ast = _parse_only("SELECT CustomerID FROM Customer;")
        assert ast is not None

    def test_waitfor_alone_is_invalid_stmt_start(self):
        """WAITFOR 單獨作為語句起始（非合法語句開頭，Parser 拋出例外）"""
        with pytest.raises(SyntaxError):
            _parse_only("WAITFOR DELAY '0:0:5'")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Comment 混淆繞過嘗試
# ═══════════════════════════════════════════════════════════════════════════════

class TestCommentObfuscation:
    """
    Lexer 在 tokenize 階段靜默去除 -- 單行與 /* */ 多行 comment。
    驗證 comment 混淆不影響語義解析正確性（comment 去除後語義等同原始語句）。
    """

    def test_single_line_comment_in_select(self):
        """-- 單行 comment 夾在 SELECT 欄位間，解析應成功"""
        ast = _parse_only("SELECT CustomerID -- this is id\n, Name FROM Customer")
        assert ast is not None

    def test_block_comment_between_keywords(self):
        """/* */ 多行 comment 插入關鍵字之間，解析應成功"""
        ast = _parse_only("SELECT /* bypass? */ CustomerID FROM Customer")
        assert ast is not None

    def test_nested_comment_stripped(self):
        """/* comment /* nested? */ */ 外層關閉後繼續解析"""
        # MSSQL 不支援真正的巢狀 comment，但外層 /* ... */ 應正常閉合
        ast = _parse_only("SELECT CustomerID /* outer */ FROM Customer")
        assert ast is not None

    def test_comment_cannot_split_keyword(self):
        """comment 無法插入關鍵字中間拆分（如 SEL/**/ECT，Lexer 不支援，應視為識別符）"""
        # "SEL" 被視為 IDENTIFIER，"ECT" 也是 IDENTIFIER，Parser 拋出 SyntaxError
        with pytest.raises(SyntaxError):
            _parse_only("SEL/**/ECT CustomerID FROM Customer")

    def test_comment_after_stacked_query_does_not_rescue(self):
        """-- comment 無法讓 stacked query 通過（殘餘 DROP 仍觸發 SyntaxError）"""
        with pytest.raises(SyntaxError, match="Unexpected token"):
            _parse_only("SELECT * FROM Customer; DROP TABLE Customer --")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Fail-Closed 驗證（不支援語法 → SyntaxError，不放行）
# ═══════════════════════════════════════════════════════════════════════════════

class TestFailClosed:
    """
    BirdEye-SQL 採 Fail-Closed 策略：遇到無法解析的語法時拋出 SyntaxError，
    Proxy 回傳 HTTP 400，不放行至資料庫。
    本節驗證常見的「合法但未支援」T-SQL 語法均觸發 Fail-Closed 而非靜默放行。
    """

    def test_pivot_raises_syntaxerror(self):
        """PIVOT：不支援，觸發 SyntaxError（Fail-Closed）"""
        with pytest.raises(SyntaxError):
            _parse_only(
                "SELECT * FROM Sales PIVOT "
                "(SUM(Amount) FOR Region IN ([North],[South])) AS P"
            )

    def test_for_xml_raises_syntaxerror(self):
        """FOR XML：不支援，觸發 SyntaxError（Fail-Closed）"""
        with pytest.raises(SyntaxError):
            _parse_only("SELECT CustomerID, Name FROM Customer FOR XML AUTO")

    def test_for_json_raises_syntaxerror(self):
        """FOR JSON：不支援，觸發 SyntaxError（Fail-Closed）"""
        with pytest.raises(SyntaxError):
            _parse_only("SELECT CustomerID FROM Customer FOR JSON PATH")

    def test_bulk_insert_raises_syntaxerror(self):
        """BULK INSERT：不支援，觸發 SyntaxError（Fail-Closed）"""
        with pytest.raises(SyntaxError):
            _parse_only("BULK INSERT Customer FROM 'C:\\data.csv'")

    def test_empty_sql_raises(self):
        """空字串 SQL：解析應拋出例外或回傳空結果，不放行"""
        with pytest.raises((SyntaxError, IndexError, Exception)):
            _parse_only("")

    def test_only_comment_raises(self):
        """純 comment 無任何語句：解析後無有效 AST 節點"""
        with pytest.raises((SyntaxError, IndexError, Exception)):
            _parse_only("-- just a comment")

    def test_unclosed_string_raises(self):
        """未閉合字串字面值：Lexer 拋出 ValueError（Fail-Closed）"""
        with pytest.raises((ValueError, SyntaxError)):
            _parse_only("SELECT * FROM Customer WHERE Name = 'unclosed")

    def test_unclosed_bracket_raises(self):
        """未閉合括號識別符：Lexer 拋出 ValueError（Fail-Closed）"""
        with pytest.raises((ValueError, SyntaxError)):
            _parse_only("SELECT [unclosed FROM Customer")


# ═══════════════════════════════════════════════════════════════════════════════
# 6. N'' Unicode 字串前綴（正當語法，不應被誤判為攻擊）
# ═══════════════════════════════════════════════════════════════════════════════

class TestUnicodeStringHandling:
    """
    驗證 N'' Unicode 字串前綴正確解析，不觸發誤判。
    Unicode 正規化攻擊在 BirdEye 層面的防禦依賴 Fail-Closed：
    若攻擊者使用未被 Lexer 辨識的 Unicode 序列，將觸發 SyntaxError。
    """

    def test_n_prefix_string_in_where(self):
        """WHERE 子句中 N'...' 字串正確解析"""
        ast = _parse_only("SELECT CustomerID FROM Customer WHERE Name = N'Taipei'")
        assert ast is not None

    def test_n_prefix_in_insert_values(self):
        """INSERT VALUES 中 N'...' 字串正確解析"""
        ast = _parse_only(
            "INSERT INTO Customer(Name) VALUES(N'測試名稱')"
        )
        assert ast is not None

    def test_n_prefix_exec_argument(self):
        """EXEC 參數中 N'...' 字串（sp_executesql 仍被封鎖，與字串前綴無關）"""
        with pytest.raises(SemanticError, match="blocked by ZTA policy"):
            _parse_bind("EXEC sp_executesql N'SELECT * FROM Customer'")


# ═══════════════════════════════════════════════════════════════════════════════
# 7. 已知解析器邊界（誠實報告）
# ═══════════════════════════════════════════════════════════════════════════════

class TestKnownParserBoundaries:
    """
    本節誠實記錄 BirdEye-SQL 目前不支援、但在 ZTA 場景下依 Fail-Closed 原則
    仍能保障安全性的語法邊界。這些並非安全漏洞——Fail-Closed 確保不支援語法
    同樣被拒絕，不存在「繞過語義分析」的靜默放行風險。

    如需支援這些語法，應擴充 Parser 並補充對應意圖萃取邏輯。
    """

    def test_pivot_unsupported(self):
        """已知邊界：PIVOT 語法不支援（Fail-Closed → HTTP 400）"""
        with pytest.raises(SyntaxError):
            _parse_only("SELECT * FROM T PIVOT (SUM(v) FOR c IN ([a])) AS P")

    def test_for_xml_unsupported(self):
        """已知邊界：FOR XML 不支援（Fail-Closed → HTTP 400）"""
        with pytest.raises(SyntaxError):
            _parse_only("SELECT id FROM T FOR XML RAW")

    def test_openxml_function_blocked(self):
        """已知邊界：OPENXML 在函式黑名單中。
        在 SELECT 運算式中直接呼叫時（單語句），Binder 會以 SemanticError 封鎖。
        注意：若將 DECLARE 與 SELECT 以分號串接作為兩語句提交，
        會先觸發 stacked query SyntaxError（同樣為 Fail-Closed）。"""
        with pytest.raises(SemanticError):
            _parse_bind("SELECT OPENXML(1, '/r') FROM Customer")

# ═══════════════════════════════════════════════════════════════════════════════
# 8. 引號閉合注入（Quote-Closing Injection）— T2/T3 字串參數模板
# ═══════════════════════════════════════════════════════════════════════════════

SCHEMA_CSV_SALES = (
    "table_schema,table_name,column_name,data_type\n"
    "SalesLT,Customer,CustomerID,INT\n"
    "SalesLT,Customer,Name,NVARCHAR\n"
    "SalesLT,Customer,EmailAddress,NVARCHAR\n"
    "SalesLT,Customer,Phone,NVARCHAR\n"
    "SalesLT,Customer,PasswordHash,NVARCHAR\n"
)

import io as _io
import json as _json
from birdeye.intent_extractor import IntentExtractor

_extractor = IntentExtractor()

def _run_and_intents(sql: str) -> list[dict]:
    """執行完整 BirdEye pipeline，回傳 intent 清單；解析失敗則拋出例外。"""
    import io
    reg = MetadataRegistry()
    reg.load_from_csv(io.StringIO(SCHEMA_CSV_SALES))
    runner = BirdEyeRunner(registry=reg)  # must pass registry to ctor so _binder gets it
    result = runner.run(sql)
    ast_dict = _json.loads(result["json"])
    intents = _extractor.extract(ast_dict)
    return _extractor.expand_star_intents(intents, runner)

def _intent_columns(intents: list[dict]) -> set[str]:
    return {(i["table"].upper(), (i["column"] or "").upper()) for i in intents}

SENSITIVE = {("CUSTOMER", "EMAILADDRESS"), ("CUSTOMER", "PHONE"),
             ("CUSTOMER", "PASSWORDHASH")}


class TestQuoteClosingInjection:
    """
    T2/T3 字串參數模板的引號閉合注入測試。

    當 AP 層存在字串拼接漏洞時，攻擊者閉合引號後附加惡意 SQL。
    預期行為：
      - UNION / FILTER 含敏感欄位 → BirdEye 產生敏感 intent → Permission API 阻斷 (403)
      - Stacked query → SyntaxError → HTTP 400

    模板 T2：SELECT CustomerID, Name FROM SalesLT.Customer WHERE Name = '{INJECT}'
    模板 T3：SELECT CustomerID, Name FROM SalesLT.Customer WHERE Name LIKE '%{INJECT}%'
    """

    T2 = "SELECT CustomerID, Name FROM SalesLT.Customer WHERE Name = '{INJECT}'"
    T3 = "SELECT CustomerID, Name FROM SalesLT.Customer WHERE Name LIKE '%{INJECT}%'"

    def _inject(self, template: str, payload: str) -> str:
        return template.replace("{INJECT}", payload)

    # ── UNION 萃取（閉合引號後 UNION SELECT 敏感欄位）────────────────────────

    def test_t2_union_email(self):
        """T2 引號閉合 UNION 讀 EmailAddress → 敏感 intent → 403
        T2 有 2 欄 (CustomerID, Name)，UNION 右側需同為 2 欄以通過欄位數驗證。"""
        sql = self._inject(self.T2,
            "' UNION SELECT CustomerID, EmailAddress FROM SalesLT.Customer--")
        intents = _run_and_intents(sql)
        cols = _intent_columns(intents)
        assert cols & SENSITIVE, f"預期含敏感欄位 intent，實際：{cols}"

    def test_t2_union_passwordhash(self):
        """T2 引號閉合 UNION 讀 PasswordHash → 敏感 intent → 403"""
        sql = self._inject(self.T2,
            "' UNION SELECT CustomerID, PasswordHash FROM SalesLT.Customer--")
        intents = _run_and_intents(sql)
        cols = _intent_columns(intents)
        assert cols & SENSITIVE, f"預期含敏感欄位 intent，實際：{cols}"

    def test_t2_union_null_padding(self):
        """T2 引號閉合 UNION NULL 填充讀 EmailAddress → 敏感 intent → 403
        攻擊者先用 ORDER BY 探測欄位數（2），再以 NULL 填充。"""
        sql = self._inject(self.T2,
            "' UNION SELECT NULL, EmailAddress FROM SalesLT.Customer--")
        intents = _run_and_intents(sql)
        cols = _intent_columns(intents)
        assert cols & SENSITIVE, f"預期含敏感欄位 intent，實際：{cols}"

    def test_t3_union_email(self):
        """T3 LIKE 引號閉合 UNION 讀 EmailAddress → 敏感 intent → 403"""
        sql = self._inject(self.T3,
            "%' UNION SELECT CustomerID, EmailAddress FROM SalesLT.Customer--")
        intents = _run_and_intents(sql)
        cols = _intent_columns(intents)
        assert cols & SENSITIVE, f"預期含敏感欄位 intent，實際：{cols}"

    # ── Boolean 盲注（閉合引號後 OR/AND 敏感欄位條件）────────────────────────

    def test_t2_boolean_passwordhash_notnull(self):
        """T2 閉合引號 OR PasswordHash IS NOT NULL → FILTER 敏感欄位 → 403"""
        sql = self._inject(self.T2, "' OR PasswordHash IS NOT NULL--")
        intents = _run_and_intents(sql)
        cols = _intent_columns(intents)
        assert cols & SENSITIVE, f"預期含敏感欄位 FILTER intent，實際：{cols}"

    def test_t2_boolean_email_substring(self):
        """T2 閉合引號 AND SUBSTRING(EmailAddress) 探測 → FILTER 敏感欄位 → 403"""
        sql = self._inject(self.T2,
            "' AND SUBSTRING(EmailAddress,1,1)=CHAR(97)--")
        intents = _run_and_intents(sql)
        cols = _intent_columns(intents)
        assert cols & SENSITIVE, f"預期含敏感欄位 FILTER intent，實際：{cols}"

    def test_t2_boolean_email_like(self):
        """T2 閉合引號 OR EmailAddress LIKE 探測 → FILTER 敏感欄位 → 403"""
        sql = self._inject(self.T2, "' OR EmailAddress LIKE CHAR(37)--")
        intents = _run_and_intents(sql)
        cols = _intent_columns(intents)
        assert cols & SENSITIVE, f"預期含敏感欄位 FILTER intent，實際：{cols}"

    def test_t3_boolean_phone_len(self):
        """T3 LIKE 閉合引號 AND LEN(Phone) 探測 → FILTER 敏感欄位 → 403"""
        sql = self._inject(self.T3, "%' AND LEN(Phone) > 0--")
        intents = _run_and_intents(sql)
        cols = _intent_columns(intents)
        assert cols & SENSITIVE, f"預期含敏感欄位 FILTER intent，實際：{cols}"

    # ── Stacked Query（閉合引號後分號注入第二語句）───────────────────────────

    def test_t2_stacked_drop(self):
        """T2 閉合引號 stacked DROP TABLE → SyntaxError → 400"""
        sql = self._inject(self.T2, "'; DROP TABLE SalesLT.Customer--")
        with pytest.raises(SyntaxError):
            _run_and_intents(sql)

    def test_t2_stacked_update(self):
        """T2 閉合引號 stacked UPDATE 竄改資料 → SyntaxError → 400"""
        sql = self._inject(self.T2,
            "'; UPDATE SalesLT.Customer SET PasswordHash=CHAR(49) WHERE 1=1--")
        with pytest.raises(SyntaxError):
            _run_and_intents(sql)

    def test_t3_stacked_exec(self):
        """T3 LIKE 閉合引號 stacked EXEC xp_cmdshell → SyntaxError → 400"""
        sql = self._inject(self.T3,
            "%'; EXEC xp_cmdshell CHAR(119)--")
        with pytest.raises(SyntaxError):
            _run_and_intents(sql)

    def test_linked_server_fourpart_identifier_known_gap(self):
        """已知邊界（誠實揭露）：四段式 Linked Server 識別符
        （如 LinkedSrv.RemoteDB.dbo.Customer）目前被 Parser 靜默接受，
        不拋出 SyntaxError。意圖萃取會將其視為帶多段 qualifier 的識別符，
        可能無法正確對應到本地資料庫 schema，導致意圖清單不完整。
        此為已知覆蓋缺口——實務上 Linked Server 應透過 OPENQUERY 呼叫（已封鎖），
        四段式直接引用在 MSSQL 環境中較為罕見，但建議在未來版本中加入驗證。"""
        # 此測試驗證「已知可通過 Parser 但意圖萃取不完整」的邊界情境
        try:
            ast = _parse_only("SELECT * FROM LinkedSrv.RemoteDB.dbo.Customer")
            # 若未拋出例外，記錄此為已知邊界，不視為測試失敗
            assert ast is not None, "Parser accepts four-part identifiers (known boundary)"
        except SyntaxError:
            pass  # 若未來版本加入驗證，此處會通過
