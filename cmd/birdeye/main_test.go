package main

import (
	"bytes"
	"strings"
	"testing"
)

// 對照 python-final:tests/test_cli_suite.py

const testCSV = "../../data/output.csv"

func runCLI(args ...string) (code int, out, errOut string) {
	var o, e bytes.Buffer
	code = run(args, &o, &e)
	return code, o.String(), e.String()
}

func TestCLI_RequiresInput(t *testing.T) {
	code, _, errOut := runCLI()
	if code != 2 {
		t.Fatalf("exit code %d, want 2", code)
	}
	if !strings.Contains(errOut, "arguments are required") && !strings.Contains(errOut, "one of the arguments") {
		t.Errorf("stderr: %q", errOut)
	}
}

func TestCLI_SuccessfulSQLParsing(t *testing.T) {
	code, out, errOut := runCLI("-csv", testCSV, "-sql", "SELECT AddressID FROM Address")
	if code != 0 {
		t.Fatalf("exit %d; stderr=%s", code, errOut)
	}
	if !strings.Contains(out, "SELECT_STATEMENT") || !strings.Contains(out, "IDENTIFIER: AddressID") {
		t.Errorf("stdout: %q", out)
	}
}

func TestCLI_SemanticErrorHandling(t *testing.T) {
	code, _, errOut := runCLI("-csv", testCSV, "-sql", "SELECT * FROM GhostTable")
	if code != 1 {
		t.Fatalf("exit %d, want 1", code)
	}
	if !strings.Contains(errOut, "Semantic Error") || !strings.Contains(errOut, "Table 'GhostTable' not found") {
		t.Errorf("stderr: %q", errOut)
	}
}

func TestCLI_FormatOutputOptions(t *testing.T) {
	code, out, _ := runCLI("-csv", testCSV, "-sql", "SELECT AddressID FROM Address", "-format", "mermaid")
	if code != 0 {
		t.Fatalf("exit %d", code)
	}
	if !strings.Contains(out, "flowchart TD") {
		t.Errorf("no mermaid: %q", out)
	}
	if strings.Contains(out, "SELECT_STATEMENT") {
		t.Errorf("mermaid format 不應含 tree: %q", out)
	}
}

func TestCLI_ASTToSQL(t *testing.T) {
	code, out, errOut := runCLI("-ast", `{"node_type":"SelectStatement","is_star":true,"table":{"node_type":"IdentifierNode","name":"Address","qualifiers":[]}}`)
	if code != 0 {
		t.Fatalf("exit %d; %s", code, errOut)
	}
	if strings.TrimSpace(out) != "SELECT * FROM Address" {
		t.Errorf("AST→SQL: %q", out)
	}
}

func TestCLI_Params(t *testing.T) {
	// 具名
	code, out, errOut := runCLI("-csv", testCSV, "-sql", "SELECT @p AS x", "-params", `{"@p": 30}`, "-format", "json")
	if code != 0 || !strings.Contains(out, `"@P": "INT"`) {
		t.Errorf("named param: exit=%d out=%q err=%q", code, out, errOut)
	}
	// 位置（qmark）
	code2, out2, _ := runCLI("-csv", testCSV, "-sql", "SELECT AddressID FROM Address WHERE AddressID = ? AND City = ?", "-params", `[1, "Seattle"]`, "-format", "json")
	if code2 != 0 || !strings.Contains(out2, `"param_input_mode": "qmark"`) {
		t.Errorf("qmark param: exit=%d out=%q", code2, out2)
	}
	// 數量不符
	code3, _, err3 := runCLI("-csv", testCSV, "-sql", "SELECT AddressID FROM Address WHERE AddressID = ?", "-params", `[1, 2]`)
	if code3 != 1 || !strings.Contains(err3, "PARAM_COUNT_MISMATCH") {
		t.Errorf("count mismatch: exit=%d err=%q", code3, err3)
	}
}

func TestCLI_MutualExclusion(t *testing.T) {
	code, _, errOut := runCLI("-sql", "SELECT 1", "-ast", "{}")
	if code != 2 || !strings.Contains(errOut, "互斥") {
		t.Errorf("exit=%d err=%q", code, errOut)
	}
}
