from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

app = FastAPI()

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://homecare-form.com",
        "https://app.homecare-form.com",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def one_hot_encode_answers(answers: Dict[str, Any]) -> Dict[str, Any]:
    """選択式回答をone-hotエンコード形式に変換"""
    encoded = {}
    
    for key, value in answers.items():
        if isinstance(value, str) and value in ["はい", "いいえ", "Yes", "No"]:
            # はい/いいえの選択肢をone-hotエンコード
            encoded[f"{key}_yes"] = 1 if value in ["はい", "Yes"] else 0
            encoded[f"{key}_no"] = 1 if value in ["いいえ", "No"] else 0
        elif key.endswith("_text"):
            # 記述欄はそのまま保存
            encoded[key] = str(value)
        elif key.endswith("_image"):
            # 画像はbase64文字列として保存
            encoded[key] = str(value)
        else:
            # その他の回答はそのまま保存もしくはone-hotエンコード
            if isinstance(value, str):
                encoded[f"{key}_{value}"] = 1
            else:
                encoded[key] = str(value)
    
    return encoded

def save_form_data_to_csv(facility_id: str, person_id: str, answers: Dict[str, Any]) -> str:
    """フォームデータをCSVファイルに保存"""
    # ユーザーIDを作成
    user_id = f"{facility_id}_{person_id}"
    
    # 回答をone-hotエンコード
    encoded_answers = one_hot_encode_answers(answers)
    
    # CSVファイルのパス（環境に応じて調整）
    if os.name == 'nt':  # Windows環境
        csv_dir = Path("./exports")
    else:  # Linux環境
        csv_dir = Path("/var/www/app/exports")
    csv_file = csv_dir / "form_data.csv"
    
    # ディレクトリが存在しない場合は作成
    csv_dir.mkdir(parents=True, exist_ok=True)
    
    # 既存のCSVファイルを読み込み
    existing_data = []
    fieldnames = set(["user_id"])
    
    if csv_file.exists():
        with open(csv_file, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            existing_data = list(reader)
            if existing_data:
                fieldnames.update(existing_data[0].keys())
    
    # 新しいデータのフィールド名を追加
    fieldnames.update(encoded_answers.keys())
    fieldnames = list(fieldnames)
    
    # 同じuser_idの既存データを削除
    existing_data = [row for row in existing_data if row.get("user_id") != user_id]
    
    # 新しいデータ行を作成
    new_row = {"user_id": user_id}
    new_row.update(encoded_answers)
    
    # 既存データに新しい行を追加
    existing_data.append(new_row)
    
    # CSVファイルに書き込み
    with open(csv_file, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(existing_data)
    
    return str(csv_file)

@app.get("/")
async def root():
    return {"message": "Form API Server is running"}

@app.post("/api/save-form")
async def save_form_data(request: Request):
    """フォームデータをCSVファイルに保存"""
    try:
        data = await request.json()
        
        # 必須フィールドの確認
        facility_id = data.get("facility_id")
        person_id = data.get("person_id")
        answers = data.get("answers", {})
        
        if not facility_id or not person_id:
            raise HTTPException(status_code=400, detail="facility_id と person_id は必須です")
        
        # CSVファイルに保存
        csv_path = save_form_data_to_csv(facility_id, person_id, answers)
        
        return {
            "status": "success",
            "message": "フォームデータが正常に保存されました",
            "user_id": f"{facility_id}_{person_id}",
            "csv_path": csv_path,
            "saved_at": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"データ保存エラー: {str(e)}")

@app.get("/api/get-form-data")
async def get_form_data(user_id: str = None):
    """保存されたフォームデータを取得"""
    try:
        # CSVファイルのパス（環境に応じて調整）
        if os.name == 'nt':  # Windows環境
            csv_file = Path("./exports/form_data.csv")
        else:  # Linux環境
            csv_file = Path("/var/www/app/exports/form_data.csv")
        
        if not csv_file.exists():
            return {"data": [], "message": "データファイルが存在しません"}
        
        with open(csv_file, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            data = list(reader)
        
        # 特定のuser_idが指定された場合はフィルタリング
        if user_id:
            data = [row for row in data if row.get("user_id") == user_id]
        
        return {
            "data": data,
            "total_count": len(data),
            "message": "データを正常に取得しました"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"データ取得エラー: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
