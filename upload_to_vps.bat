@echo off
echo 🚀 VPSにファイルをアップロードします...

REM 必要なファイルをzipでまとめる
echo 📦 ファイルを圧縮中...
powershell -command "Compress-Archive -Path 'app', 'routes', 'utils', 'static', 'main_vps.py', 'requirements_vps.txt', '.env', 'deploy_vps.sh' -DestinationPath 'apos-hc-backend.zip' -Force"

echo ✅ 圧縮完了: apos-hc-backend.zip
echo.
echo 📋 次の手順:
echo 1. さくらのVPSコンソールでSSH接続
echo 2. ファイルをアップロード: scp apos-hc-backend.zip root@153.126.181.66:/tmp/
echo 3. VPSで解凍: unzip /tmp/apos-hc-backend.zip -d /var/www/apos-hc/
echo 4. デプロイスクリプト実行: chmod +x deploy_vps.sh && ./deploy_vps.sh
echo.
pause
