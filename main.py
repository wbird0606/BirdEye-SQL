import argparse
import sys
import json
from birdeye.runner import BirdEyeRunner
from birdeye.binder import SemanticError

def main():
    parser = argparse.ArgumentParser(
        description="🦅 BirdEye-SQL: Semantic-Aware & Zero-Trust SQL Parser",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    # 輸入來源
    group_input = parser.add_mutually_exclusive_group(required=True)
    group_input.add_argument("--sql", type=str, help="直接輸入 SQL 查詢字串")
    group_input.add_argument("--file", type=str, help="從檔案讀取 SQL 查詢")
    
    # 參數設定
    parser.add_argument("--csv", type=str, default="data/output.csv", help="指定元數據 CSV 檔案路徑 (預設: data/output.csv)")
    parser.add_argument("--format", type=str, choices=["tree", "mermaid", "json", "all"], default="tree", 
                        help="輸出格式 (預設: tree)\n"
                             "  tree   : 輸出階層式文字樹狀圖 (包含類型推導)\n"
                             "  mermaid: 輸出可用於渲染圖表的 Mermaid.js 語法\n"
                             "  json   : 輸出原始 AST JSON 結構\n"
                             "  all    : 同時輸出以上三種")
    
    args = parser.parse_args()

    # 1. 取得 SQL 字串
    sql = args.sql
    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                sql = f.read()
        except FileNotFoundError:
            print(f"❌ 錯誤：找不到 SQL 檔案 '{args.file}'", file=sys.stderr)
            sys.exit(1)

    # 2. 初始化 Runner 與元數據
    runner = BirdEyeRunner()
    try:
        with open(args.csv, "r", encoding="utf-8") as f:
            runner.load_metadata_from_csv(f)
    except FileNotFoundError:
        print(f"⚠️ 警告：找不到元數據檔案 '{args.csv}'。將在無元數據狀態下執行解析 (這可能導致語意綁定失敗)。", file=sys.stderr)

    # 3. 執行解析與輸出
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
