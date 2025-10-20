# APOS-HC アンケートシステム - 使用方法

## システム概要

このシステムは、事業所番号と個人番号でユーザーを識別し、3回のセッション（2ヶ月ごと）にわたってアンケートデータを収集・保存します。

## セットアップ

### 1. データベースの初期化

```bash
cd backend/app
python init_db.py
```

### 2. サーバーの起動

```bash
cd backend
python run_server.py
```

サーバーは `http://localhost:8000` で起動します。

## 使用フロー

### 1. ユーザー登録・ログイン（form.html）

1. `https://homecare-form.com/` にアクセス
2. **事業所番号**と**個人番号**を入力
3. セッション（1回目、2回目、3回目）を選択

**ユーザーID形式**: `事業所番号_個人番号`
- 例: 事業所番号が「001」、個人番号が「123」の場合
- ユーザーID: `001_123`

### 2. アンケート回答（form0.html ～ form19.html）

- 各フォームに回答を入力
- データは自動的にlocalStorageに保存されます
- 途中で中断しても、次回アクセス時に続きから回答可能

### 3. 完了（form20.html）

- form19.htmlまで回答完了後、form20.htmlに自動遷移
- 全フォームデータが自動的にサーバーに送信されます
- 保存が成功すると、完了メッセージが表示されます

## データ保存の仕組み

### クライアント側（localStorage）

各フォームのデータは以下のキー形式で保存されます：
```
surveyData_{ユーザーID}_form{番号}
```

例:
- `surveyData_001_123_form0`
- `surveyData_001_123_form1`
- ...
- `surveyData_001_123_form19`

### サーバー側（データベース）

`survey_responses`テーブルに保存されます：

| カラム名 | 説明 |
|---------|------|
| id | 主キー（自動採番） |
| user_id | ユーザーID（事業所番号_個人番号） |
| session | セッション番号（1, 2, 3） |
| form_data | 全フォームデータ（JSON形式） |
| completed | 完了フラグ（0: 未完了, 1: 完了） |
| created_at | 作成日時 |
| updated_at | 更新日時 |

## API エンドポイント

### 1. 進捗確認

```
GET /api/check_progress?user_id={ユーザーID}&session={セッション}
```

**レスポンス例**:
```json
{
  "done": false,
  "user_id": "001_123",
  "session": 1
}
```

### 2. アンケートデータ保存

```
POST /api/save-survey
```

**リクエストボディ**:
```json
{
  "user_id": "001_123",
  "session": 1,
  "form_data": {
    "form0": { ... },
    "form1": { ... },
    ...
    "form19": { ... }
  },
  "completed": 1
}
```

**レスポンス例**:
```json
{
  "status": "created",
  "id": 1,
  "user_id": "001_123",
  "session": 1,
  "completed": 1
}
```

### 3. アンケートデータ取得

```
GET /api/get-survey?user_id={ユーザーID}&session={セッション}
```

**レスポンス例**:
```json
{
  "found": true,
  "id": 1,
  "user_id": "001_123",
  "session": 1,
  "form_data": { ... },
  "completed": 1,
  "created_at": "2025-10-20 12:34:56",
  "updated_at": "2025-10-20 12:34:56"
}
```

### 4. CSVエクスポート

```
GET /api/export_survey_csv
```

全アンケートデータをCSV形式でダウンロードできます。

## データ管理

### データベースの確認

SQLiteデータベースファイル: `backend/form1_data.db`

```bash
sqlite3 backend/form1_data.db
```

```sql
-- 全レコードを確認
SELECT * FROM survey_responses;

-- 特定ユーザーのデータを確認
SELECT * FROM survey_responses WHERE user_id = '001_123';

-- セッションごとの完了状況を確認
SELECT user_id, session, completed, created_at 
FROM survey_responses 
ORDER BY user_id, session;
```

### データのバックアップ

```bash
# データベースファイルをバックアップ
cp backend/form1_data.db backend/form1_data_backup_$(date +%Y%m%d).db

# CSVエクスポートでバックアップ
curl http://localhost:8000/api/export_survey_csv -o backup_$(date +%Y%m%d).csv
```

## セッション管理

### 3回のセッション（2ヶ月ごと）

1. **1回目**: ベースライン調査
2. **2回目**: 2ヶ月後のフォローアップ
3. **3回目**: 4ヶ月後のフォローアップ

各セッションは独立して保存されます。同じユーザーが複数回回答する場合、セッション番号を変えて実施してください。

## トラブルシューティング

### 「ユーザー情報が見つかりません」エラー

form.htmlから再度開始してください。事業所番号と個人番号を入力してセッションを選択する必要があります。

### データが保存されない

1. ブラウザのコンソールでエラーを確認
2. サーバーが起動しているか確認
3. データベースファイルの権限を確認

### 以前のデータを削除したい

localStorageをクリア:
```javascript
// ブラウザのコンソールで実行
localStorage.clear();
```

## 本番環境へのデプロイ

1. `deploy_to_vps.sh`スクリプトを使用
2. または`deployment_guide.md`を参照

```bash
cd backend/app/templates
bash deploy_to_vps.sh
```

## セキュリティ

- 本番環境では必ず`ACCESS_KEY`を環境変数で設定してください
- HTTPS接続を使用してください
- データベースファイルのバックアップを定期的に実施してください

## サポート

問題が発生した場合は、ログファイルを確認してください：
- アプリケーションログ: コンソール出力
- データベース: `backend/form1_data.db`

