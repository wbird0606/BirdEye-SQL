import argparse
import sys
import json
from birdeye.runner import BirdEyeRunner
from birdeye.binder import SemanticError
from birdeye.reconstructor import ASTReconstructor

def main():
    parser = argparse.ArgumentParser(
        description="🦅 BirdEye-SQL: Semantic-Aware & Zero-Trust SQL Parser",
        formatter_class=argparse.RawTextHelpFormatter
    )

    # 輸入來源（SQL→AST 或 AST→SQL 二擇一）
    group_input = parser.add_mutually_exclusive_group(required=True)
    group_input.add_argument("--sql", type=str, help="[SQL→AST] 直接輸入 SQL 查詢字串")
    group_input.add_argument("--file", type=str, help="[SQL→AST] 從檔案讀取 SQL 查詢")
    group_input.add_argument("--ast", type=str, help="[AST→SQL] 直接輸入 AST JSON 字串")
    group_input.add_argument("--ast-file", type=str, dest="ast_file", help="[AST→SQL] 從檔案讀取 AST JSON")

    # SQL→AST 參數
    parser.add_argument("--csv", type=str, default="data/output.csv", help="指定元數據 CSV 檔案路徑 (預設: data/output.csv)")
    parser.add_argument("--format", type=str, choices=["tree", "mermaid", "json", "all"], default="tree",
                        help="[SQL→AST] 輸出格式 (預設: tree)\n"
                             "  tree   : 輸出階層式文字樹狀圖 (包含類型推導)\n"
                             "  mermaid: 輸出可用於渲染圖表的 Mermaid.js 語法\n"
                             "  json   : 輸出原始 AST JSON 結構\n"
                             "  all    : 同時輸出以上三種")

    args = parser.parse_args()

    # ── AST → SQL 模式 ──────────────────────────────
    if args.ast or args.ast_file:
        json_str = args.ast
        if args.ast_file:
            try:
                with open(args.ast_file, "r", encoding="utf-8") as f:
                    json_str = f.read()
            except FileNotFoundError:
                print(f"❌ 錯誤：找不到 AST 檔案 '{args.ast_file}'", file=sys.stderr)
                sys.exit(1)
        try:
            sql_out = ASTReconstructor().from_json_str(json_str)
            print(sql_out)
        except Exception as e:
            print(f"\n💥 [AST→SQL 錯誤] {e}", file=sys.stderr)
            sys.exit(1)
        return

    # ── SQL → AST 模式 ──────────────────────────────
    sql = args.sql
    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                sql = f.read()
        except FileNotFoundError:
            print(f"❌ 錯誤：找不到 SQL 檔案 '{args.file}'", file=sys.stderr)
            sys.exit(1)

    runner = BirdEyeRunner()
    try:
        with open(args.csv, "r", encoding="utf-8") as f:
            runner.load_metadata_from_csv(f)
    except FileNotFoundError:
        print(f"⚠️ 警告：找不到元數據檔案 '{args.csv}'。將在無元數據狀態下執行解析 (這可能導致語意綁定失敗)。", file=sys.stderr)

    try:
        result = runner.run(sql)

        if args.format in ["tree", "all"]:
            if args.format == "all": print("\n=== AST Tree ===")
            print(result["tree"])

        if args.format in ["mermaid", "all"]:
            if args.format == "all": print("\n=== Mermaid Chart ===")
            print(result["mermaid"])

        if args.format in ["json", "all"]:
            if args.format == "all": print("\n=== AST JSON ===")
            print(result["json"])

    except (SyntaxError, ValueError) as e:
        print(f"\n❌ [語法錯誤 Syntax Error] {e}", file=sys.stderr)
        sys.exit(1)
    except SemanticError as e:
        print(f"\n🛡️ [資安/語意攔截 Semantic Error] {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 [未預期錯誤 System Error] {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
