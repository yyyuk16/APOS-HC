#!/bin/bash
# さくらのVPSデプロイスクリプト

echo "🚀 さくらのVPSにデプロイします..."

# システムの更新
sudo apt update && sudo apt upgrade -y

# Python3とpipのインストール
sudo apt install python3 python3-pip python3-venv nginx -y

# プロジェクトディレクトリの作成
sudo mkdir -p /var/www/apos-hc
sudo chown -R $USER:$USER /var/www/apos-hc
cd /var/www/apos-hc

# 仮想環境の作成とアクティベート
python3 -m venv venv
source venv/bin/activate

# 依存関係のインストール
pip install fastapi uvicorn psycopg2-binary SQLAlchemy python-dotenv pydantic pandas email-validator jinja2 python-multipart

# プロジェクトファイルのアップロード（手動で行う）
echo "📁 プロジェクトファイルをアップロードしてください"

# Nginx設定
sudo tee /etc/nginx/sites-available/apos-hc > /dev/null <<EOF
server {
    listen 80;
    server_name your-domain.com;  # ドメイン名を変更してください
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
    
    location /static {
        alias /var/www/apos-hc/static;
    }
}
EOF

# Nginx設定を有効化
sudo ln -s /etc/nginx/sites-available/apos-hc /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

# systemdサービスファイルの作成
sudo tee /etc/systemd/system/apos-hc.service > /dev/null <<EOF
[Unit]
Description=APOS-HC FastAPI Application
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/var/www/apos-hc
Environment=PATH=/var/www/apos-hc/venv/bin
ExecStart=/var/www/apos-hc/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# サービスを有効化
sudo systemctl daemon-reload
sudo systemctl enable apos-hc
sudo systemctl start apos-hc

echo "✅ デプロイ完了！"
echo "📍 アクセス先: http://your-domain.com"
echo "🔧 サービス管理: sudo systemctl status apos-hc"
