"""使用 gh CLI 直接建立 GitHub issue"""
import subprocess
from pathlib import Path


def main():
    draft_file = Path("github_issue_draft.md")
    
    if not draft_file.exists():
        print("❌ github_issue_draft.md 不存在")
        return
    
    # 讀取草稿
    with open(draft_file, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 提取標題 (第一行 # 後的內容)
    lines = content.split("\n")
    title = None
    body_start = 0
    
    for i, line in enumerate(lines):
        if line.startswith("# "):
            title = line[2:].strip()
            body_start = i + 1
            break
    
    if not title:
        print("❌ 找不到 issue 標題")
        return
    
    # 提取 body (移除空行)
    body = "\n".join(lines[body_start:]).strip()
    
    print(f"📝 Issue 標題：{title}\n")
    print(f"📄 Issue 內容長度：{len(body)} 字元\n")
    
    # 使用 gh CLI 建立 issue
    try:
        cmd = [
            "gh",
            "issue",
            "create",
            "--title", title,
            "--body", body
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("✅ Issue 已成功建立！")
        print(f"\n{result.stdout}")
        
        # 保存建立記錄
        record_file = Path("issue_created.log")
        with open(record_file, "w", encoding="utf-8") as f:
            f.write(f"建立時間：{result.stdout}\n")
            f.write(f"標題：{title}\n")
        
    except subprocess.CalledProcessError as e:
        print(f"❌ gh 命令執行失敗：{e.stderr}")
        print("\n💡 提示：確認已安裝 GitHub CLI (gh) 並已登入")
        print("   安裝: https://cli.github.com/")
        print("   登入: gh auth login")
        return
    except FileNotFoundError:
        print("❌ 找不到 gh 命令")
        print("💡 提示：請先安裝 GitHub CLI")
        print("   https://cli.github.com/")
        return


if __name__ == "__main__":
    main()
