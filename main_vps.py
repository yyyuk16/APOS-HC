#!/usr/bin/env python3
"""
さくらのVPS用メインアプリケーション
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
import os
import sys

# パスを追加してroutesとutilsをインポート可能に
backend_dir = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, backend_dir)

# database.pyとmodels.pyはappディレクトリ内にある
from app.database import Base, engine
from routes import form as form_route
from routes import export as export_route

load_dotenv()

app = FastAPI(title="APOS-HC Backend (one-hot)")

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://homecare-form.com",
        "https://app.homecare-form.com",
        "https://your-domain.com",  # 実際のドメインに変更
        "*"  # 開発用（本番では削除）
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# テンプレートディレクトリ
templates_dir = os.path.join(os.path.dirname(__file__), "app", "templates")
templates = Jinja2Templates(directory=templates_dir)

# 静的ファイルをマウント（staticディレクトリを公開）
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# DB 初期化（既存テーブルも含めて全て作成）
Base.metadata.create_all(bind=engine)

# ルーター登録
app.include_router(form_route.router)
app.include_router(export_route.router)

# === ルートエンドポイント ===
@app.get("/")
def root():
    return {"ok": True, "service": "APOS-HC (one-hot)", "version": "2.0", "environment": "production"}

@app.get("/export_page")
def export_page(request: Request):
    """CSVエクスポートページ"""
    return templates.TemplateResponse("export.html", {"request": request})

# === 既存フォーム表示用エンドポイント（互換性維持） ===
@app.get("/form{num}.html", response_class=HTMLResponse)
async def serve_form(num: int):
    """既存のフォームHTML配信"""
    filename = f"form{num}.html"
    html_path = os.path.join(templates_dir, filename)
    try:
        with open(html_path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Form not found</h1>"

@app.get("/form.html", response_class=HTMLResponse)
async def serve_form_root():
    """ルートフォームHTML配信"""
    html_path = os.path.join(templates_dir, "form.html")
    try:
        with open(html_path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Form not found</h1>"

@app.get("/export.html", response_class=HTMLResponse)
async def export_html():
    """エクスポートHTML配信"""
    html_path = os.path.join(templates_dir, "export.html")
    try:
        with open(html_path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Export page not found</h1>"

@app.get("/sample_form", response_class=HTMLResponse)
async def sample_form():
    """サンプルフォーム直接配信"""
    sample_path = os.path.join(os.path.dirname(__file__), "static", "FORM_SUBMIT_SAMPLE.html")
    try:
        with open(sample_path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Sample form not found</h1>"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

print("✅ APOS-HC Backend (one-hot) が起動しました")
print("📍 本番環境モード")
print("🔧 管理: sudo systemctl status apos-hc")
