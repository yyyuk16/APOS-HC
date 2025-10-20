# フォームデータ保存API デプロイメントガイド

## 🚀 本番環境へのデプロイ手順

### 1. ファイルのアップロード
本番サーバー（さくらVPS）に以下のファイルをアップロードしてください：

- `production_form_api.py` - 本番環境用のAPIサーバー
- `requirements.txt` - 必要なPythonパッケージ

### 2. サーバー設定

#### 2.1 必要なパッケージのインストール
```bash
pip install fastapi uvicorn python-multipart
```

#### 2.2 ディレクトリの作成
```bash
sudo mkdir -p /var/www/app/exports
sudo chown www-data:www-data /var/www/app/exports
sudo chmod 755 /var/www/app/exports
```

#### 2.3 systemdサービスの作成
`/etc/systemd/system/form-api.service` ファイルを作成：

```ini
[Unit]
Description=Form Data API Server
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/app
ExecStart=/usr/bin/python3 /var/www/app/production_form_api.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

#### 2.4 サービスの開始
```bash
sudo systemctl daemon-reload
sudo systemctl enable form-api
sudo systemctl start form-api
sudo systemctl status form-api
```

### 3. Nginx設定

#### 3.1 リバースプロキシの設定
`/etc/nginx/sites-available/homecare-form.com` に以下を追加：

```nginx
# Form API Server (Port 8001)
location /api/form/ {
    proxy_pass http://127.0.0.1:8001/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

#### 3.2 Nginx設定の再読み込み
```bash
sudo nginx -t
sudo systemctl reload nginx
```

### 4. フロントエンドの設定変更

#### 4.1 form.html, form0.html, form20.html の修正
以下のようにAPI URLを変更：

```javascript
// 現在の設定
const baseURL = window.location.hostname.includes("localhost") 
  ? "http://localhost:8001" 
  : "https://homecare-form.com";

// 本番環境用の設定
const baseURL = window.location.hostname.includes("localhost") 
  ? "http://localhost:8001" 
  : "https://homecare-form.com/api/form";
```

### 5. 動作確認

#### 5.1 APIサーバーの確認
```bash
curl https://homecare-form.com/api/form/
```

#### 5.2 データ保存のテスト
```bash
curl -X POST https://homecare-form.com/api/form/save-form \
  -H "Content-Type: application/json" \
  -d '{"facility_id":"TEST001","person_id":"0001","answers":{"Q1":"はい","Q2":"いいえ","Q3_text":"テスト記述"}}'
```

#### 5.3 データ取得のテスト
```bash
curl https://homecare-form.com/api/form/get-form-data
```

### 6. ログの確認

#### 6.1 サービスログ
```bash
sudo journalctl -u form-api -f
```

#### 6.2 エラーログ
```bash
sudo tail -f /var/log/nginx/error.log
```

### 7. トラブルシューティング

#### 7.1 ポート競合の確認
```bash
sudo netstat -tlnp | grep :8001
```

#### 7.2 権限の確認
```bash
ls -la /var/www/app/exports/
```

#### 7.3 ファイアウォールの確認
```bash
sudo ufw status
```

## 📊 使用例

### フォームデータ保存
```javascript
const response = await fetch('https://homecare-form.com/api/form/save-form', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    facility_id: "A001",
    person_id: "0001",
    answers: {
      "Q1": "はい",
      "Q2": "いいえ",
      "Q3_text": "自由記述内容",
      "Q4_image": "data:image/png;base64,..."
    }
  })
});
```

### データ取得
```javascript
const response = await fetch('https://homecare-form.com/api/form/get-form-data');
const data = await response.json();
console.log(data.data); // 保存されたデータの配列
```

## 🔧 メンテナンス

### データバックアップ
```bash
sudo cp /var/www/app/exports/form_data.csv /backup/form_data_$(date +%Y%m%d_%H%M%S).csv
```

### ログローテーション
```bash
sudo logrotate -f /etc/logrotate.d/form-api
```

### サービス再起動
```bash
sudo systemctl restart form-api
```

## 📝 注意事項

1. **セキュリティ**: 本番環境では適切なアクセス制御を設定してください
2. **バックアップ**: 定期的にCSVファイルのバックアップを取ってください
3. **監視**: サーバーのリソース使用量を監視してください
4. **更新**: 定期的にパッケージの更新を行ってください