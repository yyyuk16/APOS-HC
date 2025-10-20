# フォームファイルの修正ガイド

## 概要

form1.html～form19.htmlのlocalStorage管理をユーザーIDベースに変更するための修正手順です。

## 修正が必要なファイル

- form1.html
- form2.html
- form3.html
- ...
- form19.html

**注意**: form0.htmlは既に修正済みです。form20.htmlは完了ページなので修正不要です。

## 修正手順

各フォームファイル（form1.html～form19.html）に対して以下の修正を行います。

### 1. 共通スクリプトの読み込み

`<head>`タグ内または`</body>`の直前に以下を追加：

```html
<script src="survey-common.js"></script>
```

### 2. 既存のlocalStorage処理を置き換え

#### 修正前:
```javascript
localStorage.setItem("surveyData_form1", JSON.stringify(data));
```

#### 修正後:
```javascript
const storageKey = getFormStorageKey(1); // フォーム番号を指定
localStorage.setItem(storageKey, JSON.stringify(data));
```

### 3. データ復元処理を置き換え

#### 修正前:
```javascript
const saved = localStorage.getItem("surveyData_form1");
```

#### 修正後:
```javascript
const saved = localStorage.getItem(getFormStorageKey(1)); // フォーム番号を指定
```

### 4. 自動保存機能を使用する場合

既存の自動保存コードを以下に置き換え：

```javascript
document.addEventListener('DOMContentLoaded', function() {
  // フォーム番号を指定（form1の場合は1、form2の場合は2...）
  initFormAutoSave(1);
});
```

## 完全な例（form1.html）

### 修正箇所の例

```html
<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <title>APOS-HC 入力フォーム - フォーム1</title>
  <!-- 共通スクリプトを読み込み -->
  <script src="survey-common.js"></script>
</head>
<body>
  <!-- フォーム内容 -->
  <form id="surveyForm">
    <!-- ... -->
  </form>

  <script>
    // ページ読み込み時に自動保存機能を初期化
    document.addEventListener('DOMContentLoaded', function() {
      // form1なので formNumber = 1
      const formNumber = 1;
      initFormAutoSave(formNumber);
    });
  </script>
</body>
</html>
```

## 一括置換用の正規表現

### パターン1: 保存処理
**検索**: `localStorage\.setItem\("surveyData_form(\d+)"`, `JSON\.stringify\(data\)\);`
**置換**: `localStorage.setItem(getFormStorageKey($1), JSON.stringify(data));`

### パターン2: 復元処理
**検索**: `localStorage\.getItem\("surveyData_form(\d+)"\)`
**置換**: `localStorage.getItem(getFormStorageKey($1))`

### パターン3: バッククォートを使用している場合
**検索**: `` localStorage\.setItem\(`surveyData_form\$\{formNumber\}``, `JSON\.stringify\(data\)\); ``
**置換**: `localStorage.setItem(getFormStorageKey(formNumber), JSON.stringify(data));`

## 検証方法

修正後、以下の手順で動作確認：

1. form.htmlで事業所番号と個人番号を入力
2. セッションを選択してform0に進む
3. 各フォームでデータを入力
4. ブラウザのコンソールで以下を実行：

```javascript
// localStorageの内容を確認
for (let i = 0; i < localStorage.length; i++) {
  const key = localStorage.key(i);
  console.log(key);
}

// ユーザーIDを確認
console.log('User ID:', localStorage.getItem('user_id'));

// 特定のフォームデータを確認
const userId = localStorage.getItem('user_id');
console.log(`Form 1 data:`, localStorage.getItem(`surveyData_${userId}_form1`));
```

期待される出力:
```
surveyData_001_123_form0
surveyData_001_123_form1
surveyData_001_123_form2
...
user_id
session
office_id
personal_id
```

## トラブルシューティング

### データが保存されない

1. ブラウザのコンソールでエラーを確認
2. survey-common.jsが正しく読み込まれているか確認
3. formNumber が正しく設定されているか確認

### 古いデータが残っている

localStorageをクリア:
```javascript
localStorage.clear();
```

または、古いキーのみ削除:
```javascript
// surveyData_form0～form19 のキーを削除
for (let i = 0; i <= 19; i++) {
  localStorage.removeItem(`surveyData_form${i}`);
}
```

## 自動化スクリプト（オプション）

すべてのフォームファイルを一括で修正するPythonスクリプト：

```python
import re
import glob

def update_form_file(filepath, form_number):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # survey-common.jsの読み込みを追加（まだ無い場合）
    if 'survey-common.js' not in content:
        content = content.replace('</head>', '  <script src="survey-common.js"></script>\n</head>')
    
    # localStorageの保存処理を置換
    content = re.sub(
        r'localStorage\.setItem\("surveyData_form\d+"', r'JSON\.stringify\(data\)\);',
        f'localStorage.setItem(getFormStorageKey({form_number}), JSON.stringify(data));',
        content
    )
    
    # localStorageの取得処理を置換
    content = re.sub(
        r'localStorage\.getItem\("surveyData_form\d+"\)',
        f'localStorage.getItem(getFormStorageKey({form_number}))',
        content
    )
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f'Updated: {filepath}')

# form1.html～form19.htmlを一括更新
for i in range(1, 20):
    filepath = f'form{i}.html'
    update_form_file(filepath, i)
```

実行:
```bash
python update_forms.py
```

## 注意事項

- 修正前に必ずバックアップを取ってください
- form0.htmlは既に修正済みなので、修正不要です
- form20.htmlは完了ページなので、修正不要です（独自の処理を使用）
- 各フォームのformNumber値は正確に設定してください（form1なら1、form2なら2...）

