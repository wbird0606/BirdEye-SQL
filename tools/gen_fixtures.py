#!/usr/bin/env python3
"""
gen_fixtures.py — 由 Python baseline 產生 Go conformance corpus。

架構：parent 每個 suite 開一個 resumable worker 子行程（有 timeout）。worker
把每筆 fixture 逐一 append+flush 到輸出檔；啟動時先讀已存在的 id 跳過。若 worker
因畸形輸入把 Python parser 卡死（見 KNOWN_DEVIATIONS A1）而逾時，parent 找出
第一個「尚未寫入」的案例，記為 error.category="hang"，再重跑 worker（會跳過
已完成 + 已標 hang 的），直到 worker 正常結束。因此整支工具對掛死免疫。

harvest 只從測試檔字串常數收割「看起來像 SQL」的字串，並排除自然語言
（去掉引號後仍含非 SQL 字元 / CJK / "..." 者視為 prose）。

用法：
    BIRDEYE_BASELINE=../birdeye_1150831 \\
      ../birdeye_1150831/.venv/Scripts/python tools/gen_fixtures.py
"""
from __future__ import annotations

import ast as pyast
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASELINE = Path(os.environ.get("BIRDEYE_BASELINE", REPO.parent / "birdeye_1150831")).resolve()
CSV_PATH = REPO / "testdata" / "output.csv"
OUT_DIR = REPO / "testdata" / "conformance"
EXTRA = REPO / "tools" / "corpus_extra.jsonl"

MODES = ("parse_only", "run", "run_multi")
MAX_SQL_LEN = 5000
SUITE_TIMEOUT = 150          # 秒；worker 正常跑完一個 suite 遠低於此
MAX_HANGS_PER_SUITE = 40     # 保險絲：一個 suite 標到這麼多 hang 就放棄重跑

SQL_RE = re.compile(
    r"\s*(WITH|SELECT|INSERT|UPDATE|DELETE|DECLARE|CREATE|DROP|ALTER|"
    r"MERGE|TRUNCATE|EXEC|EXECUTE|PRINT|SET|BULK|IF)\b",
    re.I,
)
_QUOTED = re.compile(r"'(?:[^']|'')*'")
# 引號外允許的字元：ASCII 英數、空白、SQL 標點。出現其他字元（破折號、CJK、
# 智慧引號、省略號…）即視為自然語言。
_NON_SQL = re.compile(r"[^0-9A-Za-z \t\r\n_@#.,;:()\[\]'\"*+/%&|^~=<>!?$-]")


# ── harvest ──────────────────────────────────────────────────────────────────

def looks_like_sql(s: str) -> bool:
    if not (0 < len(s) <= MAX_SQL_LEN) or not SQL_RE.match(s):
        return False
    return _NON_SQL.search(_QUOTED.sub("", s)) is None


def harvest_suite(suite: str) -> list[str]:
    path = BASELINE / "tests" / f"{suite}.py"
    try:
        tree = pyast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    seen: dict[str, None] = {}
    for node in pyast.walk(tree):
        if isinstance(node, pyast.Constant) and isinstance(node.value, str) and looks_like_sql(node.value):
            seen.setdefault(node.value, None)
    return list(seen)


def fixture_id(suite: str, sql: str, params, mode: str) -> str:
    payload = f"{mode}\x00{json.dumps(params, sort_keys=True)}\x00{sql}".encode()
    return f"{suite}:{hashlib.sha1(payload).hexdigest()[:12]}"


def suite_cases(suite: str) -> list[tuple[str, object, str]]:
    """該 suite 的正規案例順序：(sql, params, mode)。parent 與 worker 一致。"""
    return [(sql, None, mode) for sql in harvest_suite(suite) for mode in MODES]


def extra_cases() -> list[tuple[str, object, str]]:
    out: list[tuple[str, object, str]] = []
    if not EXTRA.exists():
        return out
    for line in EXTRA.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            item = json.loads(line)
            for mode in item.get("modes", ["run", "run_multi"]):
                out.append((item["sql"], item.get("params"), mode))
    return out


# ── worker：跑 pipeline ──────────────────────────────────────────────────────

