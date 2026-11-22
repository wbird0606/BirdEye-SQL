package birdeye

import (
	"strings"
	"testing"
)

// isExecPolicyDeviation 判斷錯誤是否來自預存程序白名單政策（與 Python 基準版之刻意差異，見 KNOWN_DEVIATIONS A13）。
func isExecPolicyDeviation(err error) bool {
	m := err.Error()
	return strings.Contains(m, "is not on the ZTA allow-list") ||
		strings.Contains(m, "given by a variable is not allowed") ||
		strings.Contains(m, "without a literal procedure name")
}

func runExec(t *testing.T, allow []string, sql string) error {
	t.Helper()
	_, err := NewRunner(loadAdventureWorks(t)).WithAllowedProcs(allow).Run(sql, nil)
	return err
}

func TestExecDefaultDeny(t *testing.T) {
	for _, sql := range []string{
		"EXEC usp_GetPayroll",
		"EXEC dbo.usp_GetPayroll 1",
		"EXECUTE usp_GetPayroll @EmpID = 1",
		"EXEC sp_help 'Customer'", // 系統程序亦不例外：會洩漏無權限資料表之欄位結構
		"EXEC sp_columns Customer",
	} {
		err := runExec(t, nil, sql)
		if err == nil || !strings.Contains(err.Error(), "allow-list") {
			t.Errorf("%q 應因不在白名單而被拒絕，got %v", sql, err)
		}
	}
}

func TestExecAllowList(t *testing.T) {
	allow := ParseProcAllowList(" usp_GetOrders , dbo.usp_GetPayroll,Sales.usp_Report ")
	ok := []string{
		"EXEC usp_GetOrders",
		"EXEC USP_GETORDERS 1",           // 不分大小寫
		"EXEC dbo.usp_GetPayroll @a = 1", // 白名單含 schema
		"EXEC usp_GetPayroll",            // 未指定 schema 視同 dbo
		"EXEC Sales.usp_Report",
	}
	for _, sql := range ok {
		if err := runExec(t, allow, sql); err != nil {
			t.Errorf("%q 應被放行，got %v", sql, err)
		}
	}
	deny := []string{
		"EXEC usp_Other",
		"EXEC dbo.usp_GetOrders",    // 白名單只列未限定名稱：不涵蓋明確指定之 dbo.<name>
		"EXEC Other.usp_GetPayroll", // schema 不同
		"EXEC Sales.usp_GetPayroll",
		"EXEC mydb.dbo.usp_GetPayroll", // 三段式不在白名單
	}
	for _, sql := range deny {
		if err := runExec(t, allow, sql); err == nil {
			t.Errorf("%q 應被拒絕", sql)
		}
	}
}

func TestExecBlocklistOverridesAllowList(t *testing.T) {
	allow := []string{"xp_cmdshell", "sp_executesql", "sp_configure"}
	for _, sql := range []string{"EXEC xp_cmdshell 'dir'", "EXEC sp_executesql N'SELECT 1'", "EXEC sp_configure"} {
		err := runExec(t, allow, sql)
		if err == nil || !strings.Contains(err.Error(), "blocked by ZTA policy") {
			t.Errorf("%q 即使列入白名單仍應被封鎖清單攔截，got %v", sql, err)
		}
	}
}

func TestExecVariableProcName(t *testing.T) {
	// 以變數指定之程序名稱無法審核，即使白名單列出該變數名稱亦拒絕
	err := runExec(t, []string{"@dynamic_proc"}, "EXEC @dynamic_proc 1, 2")
	if err == nil {
		t.Error("以變數指定程序名稱應被拒絕")
	}
}

func TestParseProcAllowList(t *testing.T) {
	got := ParseProcAllowList(" a , ,b,, dbo.c ")
	if len(got) != 3 || got[0] != "a" || got[1] != "b" || got[2] != "dbo.c" {
		t.Errorf("ParseProcAllowList = %v", got)
	}
	if ParseProcAllowList("") != nil || procSet(nil) != nil {
		t.Error("空輸入應回傳 nil")
	}
}
