"""分析 clause_coverage_report.json，列出未被完全覆蓋的 clause 並產生摘要。"""
import json
from pathlib import Path
from collections import defaultdict


def main():
    report_path = Path("clause_coverage_report.json")
    if not report_path.exists():
        print("No clause_coverage_report.json found")
        return

    with open(report_path) as f:
        data = json.load(f)

    total = data["total_clauses"]
    clauses = data["clauses"]

    # Classify coverage status
    fully_covered = 0  # both true and false > 0
    only_true = []     # true > 0, false == 0
    only_false = []    # true == 0, false > 0
    never_hit = []     # both == 0

    for clause_id, counts in clauses.items():
        t = counts.get("true", 0)
        f = counts.get("false", 0)

        if t > 0 and f > 0:
            fully_covered += 1
        elif t > 0 and f == 0:
            only_true.append((clause_id, t))
        elif t == 0 and f > 0:
            only_false.append((clause_id, f))
        else:
            never_hit.append(clause_id)

    # Per-file summary
    by_file = defaultdict(lambda: {"total": 0, "covered": 0, "partial": 0, "uncovered": 0})
    for clause_id in clauses:
        file_part = clause_id.split(":")[0]
        by_file[file_part]["total"] += 1

        t = clauses[clause_id].get("true", 0)
        f = clauses[clause_id].get("false", 0)
        if t > 0 and f > 0:
            by_file[file_part]["covered"] += 1
        elif (t > 0 or f > 0):
            by_file[file_part]["partial"] += 1
        else:
            by_file[file_part]["uncovered"] += 1

    # Output summary
    print(f"\n=== Clause Coverage Summary ===")
    print(f"Total clauses: {total}")
    print(f"Fully covered: {fully_covered} ({100*fully_covered//total}%)")
    print(f"Only True (missing False): {len(only_true)}")
    print(f"Only False (missing True): {len(only_false)}")
    print(f"Never hit: {len(never_hit)}")
    print(f"Coverage: {100*fully_covered//total}% ({fully_covered}/{total})")

    print(f"\n=== Per-File Summary (Top 20 uncovered) ===")
    sorted_files = sorted(by_file.items(), key=lambda x: x[1]["partial"] + x[1]["uncovered"], reverse=True)
    for file, stats in sorted_files[:20]:
        print(f"{file}: {stats['covered']}/{stats['total']} covered, {stats['partial']} partial, {stats['uncovered']} uncovered")

    print(f"\n=== Top 30 Clauses Missing FALSE ===")
    for clause_id, true_count in sorted(only_true, key=lambda x: -x[1])[:30]:
        print(f"  {clause_id}: true={true_count}")

    print(f"\n=== Top 30 Clauses Missing TRUE ===")
    for clause_id, false_count in sorted(only_false, key=lambda x: -x[1])[:30]:
        print(f"  {clause_id}: false={false_count}")

    if never_hit:
        print(f"\n=== Clauses Never Hit ({len(never_hit)} total) ===")
        for clause_id in never_hit[:20]:
            print(f"  {clause_id}")
        if len(never_hit) > 20:
            print(f"  ... and {len(never_hit) - 20} more")

    # Write detailed report
    detailed_path = Path("clause_coverage_detailed.json")
    detailed_data = {
        "summary": {
            "total": total,
            "fully_covered": fully_covered,
            "coverage_percentage": 100 * fully_covered // total,
            "only_true": len(only_true),
            "only_false": len(only_false),
            "never_hit": len(never_hit),
        },
        "only_true_clauses": [{"id": cid, "true_count": cnt} for cid, cnt in sorted(only_true, key=lambda x: -x[1])],
        "only_false_clauses": [{"id": cid, "false_count": cnt} for cid, cnt in sorted(only_false, key=lambda x: -x[1])],
        "never_hit_clauses": never_hit,
        "per_file_summary": {k: v for k, v in sorted(by_file.items())},
    }
    with open(detailed_path, "w") as f:
        json.dump(detailed_data, f, indent=2)
    print(f"\nDetailed report written to {detailed_path}")


if __name__ == "__main__":
    main()