_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        sys.path.insert(0, str(BASELINE))
        from birdeye.runner import BirdEyeRunner
        from birdeye.binder import SemanticError
        from birdeye.intent_extractor import IntentExtractor
        from birdeye.reconstructor import ASTReconstructor
        _ENGINE = (BirdEyeRunner, SemanticError, IntentExtractor, ASTReconstructor,
                   CSV_PATH.read_text(encoding="utf-8"))
    return _ENGINE


def _categorize(exc, SemanticError) -> str:
    if isinstance(exc, SemanticError):
        return "semantic"
    if isinstance(exc, SyntaxError):
        return "syntax"
    if isinstance(exc, ValueError):
        return "value"
    return "system"


def _stage(fn):
    """跑一個 pipeline 階段，回傳 {"ok":..., "value":..., "error":...}。"""
    _, SemanticError, *_ = _engine()
    try:
        return {"ok": True, "value": fn(), "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "value": None,
                "error": {"category": _categorize(exc, SemanticError),
                          "type": type(exc).__name__, "message": str(exc)}}


def run_case(suite: str, sql: str, params, mode: str) -> dict:
    """逐階段記錄：parse(+serialize) / tree / mermaid / intents / reconstructed。
    下游階段只在 parse 成功時才嘗試。"""
    BirdEyeRunner, SemanticError, IntentExtractor, ASTReconstructor, csv_text = _engine()
    r = BirdEyeRunner()
    r.load_metadata_from_csv(io.StringIO(csv_text))
    rec: dict = {"id": fixture_id(suite, sql, params, mode), "suite": suite,
                 "mode": mode, "sql": sql, "params": params,
                 "binder_ran": mode != "parse_only"}

    state: dict = {}

    def do_parse():
        if mode == "run":
            out = r.run(sql, params=params)
            return out["json"], out["tree"], out["mermaid"]
        if mode == "run_multi":
            out = r.run_multi(sql, params=params)
            return out["json"], out["tree"], out["mermaid"]
        node = r.parse_only(sql, params=params)["ast"]
        aj = r.serializer.to_json(node)
        return aj, r.visualizer.dump(node), r.exporter.export(json.loads(aj))

    parse = _stage(do_parse)
    if parse["ok"]:
        aj, tree, mermaid = parse["value"]
        state["ast_json"] = aj
        rec["parse"] = {"ok": True, "ast_json": aj, "error": None}
        rec["tree"] = {"ok": True, "value": tree, "error": None}
        rec["mermaid"] = {"ok": True, "value": mermaid, "error": None}
        rec["intents"] = _stage(lambda: IntentExtractor().expand_star_intents(
            IntentExtractor().extract(json.loads(aj)), r))
        rec["reconstructed"] = _stage(lambda: ASTReconstructor().from_json_str(aj))
    else:
        rec["parse"] = {"ok": False, "ast_json": None, "error": parse["error"]}
        for k in ("tree", "mermaid", "intents", "reconstructed"):
            rec[k] = {"ok": False, "value": None, "error": None}

    return rec


def _existing_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            ids.add(json.loads(line)["id"])
    return ids


