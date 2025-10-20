# APOS-HC アンケートシステム - クイックスタート

## 🚀 セットアップ（初回のみ）

### 1. データベースの初期化

```bash
cd C:\Users\yukin\Desktop\analysis\backend
python app/init_db.py
```

✅ 成功すると以下のメッセージが表示されます：
```
✓ データベースの初期化が完了しました
✓ 作成されたテーブル:
  - form1
  - survey_responses
```

### 2. サーバーの起動

```bash
cd C:\Users\yukin\Desktop\analysis\backend
python run_server.py
```

✅ サーバーが起動すると：
```
🚀 APOS-HC API サーバーを起動中...
🌐 サーバーURL: http://localhost:8000
```

## 📝 使用フロー

### ステップ1: ユーザー登録

1. ブラウザで `http://localhost:8000/` にアクセス
2. **事業所番号**と**個人番号**を入力
   - 例: 事業所番号 `001`, 個人番号 `123`
   - ユーザーID: `001_123` として保存されます
3. セッションを選択（1回目、2回目、3回目）

### ステップ2: アンケート回答

- **form0.html～form19.html**まで順番に回答
- データは自動的にブラウザのlocalStorageに保存されます
- 途中で中断しても、次回アクセス時に続きから回答可能

### ステップ3: 完了

- **form19.html**まで回答完了後、**form20.html**に自動遷移
- 全フォームデータが自動的にサーバーに送信されます
- 保存が成功すると、完了メッセージが表示されます

## 📊 データの確認

### データベースの確認

```bash
cd C:\Users\yukin\Desktop\analysis\backend
sqlite3 form1_data.db
```

SQLコマンド:
```sql
-- 全レコードを確認
SELECT * FROM survey_responses;

-- 特定ユーザーのデータを確認
SELECT * FROM survey_responses WHERE user_id = '001_123';

-- ユーザー一覧
SELECT DISTINCT user_id FROM survey_responses;
```

### CSVエクスポート

ブラウザで以下にアクセス：
```
http://localhost:8000/api/export_survey_csv
```

## 🔧 主要なAPIエンドポイント

| エンドポイント | メソッド | 説明 |
|--------------|---------|------|
| `/` | GET | トップページ（form.html） |
| `/form0.html` ～ `/form19.html` | GET | アンケートフォーム |
| `/form20.html` | GET | 完了ページ |
| `/api/check_progress` | GET | 進捗確認 |
| `/api/save-survey` | POST | アンケートデータ保存 |
| `/api/get-survey` | GET | アンケートデータ取得 |
| `/api/export_survey_csv` | GET | CSVエクスポート |

### API使用例

#### 進捗確認
```bash
curl "http://localhost:8000/api/check_progress?user_id=001_123&session=1"
```

レスポンス:
```json
{
  "done": false,
  "user_id": "001_123",
  "session": 1
}
```

#### データ取得
```bash
curl "http://localhost:8000/api/get-survey?user_id=001_123&session=1"
```

## 📂 データ保存の仕組み

### クライアント側（localStorage）

各フォームのデータは以下の形式で保存：
```
surveyData_{ユーザーID}_form{番号}
```

例:
- `surveyData_001_123_form0`
- `surveyData_001_123_form1`
- ...
- `surveyData_001_123_form19`

### サーバー側（データベース）

テーブル: `survey_responses`

| カラム名 | 型 | 説明 |
|---------|-----|------|
| id | INTEGER | 主キー |
| user_id | STRING | ユーザーID（事業所番号_個人番号） |
| session | INTEGER | セッション番号（1, 2, 3） |
| form_data | JSON | 全フォームデータ |
| completed | INTEGER | 完了フラグ（0: 未完了, 1: 完了） |
| created_at | TIMESTAMP | 作成日時 |
| updated_at | TIMESTAMP | 更新日時 |

## 🔍 トラブルシューティング

### 問題: ユーザー情報が見つかりません

**解決方法**: `http://localhost:8000/` から再度開始してください。

### 問題: データが保存されない

**確認項目**:
1. サーバーが起動しているか
2. ブラウザのコンソールでエラーを確認
3. データベースファイルの権限を確認

### 問題: 以前のデータを削除したい

ブラウザのコンソールで実行:
```javascript
localStorage.clear();
```

または特定のユーザーのみ削除:
```javascript
const userId = '001_123';
for (let i = 0; i <= 19; i++) {
  localStorage.removeItem(`surveyData_${userId}_form${i}`);
}
```

## 🎯 テストデータの作成

### 方法1: ブラウザから手動入力

1. `http://localhost:8000/` にアクセス
2. 事業所番号: `001`, 個人番号: `TEST001`
3. セッション1を選択
4. 各フォームに適当なデータを入力
5. form20まで進む

### 方法2: Pythonスクリプトで作成

```python
import requests
import json

# テストデータ
test_data = {
    "user_id": "001_TEST001",
    "session": 1,
    "form_data": {
        "form0": {"test": "data"},
        "form1": {"test": "data"}
        # ... 他のフォームデータ
    },
    "completed": 1
}

# 保存
response = requests.post(
    "http://localhost:8000/api/save-survey",
    json=test_data
)
print(response.json())
```

## 📖 詳細ドキュメント

- **使用方法の詳細**: `USAGE.md`
- **フォーム修正ガイド**: `MIGRATION_GUIDE.md`

## 🌐 本番環境へのデプロイ

```bash
cd C:\Users\yukin\Desktop\analysis\backend\app\templates
bash deploy_to_vps.sh
```

または `deployment_guide.md` を参照してください。

## 📞 サポート

問題が発生した場合:
1. サーバーのログを確認
2. ブラウザのコンソールを確認
3. データベースの内容を確認（SQLite）

