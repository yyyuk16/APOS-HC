#!/usr/bin/env python3
"""
簡単なサーバーでform.htmlを表示
"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import os

app = FastAPI()

# 静的ファイルをマウント
app.mount("/static", StaticFiles(directory="app/templates"), name="static")

@app.get("/", response_class=HTMLResponse)
async def root():
    """トップページでform.htmlを表示"""
    html_path = os.path.join("app", "templates", "form.html")
    try:
        with open(html_path, encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"<h1>Error</h1><p>form.htmlが見つかりません: {e}</p>"

@app.get("/form.html", response_class=HTMLResponse)
async def form_html():
    """form.htmlを直接表示"""
    html_path = os.path.join("app", "templates", "form.html")
    try:
        with open(html_path, encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"<h1>Error</h1><p>form.htmlが見つかりません: {e}</p>"

if __name__ == "__main__":
    import uvicorn
    print("🚀 Simple Server starting...")
    print("🌐 URL: http://localhost:8004/")
    uvicorn.run(app, host="127.0.0.1", port=8004)