def worker(kind: str, out_path: str) -> None:
    """kind 為 suite 名稱或字面 '_extra'。append 模式，跳過已寫入的 id。"""
    path = Path(out_path)
    done = _existing_ids(path)
    cases = extra_cases() if kind == "_extra" else suite_cases(kind)
    suite = kind
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        for sql, params, mode in cases:
            if fixture_id(suite, sql, params, mode) in done:
                continue
            f.write(json.dumps(run_case(suite, sql, params, mode), ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()


# ── parent ───────────────────────────────────────────────────────────────────

def _hang_record(suite: str, sql: str, params, mode: str) -> dict:
    hang_err = {"category": "hang", "type": "NonTermination",
                "message": f"Python pipeline did not terminate within {SUITE_TIMEOUT}s"}
    rec = {"id": fixture_id(suite, sql, params, mode), "suite": suite, "mode": mode,
           "sql": sql, "params": params, "binder_ran": mode != "parse_only",
           "parse": {"ok": False, "ast_json": None, "error": hang_err}}
    for k in ("tree", "mermaid", "intents", "reconstructed"):
        rec[k] = {"ok": False, "value": None, "error": None}
    return rec


def gen_file(kind: str, manifest: dict) -> None:
    cases = extra_cases() if kind == "_extra" else suite_cases(kind)
    if not cases:
        return
    name = f"{kind}.jsonl"
    out = OUT_DIR / name
    out.unlink(missing_ok=True)
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    hangs = 0

    while True:
        try:
            subprocess.run([sys.executable, __file__, "--worker", kind, str(out)],
                           timeout=SUITE_TIMEOUT, env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", check=False)
            break  # worker 正常結束
        except subprocess.TimeoutExpired:
            done = _existing_ids(out)
            stuck = next(((s, p, m) for s, p, m in cases
                          if fixture_id(kind, s, p, m) not in done), None)
            if stuck is None or hangs >= MAX_HANGS_PER_SUITE:
                break
            with open(out, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(_hang_record(kind, *stuck), ensure_ascii=False, sort_keys=True) + "\n")
            hangs += 1
            sys.stderr.write(f"[hang] {kind}: {stuck[2]} {stuck[0][:60]!r}\n")

    records = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    records.sort(key=lambda r: r["id"])
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    def cat(r):
        return (r.get("parse", {}).get("error") or {}).get("category")

    ok = sum(1 for r in records if r["parse"]["ok"])
    manifest["files"][name] = {
        "cases": len(records), "parse_ok": ok, "parse_err": len(records) - ok,
        "hang": sum(1 for r in records if cat(r) == "hang"),
    }
    print(f"  {kind}: {len(records)}")


def gen_tokens(suites: list[str], manifest: dict) -> None:
    """_tokens.jsonl：每個 harvested SQL 的 Python token 序列，供 Go lexer conformance。"""
    sys.path.insert(0, str(BASELINE))
    from birdeye.lexer import Lexer

    seen: dict[str, None] = {}
    for suite in suites:
        for sql in harvest_suite(suite):
            seen.setdefault(sql, None)
    for sql, _p, _m in extra_cases():
        seen.setdefault(sql, None)

    records = []
    for sql in sorted(seen):
        rec: dict = {"sql": sql}
        try:
            rec["tokens"] = [[t.type.name, t.value] for t in Lexer(sql).tokenize()]
        except Exception as exc:  # noqa: BLE001
            rec["tokens"] = None
            rec["error"] = {"category": "value" if isinstance(exc, ValueError) else "system",
                            "type": type(exc).__name__, "message": str(exc)}
        records.append(rec)

    with open(OUT_DIR / "_tokens.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    manifest["files"]["_tokens.jsonl"] = {
        "cases": len(records),
        "parse_ok": sum(1 for r in records if r.get("tokens") is not None),
        "parse_err": sum(1 for r in records if r.get("tokens") is None), "hang": 0}
    print(f"  _tokens: {len(records)}")


def baseline_commit() -> str:
    head = (BASELINE / ".git" / "HEAD").read_text(encoding="utf-8").strip()
    if head.startswith("ref: "):
        return (BASELINE / ".git" / head[5:]).read_text(encoding="utf-8").strip()[:12]
    return head[:12]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUT_DIR.glob("*.jsonl"):
        stale.unlink()
    for stale in Path(tempfile.gettempdir()).glob("birdeye_fx_*"):
        stale.unlink(missing_ok=True)

    manifest: dict = {"baseline_commit": baseline_commit(), "files": {},
                      "totals": {"cases": 0, "parse_ok": 0, "parse_err": 0, "hang": 0}}

    suites = sorted(p.stem for p in (BASELINE / "tests").glob("test_*.py")
                    if p.stem != "test_perf_benchmark")
    for suite in suites:
        gen_file(suite, manifest)
    gen_file("_extra", manifest)
    gen_tokens(suites, manifest)

    for info in manifest["files"].values():
        for k in ("cases", "parse_ok", "parse_err", "hang"):
            manifest["totals"][k] += info[k]
    with open(OUT_DIR / "_manifest.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    t = manifest["totals"]
    print(f"baseline {manifest['baseline_commit']}  files={len(manifest['files'])}  "
          f"cases={t['cases']}  parse_ok={t['parse_ok']}  parse_err={t['parse_err']}  hang={t['hang']}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--worker"]:
        worker(sys.argv[2], sys.argv[3])
    else:
        main()
