import argparse
import sys
import json
import re
from birdeye.runner import BirdEyeRunner
from birdeye.binder import SemanticError
from birdeye.reconstructor import ASTReconstructor


class _RelaxedParserError(ValueError):
    pass


def _to_scalar(token):
    low = token.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low == "null" or low == "none":
        return None
    if re.fullmatch(r"[+-]?\d+", token):
        return int(token)
    if re.fullmatch(r"[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?", token):
        return float(token)
    return token


def _tokenize_relaxed(raw):
    tokens = []
    i = 0
    n = len(raw)
    punct = "{}[]:,"

    while i < n:
        ch = raw[i]
        if ch.isspace():
            i += 1
            continue

        if ch in punct:
            tokens.append((ch, ch))
            i += 1
            continue

        if ch in ('"', "'"):
            quote = ch
            i += 1
            buf = []
            while i < n:
                c = raw[i]
                if c == "\\" and i + 1 < n:
                    buf.append(raw[i + 1])
                    i += 2
                    continue
                if c == quote:
                    i += 1
                    break
                buf.append(c)
                i += 1
            else:
                raise _RelaxedParserError("Unterminated quoted string")
            tokens.append(("STRING", "".join(buf)))
            continue

        j = i
        while j < n and (not raw[j].isspace()) and raw[j] not in punct:
            j += 1
        tokens.append(("BARE", raw[i:j]))
        i = j

    return tokens


def _parse_relaxed(raw):
    tokens = _tokenize_relaxed(raw)
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else (None, None)

    def consume(expected=None):
        nonlocal pos
        tok = peek()
        if expected is not None and tok[0] != expected:
            raise _RelaxedParserError(f"Expected token {expected}, got {tok[0]}")
        pos += 1
        return tok

    def parse_value():
        kind, val = peek()
        if kind == "{":
            consume("{")
            obj = {}
            if peek()[0] == "}":
                consume("}")
                return obj
            while True:
                k_kind, k_val = peek()
                if k_kind not in ("STRING", "BARE"):
                    raise _RelaxedParserError("Object key must be string or bare identifier")
                consume()
                consume(":")
                obj[str(k_val)] = parse_value()
                if peek()[0] == ",":
                    consume(",")
                    continue
                consume("}")
                return obj

        if kind == "[":
            consume("[")
            arr = []
            if peek()[0] == "]":
                consume("]")
                return arr
            while True:
                arr.append(parse_value())
                if peek()[0] == ",":
                    consume(",")
                    continue
                consume("]")
                return arr

        if kind == "STRING":
            consume("STRING")
            return val

        if kind == "BARE":
            consume("BARE")
            return _to_scalar(val)

        raise _RelaxedParserError("Invalid value token")

    parsed = parse_value()
    if pos != len(tokens):
        raise _RelaxedParserError("Unexpected trailing tokens")
    return parsed


def _parse_cli_params(raw):
    # 1) strict JSON first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 2) tolerate accidental wrapping quotes
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        inner = raw[1:-1]
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            pass

    # 3) PowerShell-relaxed object/array syntax (e.g. {@city: Taipei})
    return _parse_relaxed(raw)

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
    
    # 參數選項（可選）
    params_group = parser.add_mutually_exclusive_group()
    params_group.add_argument("--params", type=str, help="[SQL→AST] 參數 (JSON 格式)\n"
                             "  命名：{\"@city\": \"Taipei\", \"@age\": 30}\n"
                             "  位置：[\"Taipei\", 30]")
    params_group.add_argument("--params-file", type=str, dest="params_file", help="[SQL→AST] 從檔案讀取參數 (JSON 格式)")

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

    # 解析參數
    params = None
    if args.params:
        try:
            params = _parse_cli_params(args.params)
        except Exception as e:
            print(f"❌ 錯誤：--params 解析失敗: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.params_file:
        try:
            with open(args.params_file, "r", encoding="utf-8") as f:
                params = json.load(f)
        except FileNotFoundError:
            print(f"❌ 錯誤：找不到參數檔案 '{args.params_file}'", file=sys.stderr)
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"❌ 錯誤：參數檔案 JSON 解析失敗: {e}", file=sys.stderr)
            sys.exit(1)

    try:
        result = runner.run(sql, params=params)

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
