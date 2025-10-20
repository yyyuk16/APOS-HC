#!/bin/bash
# APOS-HC さくらVPS デプロイスクリプト

echo "🚀 APOS-HC さくらVPS デプロイ開始"

# 1. システム更新
echo "📦 システム更新中..."
sudo apt update
sudo apt upgrade -y

# 2. 必要なパッケージのインストール
echo "📦 必要なパッケージをインストール中..."
sudo apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx

# 3. プロジェクトディレクトリ作成
echo "📁 プロジェクトディレクトリを作成中..."
sudo mkdir -p /opt/apos-hc
sudo chown $USER:$USER /opt/apos-hc

# 4. プロジェクトファイルをコピー
echo "📋 プロジェクトファイルをコピー中..."
cp -r app/ /opt/apos-hc/
cp requirements.txt /opt/apos-hc/

# 5. 仮想環境作成と依存関係インストール
echo "🐍 Python仮想環境を作成中..."
cd /opt/apos-hc
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 6. systemd サービスファイル作成
echo "⚙️ systemdサービスを作成中..."
sudo tee /etc/systemd/system/apos-hc.service > /dev/null <<EOF
[Unit]
Description=APOS-HC API Server
After=network.target

[Service]
Type=exec
User=$USER
WorkingDirectory=/opt/apos-hc
ExecStart=/opt/apos-hc/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

# 7. Nginx設定
echo "🌐 Nginx設定を作成中..."
sudo tee /etc/nginx/sites-available/apos-hc > /dev/null <<EOF
server {
    listen 80;
    server_name app.homecare-form.com;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
    
    location /app/ {
        alias /opt/apos-hc/app/;
        try_files \$uri \$uri/ =404;
    }
}
EOF

# 8. Nginx設定を有効化
echo "🔗 Nginx設定を有効化中..."
sudo ln -sf /etc/nginx/sites-available/apos-hc /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx

# 9. サービス開始
echo "🚀 サービスを開始中..."
sudo systemctl daemon-reload
sudo systemctl enable apos-hc
sudo systemctl start apos-hc

# 10. ステータス確認
echo "📊 サービス状況確認:"
sudo systemctl status apos-hc --no-pager

echo "✅ デプロイ完了！"
echo "🌐 アクセス: http://app.homecare-form.com"
echo "📚 API ドキュメント: http://app.homecare-form.com/docs"
echo "📋 フォーム: http://app.homecare-form.com/app/templates/form.html"
