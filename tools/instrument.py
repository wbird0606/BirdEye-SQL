"""Instrument project Python files to wrap Boolean clauses with clause_probe calls.

Usage (from repo root):
  python tools/instrument.py

It will:
  - create `.instrumented/` copy of project
  - rewrite condition expressions to call `clause_probe(id, lambda: <expr>)`
  - run `pytest` inside `.instrumented/`
  - collect `.clause_probe_log.jsonl` and produce `clause_coverage_report.json`
"""
import ast
import json
import os
import shutil
import subprocess
from pathlib import Path
import importlib.util

# load scan_paths from tools/clause_scanner.py
spec = importlib.util.spec_from_file_location('clause_scanner', Path('tools') / 'clause_scanner.py')
cl_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cl_mod)
scan_paths = cl_mod.scan_paths


class ClauseInstrumenter(ast.NodeTransformer):
    def __init__(self, file_map, base_relpath):
        super().__init__()
        self.file_map = file_map
        self.base = base_relpath
        self.counter = 0

    def _make_probe_call(self, expr_node, cid):
        # produce: clause_probe('cid', lambda: <expr>)
        lambda_node = ast.Lambda(args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=expr_node)
        call = ast.Call(func=ast.Name(id='clause_probe', ctx=ast.Load()), args=[ast.Constant(value=cid), lambda_node], keywords=[])
        return ast.copy_location(call, expr_node)

    def _wrap_expr(self, node, lineno):
        self.counter += 1
        cid = f"{self.base}:{lineno}:{self.counter}"
        return self._make_probe_call(node, cid)

    def visit_If(self, node):
        node.test = self._wrap_expr(self.visit(node.test), getattr(node, 'lineno', 0))
        self.generic_visit(node)
        return node

    def visit_While(self, node):
        node.test = self._wrap_expr(self.visit(node.test), getattr(node, 'lineno', 0))
        self.generic_visit(node)
        return node

    def visit_Assert(self, node):
        node.test = self._wrap_expr(self.visit(node.test), getattr(node, 'lineno', 0))
        self.generic_visit(node)
        return node

    def visit_IfExp(self, node):
        node.test = self._wrap_expr(self.visit(node.test), getattr(node, 'lineno', 0))
        self.generic_visit(node)
        return node

    def visit_BoolOp(self, node):
        # wrap each value
        new_values = []
        for v in node.values:
            new_v = self._wrap_expr(self.visit(v), getattr(node, 'lineno', 0))
            new_values.append(new_v)
        node.values = new_values
        return node

    def visit_Compare(self, node):
        # wrap entire compare expression
        new = self._wrap_expr(node, getattr(node, 'lineno', 0))
        return new


def instrument_project():
    root = Path('.').resolve()
    inst = root / '.instrumented'
    if inst.exists():
        shutil.rmtree(inst)
    shutil.copytree(root, inst, ignore=shutil.ignore_patterns('.git', '.instrumented', 'coverage_clause_html', '__pycache__'))
    # ensure a top-level clause_probe.py exists in the instrumented root for simple import
    src_probe = Path('tools') / 'clause_probe.py'
    if src_probe.exists():
        shutil.copy(src_probe, inst / 'clause_probe.py')

    # find python files under birdeye/ and web/
    targets = [p for p in ('birdeye', 'web') if (inst / p).exists()]
    file_map = {}
    for p in targets:
        for filepath in (inst / p).rglob('*.py'):
            file_map[str(filepath.relative_to(inst))] = filepath

    # instrument each file
    for rel, full in file_map.items():
        src = full.read_text(encoding='utf-8')
        try:
            tree = ast.parse(src)
        except Exception:
            continue
        instr = ClauseInstrumenter(file_map, rel)
        new_tree = instr.visit(tree)
        ast.fix_missing_locations(new_tree)
        # ensure import of clause_probe at top
        import_node = ast.parse('from clause_probe import clause_probe')
        if not any(isinstance(n, ast.ImportFrom) and n.module == 'clause_probe' for n in new_tree.body):
            new_tree.body[:0] = import_node.body
        try:
            new_src = ast.unparse(new_tree)
        except Exception as e:
            try:
                import astor as _astor

                new_src = _astor.to_source(new_tree)
            except Exception:
                # if we cannot unparse, skip instrumentation for this file
                print(f"Warning: cannot unparse {full}, skipping instrumentation: {e}")
                continue
        full.write_text(new_src, encoding='utf-8')

    # reset probe log
    log_path = inst / '.clause_probe_log.jsonl'
    try:
        log_path.unlink()
    except Exception:
        pass

    # run tests inside instrumented dir
    print('Running pytest in instrumented copy...')
    proc = subprocess.run(['python', '-m', 'pytest', '-q', '--disable-warnings', '--maxfail=1'], cwd=str(inst))

    # aggregate results
    results = {}
    if log_path.exists():
        for line in log_path.read_text(encoding='utf-8').splitlines():
            try:
                obj = json.loads(line)
            except Exception:
                continue
            cid = obj.get('id')
            val = bool(obj.get('value'))
            if cid not in results:
                results[cid] = {'true': 0, 'false': 0}
            if val:
                results[cid]['true'] += 1
            else:
                results[cid]['false'] += 1

    # write report
    rep = {'total_clauses': len(results), 'clauses': results}
    Path('clause_coverage_report.json').write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding='utf-8')
    print('Wrote clause_coverage_report.json')
    return proc.returncode


if __name__ == '__main__':
    rc = instrument_project()
    raise SystemExit(rc)
