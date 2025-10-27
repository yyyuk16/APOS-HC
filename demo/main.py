# ============================
# APOS-HC 入力フォーム用 FastAPI
# ============================

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import os
# ----------------------------
# アプリ本体
# ----------------------------
app = FastAPI()

# CORS（開発中は広く許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------
# form0〜form20.html を返すルート
# ----------------------------
@app.get("/form{num}.html", response_class=HTMLResponse)
async def serve_form(num: int):
    """
    /form0.html ～ /form20.html にアクセスしたとき、対応するHTMLを返す
    """
    html_path = f"/var/www/app/backend/app/templates/form{num}.html"
    if not os.path.exists(html_path):
        raise HTTPException(status_code=404, detail=f"Not Found: {html_path}")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

# ----------------------------
# トップページ（form.html）
# ----------------------------
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    html_path = "/var/www/app/backend/app/templates/form.html"
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()

# ----------------------------
# 静的ファイル（CSS, JS など）
# ----------------------------
static_dir = "/var/www/app/backend/app/templates"
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# ----------------------------
# デバッグ
# ----------------------------
@app.get("/ping")
async def ping():
    return {"status": "ok"}

# ----------------------------
# フォーム1 保存API（最小実装）
# ----------------------------
@app.post("/api/form1")
async def submit_form1(request: Request):
    try:
        payload = await request.json()
        office_id = payload.get("office_id", "unknown")
        person_id = payload.get("person_id", "unknown")
        record_id = f"{office_id}_{person_id}"
        return JSONResponse({"status": "success", "record_id": record_id})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



@app.post("/api/form_demo")
def save_demo_record(data: dict):
    import csv, os
    os.makedirs("exports_demo", exist_ok=True)
    with open("exports_demo/demo_records.csv", "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=data.keys())
        if f.tell() == 0:
            writer.writeheader()
        writer.writerow(data)
    return {"status": "ok"}


@app.get("/api/export_demo")
async def get_export_demo():
    csv_path = "/var/www/app/backend/app/exports_demo/demo_records.csv"
    if os.path.exists(csv_path):
        return FileResponse(csv_path, media_type="text/csv", filename="demo_records.csv")
    return {"error": "CSV file not found"}

@app.get("/api/export_demo/download")
async def download_export_demo():
    csv_path = "/var/www/app/backend/app/exports_demo/demo_records.csv"
    if os.path.exists(csv_path):
        return FileResponse(csv_path, media_type="text/csv", filename="demo_records.csv")
    return {"error": "CSV file not found"}
