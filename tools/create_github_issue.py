"""建立 GitHub issue 報告 clause coverage 統計結果"""
import json
import subprocess
from pathlib import Path
from datetime import datetime


def run_cmd(cmd):
    """執行命令並返回輸出"""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip()


def main():
    # 讀取詳細報告
    detailed_path = Path("clause_coverage_detailed.json")
    with open(detailed_path) as f:
        data = json.load(f)
    
    summary = data["summary"]
    only_true = data["only_true_clauses"][:15]  # Top 15
    only_false = data["only_false_clauses"][:15]  # Top 15
    
    # 準備 issue 內容
    issue_title = "[Coverage] 2,746 個 Clause 中 661 個未完全覆蓋 (75% coverage)"
    
    issue_body = f"""## 📊 Clause Coverage 分析報告

根據專案範圍內的自動化 Clause-Level Instrumentation，識別出現有測試套件之覆蓋缺口。

### 📈 覆蓋率統計

- **總 Clause 數**: {summary['total']:,}
- **完全覆蓋** (true > 0 且 false > 0): {summary['fully_covered']:,} ({summary['coverage_percentage']}%)
- **缺少 False 路徑** (true > 0, false = 0): {summary['only_true']}
- **缺少 True 路徑** (true = 0, false > 0): {summary['only_false']}
- **未曾執行**: {summary['never_hit']}

**未完全覆蓋的 Clause 總數**: {summary['only_true'] + summary['only_false']} (25%)

---

### 🎯 最需改進的檔案 (優先順序)

根據未完全覆蓋的 Clause 數量排序：

1. **birdeye/parser.py** - 182 個部分覆蓋 clause (關鍵: SQL 解析邏輯)
2. **birdeye/binder.py** - 173 個部分覆蓋 clause (關鍵: 語義分析)
3. **birdeye/intent_extractor.py** - 103 個部分覆蓋 clause
4. **birdeye/reconstructor.py** - 70 個部分覆蓋 clause (65% 覆蓋率)
5. **web/app.py** - 27 個部分覆蓋 clause ⚠️ **最低覆蓋率 (10%)**

---

### 🔴 高優先級缺口 (已執行但缺少分支)

#### 缺少 False 路徑的高頻 Clause (Top 10)
- 需要新增測試用例使這些條件被評估為 False

|檔案位置|True 次數|建議改進|
|-------|--------|-------|
| parser.py:37:4,8 | 101,001x | 需要測試「並非空值」的情況 |
| parser.py:47:12,15 | 6,951x | 語法異常或邊界情況|
| parser.py:775,777,781 | 3.6-5k x | 解析器異常路徑|
| registry.py:189:18 | 2,939x | 元資料查詢邊界情況|

#### 缺少 True 路徑的高頻 Clause (Top 10)
- 需要新增測試用例使這些條件被評估為 True

|檔案位置|False 次數|建議改進|
|-------|---------|-------|
| lexer.py:270:45-54 | 4,744x | Token 轉換邊界情況|
| registry.py:184:14,17 | 2,939x | 函數型別推斷邊界|
| ast.py:94:2 | 2,382x | AST 節點驗證邊界|
| parser.py:71:30,34 | 1,054x | 語法錯誤恢復路徑|

---

### 📝 建議改進方向

1. **Parser 邏輯** - 強化邊界情況 (NULL handling, 複雜表達式, SET 操作符)
2. **Binder 語義** - 增加型別驗證邊界測試 (不兼容型別, NULL 傳播)
3. **Web API** - 從目前 10% 提升至 80%+ (缺少端點驗證、錯誤處理測試)
4. **Reconstructor** - 各種 AST 結構的重建驗證

---

### 🔧 技術細節

- **覆蓋測量方式**: AST-based 動態 Instrumentation
-  **測試框架**: pytest (1,075 個測試)
- **執行環境**: Python 3.10
- **報告檔案**: `clause_coverage_detailed.json` (包含每個 clause 的詳細統計)
- **分析工具**: `tools/analyze_clause_coverage.py`

---

### 📌 下一步行動

- [ ] 檢視 `tests/` 目錄下各個測試套件
- [ ] 針對清單中的高優先級 clause 新增測試用例
- [ ] 重新執行 instrumentation 驗證改進結果
- [ ] 設置目標: 達到 90%+ clause coverage

---

**報告產生時間**: {datetime.now().isoformat()}
**報告來源**: `clause_coverage_detailed.json`, `tools/analyze_clause_coverage.py`
"""

    # 顯示內容預覽
    print("=" * 80)
    print("GitHub Issue 預覽")
    print("=" * 80)
    print(f"\nIssue 標題:\n{issue_title}\n")
    print(f"\nIssue 內容:\n{issue_body}\n")
    
    # 儲存為本地檔案供查閱
    issue_file = Path("github_issue_draft.md")
    with open(issue_file, "w", encoding="utf-8") as f:
        f.write(f"# {issue_title}\n\n")
        f.write(issue_body)
    print(f"✅ Issue 草稿已儲存至: {issue_file}")
    
    return issue_title, issue_body


if __name__ == "__main__":
    title, body = main()
