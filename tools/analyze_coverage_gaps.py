"""分析未覆蓋 clause 並生成測試建議"""
import json
from pathlib import Path
import re


def extract_code_context(file_path, line_num, context_lines=3):
    """提取程式碼的上下文"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        start = max(0, line_num - context_lines - 1)
        end = min(len(lines), line_num + context_lines)
        
        code = ''.join(lines[start:end])
        actual_line = lines[line_num - 1] if line_num <= len(lines) else "N/A"
        
        return code, actual_line.strip()
    except Exception as e:
        return str(e), "N/A"


def analyze_top_gaps(detailed_json):
    """分析最高優先級的覆蓋缺口"""
    with open(detailed_json) as f:
        data = json.load(f)
    
    print("=" * 100)
    print("🔴 高優先級覆蓋缺口分析 (Top 20 最高頻執行)")
    print("=" * 100)
    
    # 只看缺少 False 的 clause (最常執行)
    only_true = data["only_true_clauses"][:20]
    
    test_recommendations = []
    
    for item in only_true:
        clause_id = item["id"]
        true_count = item["true_count"]
        
        # 解析 clause ID: 格式為 "file\\line:col"
        # 實際格式更複雜，例如 "birdeye\\parser.py:37:4"
        parts = clause_id.replace("\\", "/").split(":")
        if len(parts) >= 2:
            file_part = parts[0]
            line_num = int(parts[1])
            
            # 構建完整路徑
            file_path = Path(f"d:/1150322/birdeye/{file_part}")
            
            code, actual_line = extract_code_context(file_path, line_num)
            
            recommendation = {
                "clause_id": clause_id,
                "true_count": true_count,
                "file": file_part,
                "line": line_num,
                "code": actual_line,
                "issue": "缺少 False 路徑 - 需要讓條件評估為 False"
            }
            test_recommendations.append(recommendation)
            
            print(f"\n📍 {clause_id} (執行 {true_count}x，皆為 True)")
            print(f"   程式碼: {actual_line}")
            print(f"   問題: 需要測試案例使此條件為 False")
            print(f"   上下文:\n{code}")
    
    return test_recommendations


def main():
    detailed_json = Path("clause_coverage_detailed.json")
    
    if not detailed_json.exists():
        print("❌ clause_coverage_detailed.json 不存在")
        return
    
    recommendations = analyze_top_gaps(detailed_json)
    
    # 儲存建議為 JSON
    output = Path("test_recommendations.json")
    with open(output, "w", encoding="utf-8") as f:
        json.dump(recommendations, f, indent=2, ensure_ascii=False)
    
    print(f"\n\n✅ 測試建議已儲存至: {output}")


if __name__ == "__main__":
    main()
