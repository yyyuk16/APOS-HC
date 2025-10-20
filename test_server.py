#!/usr/bin/env python3
"""
簡単なテストサーバー
"""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

app = FastAPI()

@app.get("/")
def root():
    return {"message": "テストサーバーが動作しています！", "status": "ok"}

@app.get("/test", response_class=HTMLResponse)
def test_page():
    return """
    <html>
        <head><title>テストページ</title></head>
        <body>
            <h1>✅ サーバーが正常に動作しています！</h1>
            <p>FastAPIサーバーが起動しています。</p>
        </body>
    </html>
    """

if __name__ == "__main__":
    print("🚀 テストサーバーを起動します...")
    print("📍 URL: http://localhost:8001")
    uvicorn.run(app, host="0.0.0.0", port=8001)