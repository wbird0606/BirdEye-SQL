import pytest
import sys
from unittest.mock import patch
from io import StringIO
# 載入我們將要實作或修正的 CLI main 函數
from main import main

def run_cli_with_args(*args):
    """輔助函式：模擬命令列參數執行 main()，並攔截 stdout/stderr"""
    # 將 'main.py' 加入 args 首位模擬真實 sys.argv
    test_args = ['main.py'] + list(args)
    with patch('sys.argv', test_args):
        # 攔截標準輸出
        with patch('sys.stdout', new=StringIO()) as fake_out:
            with patch('sys.stderr', new=StringIO()) as fake_err:
                try:
                    main()
                except SystemExit as e:
                    return e.code, fake_out.getvalue(), fake_err.getvalue()
                return 0, fake_out.getvalue(), fake_err.getvalue()

# --- 1. TDD Red Phase: CLI 基礎參數驗證 ---

def test_cli_requires_input_arguments():
    """驗證：如果沒有給予 --sql 或 --file，CLI 應以錯誤碼 2 (argparse) 退出"""
    exit_code, out, err = run_cli_with_args()
    assert exit_code == 2
    assert "error: one of the arguments" in err or "the following arguments are required" in err

def test_cli_successful_sql_parsing():
    """驗證：給予合法的 --sql，應以 0 退出並在 stdout 顯示 AST Tree"""
    # 這是非常基礎的 SELECT，依賴 global_runner 的預設元數據機制
    exit_code, out, err = run_cli_with_args("--sql", "SELECT AddressID FROM Address")
    assert exit_code == 0
    assert "SELECT_STATEMENT" in out
    assert "IDENTIFIER: AddressID" in out

def test_cli_semantic_error_handling():
    """驗證：遇到語意錯誤 (如 ZTA 攔截) 時，應以錯誤碼 1 退出，並輸出到 stderr"""
    # GhostTable 不存在於 output.csv 中
    exit_code, out, err = run_cli_with_args("--sql", "SELECT * FROM GhostTable")
    assert exit_code == 1
    assert "Semantic Error" in err
    assert "Table 'GhostTable' not found" in err

def test_cli_format_output_options():
    """驗證：--format 參數能正確切換輸出格式"""
    exit_code, out, err = run_cli_with_args("--sql", "SELECT AddressID FROM Address", "--format", "mermaid")
    assert exit_code == 0
    assert "graph TD" in out
    assert "SELECT_STATEMENT" not in out # Tree 格式不應出現
