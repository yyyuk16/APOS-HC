#!/usr/bin/env python3
"""
APOS-HC API サーバー起動スクリプト
開発環境用のサーバー起動とヘルスチェック
"""

import uvicorn
import sys
import os
from pathlib import Path

# プロジェクトルートをPythonパスに追加
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def main():
    """メイン関数"""
    print("🚀 APOS-HC API サーバーを起動中...")
    print("📍 プロジェクトルート:", project_root)
    print("🌐 サーバーURL: http://localhost:8000")
    print("📚 API ドキュメント: http://localhost:8000/docs")
    print("🔍 ヘルスチェック: http://localhost:8000/api/health")
    print("-" * 50)
    
    try:
        # サーバー起動
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,  # 開発環境用の自動リロード
            log_level="info",
            access_log=True
        )
    except KeyboardInterrupt:
        print("\n🛑 サーバーを停止しました")
    except Exception as e:
        print(f"❌ サーバー起動エラー: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
