#!/usr/bin/env python3
"""
フォームファイル一括更新スクリプト
form1.html～form19.htmlのlocalStorage管理をユーザーIDベースに変更
"""

import re
import os
from pathlib import Path

def update_form_file(filepath, form_number):
    """
    フォームファイルを更新
    
    Args:
        filepath: ファイルパス
        form_number: フォーム番号（1～19）
    """
    print(f"\n処理中: {filepath}")
    
    if not os.path.exists(filepath):
        print(f"  ⚠ ファイルが見つかりません: {filepath}")
        return False
    
    # ファイルを読み込み
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    changes_made = []
    
    # 1. survey-common.jsの読み込みを追加（まだ無い場合）
    if 'survey-common.js' not in content:
        # </head>の直前に追加
        if '</head>' in content:
            content = content.replace('</head>', '  <script src="survey-common.js"></script>\n</head>')
            changes_made.append("survey-common.jsの読み込みを追加")
    
    # 2. ダブルクォートを使用したlocalStorageの保存処理を置換
    # パターン: localStorage.setItem("surveyData_formN", JSON.stringify(data));
    pattern1 = rf'localStorage\.setItem\("surveyData_form{form_number}",\s*JSON\.stringify\(data\)\)'
    replacement1 = f'localStorage.setItem(getFormStorageKey({form_number}), JSON.stringify(data))'
    if re.search(pattern1, content):
        content = re.sub(pattern1, replacement1, content)
        changes_made.append(f"保存処理を置換（パターン1）")
    
    # 3. ダブルクォートを使用したlocalStorageの取得処理を置換
    # パターン: localStorage.getItem("surveyData_formN")
    pattern2 = rf'localStorage\.getItem\("surveyData_form{form_number}"\)'
    replacement2 = f'localStorage.getItem(getFormStorageKey({form_number}))'
    if re.search(pattern2, content):
        content = re.sub(pattern2, replacement2, content)
        changes_made.append(f"取得処理を置換（パターン2）")
    
    # 4. バッククォートとテンプレートリテラルを使用している場合
    # パターン: localStorage.setItem(`surveyData_form${formNumber}`, JSON.stringify(data))
    pattern3 = r'localStorage\.setItem\(`surveyData_form\$\{formNumber\}`,\s*JSON\.stringify\(data\)\)'
    replacement3 = 'localStorage.setItem(getFormStorageKey(formNumber), JSON.stringify(data))'
    if re.search(pattern3, content):
        content = re.sub(pattern3, replacement3, content)
        changes_made.append(f"保存処理を置換（パターン3）")
    
    # パターン: localStorage.getItem(`surveyData_form${formNumber}`)
    pattern4 = r'localStorage\.getItem\(`surveyData_form\$\{formNumber\}`\)'
    replacement4 = 'localStorage.getItem(getFormStorageKey(formNumber))'
    if re.search(pattern4, content):
        content = re.sub(pattern4, replacement4, content)
        changes_made.append(f"取得処理を置換（パターン4）")
    
    # 5. 汎用パターン（任意のフォーム番号）
    # パターン: localStorage.setItem("surveyData_form1", ...)
    pattern5 = r'localStorage\.setItem\("surveyData_form\d+",\s*JSON\.stringify\(data\)\)'
    replacement5 = f'localStorage.setItem(getFormStorageKey({form_number}), JSON.stringify(data))'
    if re.search(pattern5, content) and form_number not in [1, 2, 3]:  # 既に処理されたものを除く
        content = re.sub(pattern5, replacement5, content)
        changes_made.append(f"保存処理を置換（パターン5）")
    
    # パターン: localStorage.getItem("surveyData_formN")
    pattern6 = r'localStorage\.getItem\("surveyData_form\d+"\)'
    replacement6 = f'localStorage.getItem(getFormStorageKey({form_number}))'
    if re.search(pattern6, content):
        content = re.sub(pattern6, replacement6, content)
        changes_made.append(f"取得処理を置換（パターン6）")
    
    # 変更があった場合のみファイルを更新
    if content != original_content:
        # バックアップを作成
        backup_path = f"{filepath}.backup"
        with open(backup_path, 'w', encoding='utf-8') as f:
            f.write(original_content)
        
        # ファイルを更新
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"  ✓ 更新完了")
        print(f"  ✓ バックアップ: {backup_path}")
        for change in changes_made:
            print(f"    - {change}")
        return True
    else:
        print(f"  - 変更なし（既に更新済みまたは対象パターンなし）")
        return False

def main():
    """メイン処理"""
    print("=" * 60)
    print("フォームファイル一括更新スクリプト")
    print("=" * 60)
    
    # 現在のディレクトリを確認
    current_dir = Path.cwd()
    print(f"\n現在のディレクトリ: {current_dir}")
    
    # form1.html～form19.htmlを更新
    updated_count = 0
    skipped_count = 0
    
    for i in range(1, 20):
        filepath = f'form{i}.html'
        if update_form_file(filepath, i):
            updated_count += 1
        else:
            skipped_count += 1
    
    print("\n" + "=" * 60)
    print("処理完了")
    print("=" * 60)
    print(f"更新: {updated_count} ファイル")
    print(f"スキップ: {skipped_count} ファイル")
    print("\n注意:")
    print("- バックアップファイル（*.backup）が作成されています")
    print("- 問題がある場合は、バックアップから復元してください")
    print("- form0.htmlとform20.htmlは既に更新済みなので対象外です")

if __name__ == "__main__":
    main()

