"""掃描專案內 Python 檔案，找出複合布林式中的原子 clause 並輸出 JSON 列表。

用法：
    python -m birdeye.tools.clause_scanner
會在專案根目錄輸出 `.clause_report.json`。
"""
import ast
import json
import os
from pathlib import Path


def extract_clauses_from_node(node, source):
    clauses = []

    def add(expr_node):
        try:
            seg = ast.get_source_segment(source, expr_node)
        except Exception:
            seg = None
        if seg is None:
            seg = ast.dump(expr_node)
        clauses.append(seg.strip())

    for n in ast.walk(node):
        if isinstance(n, ast.BoolOp):
            # each value is an atomic clause (may be nested)
            for v in n.values:
                add(v)
        elif isinstance(n, ast.Compare):
            # treat each comparator pair as clause: left op comp
            # we will capture the whole compare as one clause
            add(n)
        elif isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
            add(n.operand)
        elif isinstance(n, (ast.IfExp,)):
            add(n.test)
        elif isinstance(n, (ast.If, ast.While, ast.Assert)):
            add(n.test)

    # de-dup while preserving order
    seen = set()
    out = []
    for c in clauses:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def scan_paths(paths):
    report = []
    for p in paths:
        for filepath in Path(p).rglob('*.py'):
            # skip virtual envs or hidden folders
            if any(part.startswith('.') or part == 'venv' or part == '__pycache__' for part in filepath.parts):
                continue
            try:
                src = filepath.read_text(encoding='utf-8')
            except Exception:
                continue
            try:
                tree = ast.parse(src)
            except Exception:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.If, ast.While, ast.Assert, ast.IfExp, ast.BoolOp, ast.Compare, ast.UnaryOp)):
                    lineno = getattr(node, 'lineno', None)
                    clauses = extract_clauses_from_node(node, src)
                    if clauses:
                        report.append({
                            'file': str(filepath).replace('\\', '/'),
                            'lineno': lineno,
                            'node_type': type(node).__name__,
                            'clauses': clauses,
                        })
    return report


def main():
    roots = ['birdeye', 'web']
    existing = [r for r in roots if os.path.isdir(r)]
    if not existing:
        print('No target directories found (birdeye/web)')
        return
    report = scan_paths(existing)
    out_path = Path('.clause_report.json')
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f'Wrote {out_path} with {len(report)} clause locations')


if __name__ == '__main__':
    main()
