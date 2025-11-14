# ============================
# APOS-HC 入力フォーム用 FastAPI
# ============================
from fastapi import FastAPI, Request, Query, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles
from datetime import datetime, timedelta, timezone
import unicodedata
import os
import csv
import re
import base64
try:
    # DBユーティリティ（存在しない環境でも起動できるようにtryで囲む）
    from utils.db_utils import init_db, insert_form_data, export_all_records_to_csv
except Exception:
    init_db = None
    insert_form_data = None
    export_all_records_to_csv = None

app = FastAPI(title="APOS-HC Backend")

@app.on_event("startup")
def _startup_init_db():
    """アプリ起動時にDBを初期化（ユーティリティが読み込めた場合のみ）。"""
    try:
        if init_db:
            init_db()
    except Exception as e:
        try:
            print("⚠ DB init failed:", e)
        except Exception:
            pass
# ------------------------------------------------------------
# 🔹 設定: 保存先パス
# ------------------------------------------------------------
RECORDS_CSV_PATH = "/var/www/app/backend/app/records.csv"
DEMO_CSV_PATH = "/var/www/app/backend/app/exports_demo/demo_records.csv"
UPLOADS_DIR = "/var/www/app/backend/app/uploads"
BASE_UPLOAD_URL = "https://app.homecare-form.com/uploads"
KEY_FIELDS = ["user_id"]

# 🔹 画像の静的配信を有効化（/uploads/*）
os.makedirs(UPLOADS_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

# 画像アップロード専用API（multipart/form-data）
@app.post("/api/upload_image")
async def upload_image(file: UploadFile = File(...)):
    """
    画像アップロード用エンドポイント。
    - multipart/form-data で UploadFile を受け取り、そのまま保存
    - 保存先: UPLOADS_DIR
    - 返却: filename と URL
    """
    try:
        _ensure_dirs()
        filename = os.path.basename(file.filename or "")
        if not filename:
            return {"status": "error", "detail": "empty filename"}
        save_path = os.path.join(UPLOADS_DIR, filename)
        content = await file.read()
        with open(save_path, "wb") as wf:
            wf.write(content)
        return {
            "status": "ok",
            "filename": filename,
            "url": f"{BASE_UPLOAD_URL}/{filename}",
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}

# 🔹 CORS設定（ブラウザからのPOSTを許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 必要に応じて ["https://app.homecare-form.com"]
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------
# 🔹 デモフォーム保存API
# ------------------------------------------------------------
@app.post("/api/form_demo")
async def save_form_demo(request: Request):
    """デモフォーム送信 → demo_records.csv に 1ユーザー=1行でUpsert（本番と同等の前処理）"""
    try:
        _ensure_dirs()
        payload = await request.json()
        try:
            print("🧩 RAW payload from browser:", payload)
        except Exception:
            pass
        try:
            print("🧩 RAW payload from browser:", payload)
        except Exception:
            pass
        if not isinstance(payload, dict):
            return {"status": "error", "message": "Invalid JSON"}

        # form_id / タイムスタンプ
        form_id = payload.get("form_id") or _extract_form_id_from_referer(request.headers.get("referer")) or "demo_form"
        now = datetime.now(timezone(timedelta(hours=9)))
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

        # 画像があれば保存（DataURL → JPEG）
        image_files, image_key_map = _decode_and_save_images(payload, form_id, now)

        # one-hot 展開
        field_types = payload.pop("field_types", None)
        flattened = _flatten_payload(payload, field_types)

        # user_id 決定（無ければ office_id + personal_id/person_id）
        uid = (payload.get("user_id") or flattened.get("user_id") or "").strip()
        office_id = (payload.get("office_id") or flattened.get("office_id") or "").strip()
        personal_id = (payload.get("personal_id") or payload.get("person_id") or flattened.get("personal_id") or "").strip()
        if not uid and office_id and personal_id:
            uid = f"{office_id}_{personal_id}"
            flattened["user_id"] = uid

        row = {"timestamp": timestamp, "form_id": form_id}
        row.update(flattened)
        if uid:
            row["user_id"] = uid

        # 画像列は常に出力
        row["image_file"] = ";".join(image_files) if image_files else ""
        row["image_url"] = ";".join(f"{BASE_UPLOAD_URL}/{fname}" for fname in image_files) if image_files else ""

        # 固定スキーマ適用（必要フォームのみ）
        fid = (form_id or "").lower()
        def with_imgs(base: dict) -> dict:
            imgs = {k: row.get(k, "") for k in ("image_file","image_url")}
            return {**{"timestamp": base.get("timestamp", timestamp), "form_id": fid, "user_id": uid}, **base, **imgs}

# 実データを受け取ってる
        if fid == "form0":
            row = with_imgs(_form0_apply_aliases_and_order(dict(row)))
        elif fid == "form1":
            row = with_imgs(_form1_apply_aliases_and_order(dict(row)))
        elif fid == "form19":
            row = with_imgs(_form19_apply_order(dict(row)))

        # 不要列は除外（ID列は保持）
        for k in ("session", "form_id"):
            row.pop(k, None)

        # DB保存（任意機能：ユーティリティがある場合のみ）
        try:
            if insert_form_data:
                insert_form_data(fid, row)
        except Exception as e:
            try:
                print("⚠ DB insert (demo) failed:", e)
            except Exception:
                pass

        # Upsert 保存（1ユーザー=1行で上書き）
        _upsert_row(DEMO_CSV_PATH, row, KEY_FIELDS)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}




# ------------------------------------------------------------
# 🔹 本番フォーム保存API（既存のもの）※変更禁止
# ------------------------------------------------------------
@app.post("/api/form1")
async def save_form(request: Request):
    data = await request.json()
    os.makedirs("/var/www/app/backend/exports", exist_ok=True)
    csv_path = "/var/www/app/backend/exports/records.csv"

    file_exists = os.path.isfile(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=data.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(data)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {"status": "success", "saved_at": timestamp, "filename": "records.csv"}



# ------------------------------------------------------------
# 🔹 本番フォーム保存API（records.csv＋画像）
# ------------------------------------------------------------
@app.post("/api/form")
async def save_form_production(request: Request):
    """フォーム送信をCSV + 画像として保存"""
    try:
        _ensure_dirs()
        payload = await request.json()

        if not isinstance(payload, dict):
            return {"status": "error", "message": "Invalid JSON"}

        # -----------------------------
        # 基本情報
        # -----------------------------
        form_id = payload.get("form_id") or _extract_form_id_from_referer(request.headers.get("referer")) or "unknown_form"
        now = datetime.now(timezone(timedelta(hours=9)))
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

        # 画像のデコード（form17〜19などの upload画像）
        image_files, image_key_map = _decode_and_save_images(payload, form_id, now)

        field_types = payload.pop("field_types", None)
        flattened = _flatten_payload(payload, field_types)

        # form17 専用の薬剤画像ファイル名を拾う
        extra_image_files: list[str] = []
        if form_id == "form17":
            for i in range(1, 25):
                key = f"med_image_{i}_filename"
                val = str(flattened.get(key, "")).strip()
                if val:
                    flattened[key] = val
                    extra_image_files.append(val)
            for i in range(0, 25):
                key = f"emotional_distress_{i}_filename"
                val = str(flattened.get(key, "")).strip()
                if val:
                    flattened[key] = val
                    extra_image_files.append(val)

        # -----------------------------
        # ユーザー識別
        # -----------------------------
        uid = (payload.get("user_id") or flattened.get("user_id") or "").strip()
        office_id = (payload.get("office_id") or flattened.get("office_id") or "").strip()
        personal_id = (payload.get("personal_id") or flattened.get("personal_id") or "").strip()

        if not uid and office_id and personal_id:
            uid = f"{office_id}_{personal_id}"
            flattened["user_id"] = uid

        # -----------------------------
        # row 初期化
        # -----------------------------
        row = {"timestamp": timestamp, "form_id": form_id}
        row.update(flattened)
        if uid:
            row["user_id"] = uid

        # -----------------------------
        # 画像共通列（image_file / image_url）
        # -----------------------------
        all_image_files: list[str] = []
        for fname in list(image_files) + extra_image_files:
            if fname and fname not in all_image_files:
                all_image_files.append(fname)

        row["image_file"] = ";".join(all_image_files) if all_image_files else ""
        row["image_url"] = ";".join(f"{BASE_UPLOAD_URL}/{fname}" for fname in all_image_files) if all_image_files else ""

        # -----------------------------
        # form17 〜 form19 の専用画像列
        # -----------------------------
        urls = [f"{BASE_UPLOAD_URL}/{f}" for f in image_files]
        if form_id == "form17":
            row["pain_image_front"] = urls[0] if len(urls) > 0 else ""
            row["pain_image_back"] = urls[1] if len(urls) > 1 else ""
        elif form_id == "form18":
            row["paralysis_image_front"] = urls[0] if len(urls) > 0 else ""
            row["paralysis_image_back"] = urls[1] if len(urls) > 1 else ""
        elif form_id == "form19":
            row["contracture_image_front"] = urls[0] if len(urls) > 0 else ""
            row["contracture_image_back"] = urls[1] if len(urls) > 1 else ""

        # ============================================================
        # 🔥🔥🔥 form1：ここを完全に差し替え（Canvas → JPEG保存）
        # ============================================================
        if form_id == "form1":

            # Base64 のジェノグラム画像保存
            base64_img = row.get("genogramCanvas_image", "")
            saved_file = _save_genogram_base64(base64_img, uid)

            # one-hot や alias を適用
            form1_only = _form1_apply_aliases_and_order(row)

            # 専用列をセット
            form1_only["genogramCanvas_image"] = saved_file
            form1_only["genogram_file"] = saved_file
            form1_only["genogram_url"] = f"{BASE_UPLOAD_URL}/{saved_file}" if saved_file else ""

            row = {
                "timestamp": form1_only["timestamp"],
                "form_id": form_id,
                "user_id": uid,
                **form1_only
            }

        # ------------------------------------------------------------
        # form0（そのまま）
        # ------------------------------------------------------------
        elif form_id == "form0":
            form0_only = _form0_apply_aliases_and_order(row)
            if uid:
                form0_only["user_id"] = uid
            row = form0_only

        # ------------------------------------------------------------
        # form2
        # ------------------------------------------------------------
        elif form_id == "form2":
            form2_only = _form2_apply_order(row)
            row = {
                "timestamp": form2_only["timestamp"],
                "form_id": form_id,
                "user_id": uid,
                **form2_only
            }

        # ------------------------------------------------------------
        # form3
        # ------------------------------------------------------------
         elif form_id == "form3":
            form3_only = _form3_apply_order_and_image(row)
            row = {
                "timestamp": form3_only["timestamp"],
                "form_id": form_id,
                "user_id": uid,
                **form3_only
            }
            form3_only = _form3_apply_order_and_image(row)
            # デバッグ: form3 の主要 one-hot / 数値列を確認
            try:
                debug_f3 = {}
                for k in list(form3_only.keys()):
                    if (
                        k.startswith("residence_type_")
                        or k.startswith("elevator_")
                        or k.startswith("entrance_to_road_")
                        or k.startswith("expensive_cost_usage_")
                        or k.startswith("public_medical_usage_")
                        or k.startswith("reform_need_")
                        or k.startswith("reform_place_")
                        or k.startswith("care_tool_need_")
                        or k.startswith("care_tool_type_")
                        or k.startswith("equipment_need_")
                        or k.startswith("equipment_type_")
                        or k in ("apartment_floor","room_safety","room_photo_image_filename")
                    ):
                        debug_f3[k] = form3_only.get(k, "")
                print("🏠 form3 payload (residence/elevator/entrance/reform/tools/equipment):", debug_f3)
            except Exception:
                pass
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form3_only["timestamp"], "form_id": form_id, "user_id": uid}, **form3_only, **img_cols}
        elif form_id == "form4":
            form4_only = _form4_apply_order(row)
            # デバッグ: form4 の主要 one-hot / 数値列を確認
            try:
                debug_f4 = {}
                for k in list(form4_only.keys()):
                    if (
                        k.startswith("care_burden_feeling_")
                        or k.startswith("care_burden_health_")
                        or k.startswith("care_burden_life_")
                        or k.startswith("care_burden_work_")
                        or k in ("care_period_years","care_period_months")
                        or k.startswith("care_intention_")
                        or k.startswith("abuse_injury_")
                        or k.startswith("neglect_hygiene_")
                        or k.startswith("psychological_abuse_")
                        or k.startswith("neglect_care_")
                        or k.startswith("sexual_abuse_")
                        or k.startswith("financial_abuse_")
                        or k == "memo"
                    ):
                        debug_f4[k] = form4_only.get(k, "")
                print("🛡 form4 payload (burden/intention/abuse etc):", debug_f4)
            except Exception:
                pass
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form4_only["timestamp"], "form_id": form_id, "user_id": uid}, **form4_only, **img_cols}
        elif form_id == "form5":
            form5_only = _form5_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form5_only["timestamp"], "form_id": form_id, "user_id": uid}, **form5_only, **img_cols}
        elif form_id == "form6":
            form6_only = _form6_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form6_only["timestamp"], "form_id": form_id, "user_id": uid}, **form6_only, **img_cols}
        elif form_id == "form7":
            form7_only = _form7_apply_order(row)
            # デバッグ: oral_tongue の値を確認
            try:
                dbg = {k: form7_only.get(k, "") for k in ("oral_tongue_0","oral_tongue_1","oral_tongue_2","oral_tongue_surface_0","oral_tongue_surface_1","oral_tongue_surface_2")}
                print("🦷 form7 oral_tongue mapping:", dbg)
            except Exception:
                pass
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form7_only["timestamp"], "form_id": form_id, "user_id": uid}, **form7_only, **img_cols}
        elif form_id == "form8":
            form8_only = _form8_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form8_only["timestamp"], "form_id": form_id, "user_id": uid}, **form8_only, **img_cols}
        elif form_id == "form9":
            form9_only = _form9_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form9_only["timestamp"], "form_id": form_id, "user_id": uid}, **form9_only, **img_cols}
        elif form_id == "form10":
            form10_only = _form10_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            # form10 は URL 列は不要
            img_cols.pop("image_url", None)
            row = {**{"timestamp": form10_only["timestamp"], "form_id": form_id, "user_id": uid}, **form10_only, **img_cols}
        elif form_id == "form11":
            form11_only = _form11_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form11_only["timestamp"], "form_id": form_id, "user_id": uid}, **form11_only, **img_cols}
        elif form_id == "form12":
            form12_only = _form12_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form12_only["timestamp"], "form_id": form_id, "user_id": uid}, **form12_only, **img_cols}
        elif form_id == "form13":
            form13_only = _form13_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form13_only["timestamp"], "form_id": form_id, "user_id": uid}, **form13_only, **img_cols}
        elif form_id == "form14":
            form14_only = _form14_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form14_only["timestamp"], "form_id": form_id, "user_id": uid}, **form14_only, **img_cols}
        elif form_id == "form15":
            form15_only = _form15_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form15_only["timestamp"], "form_id": form_id, "user_id": uid}, **form15_only, **img_cols}
        elif form_id == "form16":
            form16_only = _form16_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form16_only["timestamp"], "form_id": form_id, "user_id": uid}, **form16_only, **img_cols}
        elif form_id == "form17":
            form17_only = _form17_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form17_only["timestamp"], "form_id": form_id, "user_id": row.get("user_id", "")}, **form17_only, **img_cols}
        elif form_id == "form18":
            form18_only = _form18_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form18_only["timestamp"], "form_id": form_id, "user_id": row.get("user_id", "")}, **form18_only, **img_cols}
        elif form_id == "form19":
            form19_only = _form19_apply_order(row)
            # デバッグ: form19 の主要列を確認
            try:
                keys = [
                    "fall_0","fall_1","fall_count","fall_detail",
                    "fall_anxiety_0","fall_anxiety_1","fall_anxiety_2",
                    "anxiety_reason_aging_muscle","anxiety_reason_disease","anxiety_reason_medicine",
                    "anxiety_reason_internal_other","internal_other_text","anxiety_reason_environment_external",
                    "fracture_0","fracture_1","fracture_cause_fall","fracture_cause_other",
                    "fracture_count","fracture_location","height_decrease_check","height_decrease",
                    "back_curved","back_pain",
                    "choking_risk_0","choking_risk_1",
                    "abuse_evaluation_0","abuse_evaluation_1","abuse_detail_a","abuse_detail_b","abuse_detail_c",
                    "kodokushi_feeling_0","kodokushi_feeling_1","kodokushi_feeling_2","kodokushi_feeling_3",
                    "fire_water_negligence_0","fire_water_negligence_1","fire_water_detail_a","fire_water_detail_b","fire_water_detail_c",
                    "news_eval_0","news_eval_1",
                    "dehydration_0","dehydration_1",
                    "abnormal_behavior_0","abnormal_behavior_1","abnormal_behavior_2","abnormal_behavior_3",
                ]
                dbg = {k: form19_only.get(k, "") for k in keys}
                print("🧩 form19 payload (mapped):", dbg)
            except Exception:
                pass
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form19_only["timestamp"], "form_id": form_id, "user_id": row.get("user_id", "")}, **form19_only, **img_cols}
        # 不要列をCSVから除外（ID列は保持）
        for k in ("session", "form_id"):
            row.pop(k, None)

        _upsert_row(RECORDS_CSV_PATH, row, KEY_FIELDS)
        # DB保存（ユーティリティがある場合のみ）
        try:
            if insert_form_data:
                insert_form_data(form_id, row)
        except Exception as e:
            try:
                print("⚠ DB insert failed:", e)
            except Exception:
                pass
        return {"status": "ok", "form_id": form_id, "timestamp": timestamp}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

# ------------------------------------------------------------
# 🔹 ディレクトリ存在確認（本番・デモ用）
# ------------------------------------------------------------
def _ensure_dirs():
    """保存先ディレクトリを確実に作成"""
    os.makedirs(os.path.dirname(RECORDS_CSV_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(DEMO_CSV_PATH), exist_ok=True)
    os.makedirs(UPLOADS_DIR, exist_ok=True)


# ------------------------------------------------------------
# 🔹 CSVエクスポートAPI（本番・デモ）
# ------------------------------------------------------------
@app.get("/api/export")
async def get_export():
    """CSVプレビュー"""
    csv_path = RECORDS_CSV_PATH
    if os.path.exists(csv_path):
        return FileResponse(csv_path, media_type="text/csv", filename="records.csv")
    else:
        return {"error": "CSV file not found"}


@app.get("/api/export/download")
async def download_export():
    """本番CSVダウンロード"""
    csv_path = RECORDS_CSV_PATH
    if os.path.exists(csv_path):
        return FileResponse(csv_path, media_type="text/csv", filename="records.csv")
    else:
        return {"error": "CSV file not found"}


@app.get("/api/export_demo")
async def get_export_demo():
    """デモCSVプレビュー"""
    csv_path = DEMO_CSV_PATH
    if os.path.exists(csv_path):
        return FileResponse(csv_path, media_type="text/csv", filename="demo_records.csv")
    else:
        return {"error": "CSV file not found"}


@app.get("/api/export_demo/download")
async def download_export_demo():
    """デモCSVダウンロード"""
    csv_path = DEMO_CSV_PATH
    if os.path.exists(csv_path):
        return FileResponse(csv_path, media_type="text/csv", filename="demo_records.csv")
    else:
        return {"error": "CSV file not found"}


# ------------------------------------------------------------
# 🔹 DB → CSV エクスポートAPI（最新）
# ------------------------------------------------------------
@app.get("/api/export/records-csv")
async def export_records_csv():
    """
    DBに保存された全レコードを CSV にエクスポートして返す。
    ユーティリティが無い/データ0件の場合は既存の records.csv を返すフォールバック。
    """
    try:
        out_path = "/var/www/app/backend/app/records_latest.csv"
        exported = -1
        if export_all_records_to_csv:
            try:
                exported = export_all_records_to_csv(out_path)
            except Exception as e:
                print("⚠ export db -> csv failed:", e)
        # DBで0件 or ユーティリティ無し → 既存CSVがあれば返す
        if (exported is None or exported <= 0) and os.path.exists(RECORDS_CSV_PATH):
            return FileResponse(
                RECORDS_CSV_PATH,
                media_type="text/csv",
                filename="records.csv",
            )
        # DBエクスポート成功時
        if os.path.exists(out_path):
            return FileResponse(
                out_path,
                media_type="text/csv",
                filename="records_latest.csv",
            )
        return {"detail": "No data"}
    except Exception as e:
        return {"detail": str(e)}


# ------------------------------------------------------------
# 🔹 デモ: 指定 user_id の保存済み1行を返す（Upsertのため1行想定）
# ------------------------------------------------------------
@app.get("/api/form_demo/row")
async def get_demo_row(user_id: str):
    try:
        if not os.path.exists(DEMO_CSV_PATH):
            return {"data": None}
        hit = None
        with open(DEMO_CSV_PATH, "r", encoding="utf-8-sig", newline="") as rf:
            reader = csv.DictReader(rf)
            for row in reader:
                if (row.get("user_id") or "").strip() == user_id.strip():
                    hit = row
        return {"data": hit}
    except Exception as e:
        return {"error": str(e)}




CHOICE_MASTER = {
    "sex": ["男", "女", "指定なし", "NA"],
    "request_route": ["CM", "MSW", "病院医師", "病院NS", "開業医師", "福祉職員", "保健所・保健センター職員", "家族", "その他"],
    "reception_method": ["書面", "Fax", "面会", "mail", "電話", "その他"],
    "interview_location": ["1", "2", "3"],
    "cm_24h": ["0", "1"],
    "kaigo_24h": ["0", "1"],
    "kangoshi_24h": ["0", "1"],
    "care_status_nursing": ["要介護1","要介護2","要介護3","要介護4","要介護5"],
    "my_number_card": ["あり","なし"],
    "participant": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"],
    # form2 用マスタ
    "expensive_cost_usage": ["0","1a","1b","2a","2b"],
    "public_medical_usage": ["0","1","2"],
    "economic_status_1": ["1","2","3","4","5"],
    "economic_status_2": ["1","2","3","4","5"],
    # form3 用マスタ
    "residence_type": ["house_1f","house_2f","apartment"],
    "elevator": ["あり","不要"],
    "entrance_to_road": ["危険あり","問題なし"],
    "reform_need": ["0","1"],
    "care_tool_need": ["0","1"],
    "equipment_need": ["0","1"],
    "social_service_usage": ["0","1","2","3"],
    # form3 追加マスタ（改修内容のプルダウン類）
    "reform_place": ["居室","浴室","脱衣室","浴槽","トイレ","便器","廊下","玄関","庭","階段","その他"],
    "care_tool_type": ["移動用具","生活用具","介助用具"],
    "equipment_type": ["障害者用生活用具","電気","冷暖房機","エレベータ","その他"],
    # form1 用マスタ
    "housing_type": [
        "自宅","アパート","一般マンション","高齢者マンション","グループホーム","借間","福祉施設","生活訓練施設","入所授産施設","その他"
    ],
    "user_burden_ratio": ["1割","2割","3割"],
    "care_status": ["要支援1","要支援2","要介護1","要介護2","要介護3","要介護4","要介護5"],
    "dementia_level": ["自立","Ⅰ","Ⅱa","Ⅱb","Ⅲa","Ⅲb","Ⅳ","M"],
    "elderly_independence_level": ["自立","J1","J2","A1","A2","B1","B2","C1","C2"],
    "insurance_type": ["本人","家族"],
    "insurance_category": ["国保","社保","共済","労災","後期高齢者医療","その他"],
    "kouki_kourei_burden": ["1割","2割","3割"],
    # 介護負担（1〜4）: 値はUIの数値をそのまま保持
    "care_burden_1": ["1","2","3","4","5"],
    "care_burden_2": ["1","2","3","4","5"],
    "care_burden_3": ["1","2","3","4","5"],
    "care_burden_4": ["1","2","3","4","5"],
    "support_type_1": ["キーパーソン","主介護者"],
    "support_type_2": ["キーパーソン","主介護者"],
    "living_status_1": ["同居","同居日中不在","別居"],
    "living_status_2": ["同居","同居日中不在","別居"],
    "living_status_3": ["同居","同居日中不在","別居"],
    "living_status_4": ["同居","同居日中不在","別居"],
    # care_burden_* は UI では値が 1〜5 の数値で送られるため、
    # CHOICE_MASTER は数値版（上の定義）を使用する。日本語版は使用しない。
    # form4 用マスタ
    "care_burden_feeling": ["0","1","2","3","4"],
    "care_burden_health": ["0","1","2","3","4"],
    "care_burden_life": ["0","1","2","3","4"],
    "care_burden_work": ["0","1","2","3","4"],
    "care_intention": ["0","1","2","3","4","5"],
    # form4 追加マスタ（Ⅱ 介護の実態 → one-hot 展開）
    "abuse_injury": ["0","1","2","3","4"],
    "neglect_hygiene": ["0","1","2","3","4"],
    "psychological_abuse": ["0","1","2","3","4"],
    "neglect_care": ["0","1","2","3","4"],
    "sexual_abuse": ["0","1","2","3","4"],
    "financial_abuse": ["0","1","2","3","4"],
    # form5 用マスタ
    "social_participation_1": ["a","b","c","d"],
    "enjoyment_1": ["あり","なし"],
    "enjoyment_2": ["あり","なし"],
    "enjoyment_3": ["あり","なし"],
    "relationship_status": ["1","2","3","4"],
    "consultation_status": ["1","2"],
    # form6 用マスタ
    "alcohol_problem": ["0","1","2","3"],
    "who_alcohol_criteria": ["1","2","3","4","5","6","7","8"],
    "smoking_habit": ["0","1"],
    "sleep_quality": ["0","1","2","3"],
    "fatigue": ["0","1"],
    "allergy": ["0","1"],
    "disease_within_year": ["0","1"],
    "disease_type": ["a","b","c","d","e","f","g","h","i","j"],
    "vaccination_status": ["0","1"],
    "vaccination": ["a","b","c","d","e","f","h"],
    "infection_control": ["0","1","2","3","4"],
    # form6 追加詳細マスタ
    "fatigue_detail": ["だるい","疲れやすい","疲れが残ってる","慢性的に疲れている"],
    "allergy_detail": ["花粉症","食物アレルギー","ハウスダスト","薬物","その他"],
    # form7 用マスタ
    "bmi_category": ["0","1","2","3","4","5","6","7","8"],
    "weight_change": ["0","1","2","3"],
    "nutrition_self_management": ["0","1","2","3","4","a","b","c","d","e","f","g","h","i"],
    "dietary_therapy": ["0","1"],
    "food_form": ["0","1","2","3","4","5","6"],
    "meal_frequency": ["0","1","2","3"],
    "meal_with_others": ["0","1","2"],
    "water_intake": ["0","1","2","3"],
    "swallowing": ["0","1","2","3","4"],
    "oral_teeth_gum": ["0","1","2"],
    "oral_saliva_flow": ["0","1","2"],
    "oral_dryness": ["0","1","2"],
    "oral_saliva": ["0","1","2"],
    "oral_tongue": ["0","1","2"],
    "oral_tongue_surface": ["0","1","2"],
    "oral_mucosa": ["0","1"],
    "oral_gum": ["0","1","2"],
    # form8 用マスタ
    "urination_status": ["0","1"],
    "urination": ["0","1"],
    "urination_frequency": ["0","1","2","3"],
    "urination_control": ["0","1","2","3"],
    "defecation_status": ["0","a","b","c","d","e"],
    "defecation_frequency": ["0","1","2"],
    "defecation_control": ["0","1","2","3","4"],
    "defecation_method": ["0","1","2","3","4"],
    "excretion_method": ["A","B","C","D","E","F"],
    "skin_nail_care": ["0","1","2","3"],
    "bedsore_wound": ["0","1","2","3"],
    "skin_condition": ["0","1","2"],
    # form10 用マスタ
    "communication_level": ["0","1","2","3"],
    "conversation_level": ["0","1","2","3"],
    "hearing_level": ["0","1","2","3","4"],
    "daily_communication": ["0","1","2","3"],
    "daily_judgement": ["0","1","2","3"],
    "delirium_signs_exist": ["0","1"],
    "delirium_signs": ["a","b","c","d","e"],
    "visual_ability": ["0","1","2","3"],
    "visual_condition": ["0","1","a","b","c","d","e"],
    # form11 用マスタ
    "emotion_level": ["0","1","2","3","4"],
    "m_health_1": ["1","2"],
    "m_health_2": ["1","2"],
    "m_health_3": ["1","2"],
    "m_health_4": ["1","2"],
    "m_health_5": ["1","2"],
    "m_health_6": ["1","2"],
    "m_health_7": ["1","2"],
    "m_health_8": ["1","2"],
    # form12 用マスタ
    "information_provider": ["1","2","3","4","5","6"],
    "npiq_delusion": ["0","1","2","3"],
    "npiq_hallucination": ["0","1","2","3"],
    "npiq_agitation": ["0","1","2","3"],
    "npiq_depression": ["0","1","2","3"],
    "npiq_anxiety": ["0","1","2","3"],
    "npiq_euphoria": ["0","1","2","3"],
    "npiq_apathy": ["0","1","2","3"],
    "npiq_disinhibition": ["0","1","2","3"],
    "npiq_irritability": ["0","1","2","3"],
    "npiq_abnormal_behavior": ["0","1","2","3"],
    "npiq_night_behavior": ["0","1","2","3"],
    "npiq_eating_behavior": ["0","1","2","3"],
    # form15 用マスタ
    "strange_feeling": ["0","1"],
    "vital_respiration": ["0","1"],
    "vital_spo2": ["0","1"],
    "vital_temp": ["0","1"],
    "vital_bp": ["0","1"],
    "vital_pulse": ["0","1"],
    "consciousness_level": ["0","1","2"],
    "skin_changes": ["0","1"],
    "dyspnea_grade": ["0","1","2","3","4"],
    "nyha_class": ["0","I","II","III","IV"],
    # form16 用マスタ（褥瘡評価）
    "wound_depth": ["d0","d1","d2","d3","d4","d5","dti","du"],
    "wound_exudate": ["e0","e1","e3","e6"],
    "wound_size": ["s0","s3","s6","s8","s9","s12","s15"],
    "wound_infection": ["i0","i1","i3","i3c","i9"],
    "wound_granulation": ["g0","g1","g3","g4","g5","g6"],
    "wound_necrosis": ["n0","n3","n6"],
    "wound_pocket": ["p0","p6","p6_4to16","p12","p24"],
    # form9 用マスタ（ADL/IADL）
    "basic1_eating": ["0","1","2","3","4","5"],
    "basic1_face_hair": ["0","1","2","3","4","5"],
    "basic1_wipe": ["0","1","2","3","4","5"],
    "basic1_upper_clothes": ["0","1","2","3","4","5"],
    "basic1_lower_clothes": ["0","1","2","3","4","5"],
    "basic1_toilet": ["0","1","2","3","4","5"],
    "basic1_bath": ["0","1","2","3","4","5"],
    "basic2_stand": ["0","1","2","3","4","5"],
    "basic2_getup": ["0","1","2","3","4","5"],
    "basic2_sit": ["0","1","2","3","4","5"],
    "basic2_bed_chair_stand": ["0","1","2","3","4","5"],
    "basic2_both_leg_stand": ["0","1","2","3","4","5"],
    "basic3_transfer": ["0","1","2","3","4","5"],
    "basic3_bath_inout": ["0","1","2","3","4","5"],
    "basic3_walk_home": ["0","1","2","3","4","5"],
    "basic3_walk_out": ["0","1","2","3","4","5"],
    "iadl_phone": ["0","1","2","3"],
    "iadl_shopping": ["0","1","2","3"],
    "iadl_housework": ["0","1","2","3"],
    "iadl_toilet": ["0","1","2","3"],
    "iadl_clean": ["0","1","2","3"],
    "iadl_move": ["0","1","2","3","4"],
    "iadl_money": ["0","1","2","3"],
    "iadl_medicine": ["0","1","2","3"],
    "iadl_decision": ["0","1","2","3"],
}

# ------------------------------------------------------------
# 🔹 form0 固定スキーマ（列順）と one-hot エイリアス
# ------------------------------------------------------------
FORM0_ORDER = [
    # 基本
    "timestamp",
    "office_id",
    "personal_id",
    "user_id",

    # 生年月日・年齢
    "birth_year","birth_month","birth_day","age",

    # 性別 one-hot
    "sex_male","sex_female","sex_unspecified","sex_NA",

    # 依頼経路 one-hot
    "request_route_CM","request_route_MSW","request_route_hospital_doctor","request_route_hospital_ns",
    "request_route_private_doctor","request_route_welfare_staff","request_route_health_center",
    "request_route_family","request_route_other",

    # 依頼情報
    "request_organization","requestor_name","requestor_tel","requestor_fax","requestor_email",

    # 受付日時
    "reception_year","reception_month","reception_day",
    "reception_hour","reception_minute",
    "reception_staff",

    # 受付方法 one-hot
    "reception_method_document","reception_method_fax","reception_method_meeting",
    "reception_method_mail","reception_method_phone","reception_method_other",

    # 依頼理由
    "request_reason",

    # 評価区分（1〜5）
    "assessment_first_year","assessment_first_month","assessment_first_day",
    "assessment_regular_year","assessment_regular_month","assessment_regular_day",
    "assessment_worsen_year","assessment_worsen_month","assessment_worsen_day",
    "assessment_discharge_year","assessment_discharge_month","assessment_discharge_day",
    "assessment_admission_year","assessment_admission_month","assessment_admission_day",

    # 参加者 one-hot
    "participant_1","participant_2","participant_3","participant_4","participant_5",
    "participant_6","participant_7","participant_8","participant_9","participant_10",

    # 面談場所
    "interview_location_home","interview_location_facility","interview_location_other_flag",
    "interview_location_other_text",

    # 24h 対応
    "cm_24h_no","cm_24h_yes","kaigo_24h_no","kaigo_24h_yes","kangoshi_24h_no","kangoshi_24h_yes",

    # 終了年月日
    "end_year","end_month","end_day",

    # サマリー
    "summary_recorder","exit_summary",
]


_FORM0_TEXT_COLS = {
    # 空欄は0ではなく空文字で保存したいテキスト/日付系
    "interview_location_other_text",
    "end_year","end_month","end_day",
    "summary_recorder","exit_summary",
}


FORM0_ONEHOT_ALIASES = {
    "sex": {
        "男": "male", "女": "female", "指定なし": "unspecified", "NA": "NA",
    },
    "request_route": {
        "CM": "CM", "MSW": "MSW",
        "病院医師": "hospital_doctor", "病院NS": "hospital_ns", "開業医師": "private_doctor",
        "福祉職員": "welfare_staff", "保健所・保健センター職員": "health_center",
        "家族": "family", "その他": "other",
    },
    "reception_method": {
        "書面": "document",
        "Fax": "fax",
        "面会": "meeting",
        "mail": "mail",
        "電話": "phone",
        "その他": "other",
    },
    "interview_location": {
        "1": "home", "2": "facility", "3": "other_flag",
        "自宅": "home", "入院施設": "facility", "その他": "other_flag",
    },
    "cm_24h": { "0": "no", "1": "yes" },
    "kaigo_24h": { "0": "no", "1": "yes" },
    "kangoshi_24h": { "0": "no", "1": "yes" },
}

def _form0_apply_aliases_and_order(row: dict) -> dict:
    """form0: one-hotキーの日本語・数値サフィックスを英語化し、列順を固定する。
    - 未存在列は 0 を補完（timestamp/user_id は空文字許容）
    """
    # 生値（base）だけが来た場合でも one-hot を補完してからエイリアス変換する
    def _ensure_one_hot_from_raw(target: dict, bases: list[str]) -> None:
        for base in bases:
            prefix = base + "_"
            # 既に one-hot があればスキップ
            if any(k.startswith(prefix) for k in target.keys()):
                continue
            if base not in target:
                continue
            choices = CHOICE_MASTER.get(base)
            if not choices:
                continue
            val = str(target.get(base, "")).strip()
            for choice in choices:
                target[f"{base}_{choice}"] = 1 if val == str(choice) else 0
            # 生値は不要
            target.pop(base, None)

    _ensure_one_hot_from_raw(
        row,
        [
            "sex",
            "request_route",
            "reception_method",
            "interview_location",
            "cm_24h",
            "kaigo_24h",
            "kangoshi_24h",
        ],
    )

    # one-hot のサフィックス置換
    for base, mapping in FORM0_ONEHOT_ALIASES.items():
        prefix = base + "_"
        for k in list(row.keys()):
            if not k.startswith(prefix):
                continue
            token = k[len(prefix):]
            alias = mapping.get(str(token))
            if alias:
                row[f"{base}_{alias}"] = row.pop(k)

    # 「面談場所: その他」の記述欄を固定名にエイリアス
    if "interview_location_other_text" not in row and "interview_location_other" in row:
        row["interview_location_other_text"] = row.get("interview_location_other", "")

    # 列順固定と欠損補完
    phone_like_cols = {"requestor_tel", "requestor_fax"}
    out: dict = {}
    for col in FORM0_ORDER:
        if col in ("timestamp", "user_id"):
            out[col] = row.get(col, "")
        else:
            # サマリー系・日付系・自由記述は空欄なら空文字のまま
            if col in _FORM0_TEXT_COLS:
                v = row.get(col, "")
            else:
                v = row.get(col, 0)
                if isinstance(v, str) and v.strip() == "":
                    v = 0
            # 電話・FaxはExcelで先頭0が落ちないよう文字列化（'0800… 形式）
            if col in phone_like_cols:
                sval = "" if v is None else str(v)
                if sval != "" and not sval.startswith("'"):
                    # 先頭0 または 全数字は文字列として扱う
                    if (len(sval) > 0 and sval[0] == "0") or sval.isdigit():
                        v = "'" + sval
                    else:
                        v = sval
            out[col] = v
    return out


# ------------------------------------------------------------
# 🔹 form1 固定スキーマと one-hot エイリアス
# ------------------------------------------------------------
FORM1_ORDER = [
    # 基本
    "timestamp",
    "office_id",
    "user_id",

    # 住居形態
    "housing_type_home","housing_type_apartment","housing_type_mansion","housing_type_senior_mansion",
    "housing_type_group_home","housing_type_rented","housing_type_welfare","housing_type_rehab",
    "housing_type_employment_facility","housing_type_other_flag","housing_type_other",

    # 介護保険（第1）
    "insurer_name",
    "user_burden_ratio_1割","user_burden_ratio_2割","user_burden_ratio_3割",

    # 認定日・有効期間
    "certification_year","certification_month","certification_day",
    "valid_start_year","valid_start_month","valid_start_day",
    "valid_end_year","valid_end_month","valid_end_day",

    # 要介護度
    "care_status_要支援1","care_status_要支援2",
    "care_status_nursing_要介護1","care_status_nursing_要介護2",
    "care_status_nursing_要介護3","care_status_nursing_要介護4","care_status_nursing_要介護5",

    # 支給限度額
    "benefit_limit",

    # 認知症高齢者の日常生活自立度
    "dementia_level_自立","dementia_level_Ⅰ","dementia_level_Ⅱa","dementia_level_Ⅱb",
    "dementia_level_Ⅲa","dementia_level_Ⅲb","dementia_level_Ⅳ","dementia_level_M",

    # 生活自立度
    "elderly_independence_level_自立",
    "elderly_independence_level_J1","elderly_independence_level_J2",
    "elderly_independence_level_A1","elderly_independence_level_A2",
    "elderly_independence_level_B1","elderly_independence_level_B2",
    "elderly_independence_level_C1","elderly_independence_level_C2",

    # 医療保険（第2）
    "insurer_name_medical",
    "insurance_type_self","insurance_type_family",
    "insurance_category_national","insurance_category_social","insurance_category_mutual",
    "insurance_category_labor","insurance_category_elderly",
    "kouki_kourei_burden_1割","kouki_kourei_burden_2割","kouki_kourei_burden_3割",
    "insurance_category_other_flag","insurance_other_detail",

    # マイナンバーカード
    "my_number_card_yes","my_number_card_no",

    # 主治医意見書
    "doctor_opinion",

    # 支援者1
    "support_type_1_keyperson","support_type_1_maincaregiver",
    "living_status_1_samehouse","living_status_1_dayabsent","living_status_1_separate",
    "care_burden_1_working","care_burden_1_studying","care_burden_1_elderly",
    "care_burden_1_disabled","care_burden_1_pregnant",

    # 支援者2
    "support_type_2_keyperson","support_type_2_maincaregiver",
    "living_status_2_samehouse","living_status_2_dayabsent","living_status_2_separate",
    "care_burden_2_working","care_burden_2_studying","care_burden_2_elderly",
    "care_burden_2_disabled","care_burden_2_pregnant",

    # 支援者3
    "care_sharing_3",
    "living_status_3_samehouse","living_status_3_dayabsent","living_status_3_separate",
    "care_burden_3_working","care_burden_3_studying","care_burden_3_elderly",
    "care_burden_3_disabled","care_burden_3_pregnant",

    # 支援者4
    "care_sharing_4",
    "living_status_4_samehouse","living_status_4_dayabsent","living_status_4_separate",
    "care_burden_4_working","care_burden_4_studying","care_burden_4_elderly",
    "care_burden_4_disabled","care_burden_4_pregnant",

    # 家系図
    "genogramCanvas_image",
    "genogram_file","genogram_url",

    # 記述欄
    "user_requests","family_requests",
]


_FORM1_TEXT_COLS = {
    "insurer_name",
    "insurer_name_medical",
    "insurance_other_detail",
    "housing_type_other",
    "user_requests",
    "family_requests",
    "genogramCanvas_image",
    "genogram_file",
    "genogram_url",
    "doctor_opinion",
}

FORM1_ONEHOT_ALIASES = {
    "housing_type": {
        "自宅": "home","アパート": "apartment","一般マンション": "mansion","高齢者マンション": "senior_mansion",
        "グループホーム": "group_home","借間": "rented","福祉施設": "welfare","生活訓練施設": "rehab",
        "入所授産施設": "employment_facility","その他": "other_flag",
    },
    "user_burden_ratio": {"1割": "1割", "2割": "2割", "3割": "3割"},
    "care_status": {
        "要支援1": "要支援1","要支援2": "要支援2",
    },
    "care_status_nursing": {
        "要介護1": "nursing_要介護1",
        "要介護2": "nursing_要介護2",
        "要介護3": "nursing_要介護3",
        "要介護4": "nursing_要介護4",
        "要介護5": "nursing_要介護5",
    },
    "dementia_level": {
        "自立": "自立","Ⅰ": "Ⅰ","Ⅱa": "Ⅱa","Ⅱb": "Ⅱb","Ⅲa": "Ⅲa","Ⅲb": "Ⅲb","Ⅳ": "Ⅳ","M": "M",
    },
    "elderly_independence_level": {
        "自立": "自立","J1": "J1","J2": "J2","A1": "A1","A2": "A2","B1": "B1","B2": "B2","C1": "C1","C2": "C2",
    },
    "insurance_type": {"本人": "self", "家族": "family"},
    "insurance_category": {
        "国保": "national","社保": "social","共済": "mutual","労災": "labor","後期高齢者医療": "elderly","その他": "other_flag",
    },
    "kouki_kourei_burden": {"1割": "1割", "2割": "2割", "3割": "3割"},
    "my_number_card": {"あり": "yes", "なし": "no"},
    "support_type_1": {"キーパーソン": "keyperson", "主介護者": "maincaregiver"},
    "support_type_2": {"キーパーソン": "keyperson", "主介護者": "maincaregiver"},
    "living_status_1": {"同居": "samehouse", "同居日中不在": "dayabsent", "別居": "separate"},
    "living_status_2": {"同居": "samehouse", "同居日中不在": "dayabsent", "別居": "separate"},
    "living_status_3": {"同居": "samehouse", "同居日中不在": "dayabsent", "別居": "separate"},
    "living_status_4": {"同居": "samehouse", "同居日中不在": "dayabsent", "別居": "separate"},
    "care_burden_1": {"就労中": "working", "就学中": "studying", "高齢": "elderly", "要介護等": "disabled", "妊娠育児": "pregnant",
                      "1": "working", "2": "studying", "3": "elderly", "4": "disabled", "5": "pregnant"},
    "care_burden_2": {"就労中": "working", "就学中": "studying", "高齢": "elderly", "要介護等": "disabled", "妊娠育児": "pregnant",
                      "1": "working", "2": "studying", "3": "elderly", "4": "disabled", "5": "pregnant"},
    "care_burden_3": {"就労中": "working", "就学中": "studying", "高齢": "elderly", "要介護等": "disabled", "妊娠育児": "pregnant",
                      "1": "working", "2": "studying", "3": "elderly", "4": "disabled", "5": "pregnant"},
    "care_burden_4": {"就労中": "working", "就学中": "studying", "高齢": "elderly", "要介護等": "disabled", "妊娠育児": "pregnant",
                      "1": "working", "2": "studying", "3": "elderly", "4": "disabled", "5": "pregnant"},
}

def _form1_apply_aliases_and_order(row: dict) -> dict:
    """form1: one-hotキーを英語化し、指定列のみ順序固定で返す（timestamp は更新保持）。"""
    # フォーム1の主要な単一選択項目が「生値」で来た場合に one-hot を補完
    def _ensure_one_hot_bases(target: dict, bases: list[str]) -> None:
        for base in bases:
            # 既に one-hot が1つでもある場合はスキップ
            prefix = base + "_"
            if any(k.startswith(prefix) for k in target.keys()):
                continue
            # 生値が無ければスキップ
            if base not in target:
                continue
            # CHOICE_MASTER に定義がある場合のみ one-hot 展開
            choices = CHOICE_MASTER.get(base)
            if not choices:
                continue
            val = str(target.get(base, "")).strip()
            # レガシー値の補正（UIの古い選択肢名が送られても正規化して受け入れる）
            if base == "housing_type":
                legacy_map = {
                    "老健施設": "生活訓練施設",   # 旧誤記 → 正
                    "入所療養施設": "入所授産施設", # 旧誤記 → 正
                    "自宿舎": "借間",           # デモ版の表記ゆれ
                }
                if val in legacy_map:
                    val = legacy_map[val]
                    target[base] = val
            # care_status は「要介護x」を nursing 側へ振り分け
            if base == "care_status" and val.startswith("要介護"):
                for choice in ["要介護1","要介護2","要介護3","要介護4","要介護5"]:
                    target[f"care_status_nursing_{choice}"] = 1 if val == choice else 0
            else:
                for choice in choices:
                    target[f"{base}_{choice}"] = 1 if val == str(choice) else 0
            # 生値は不要
            target.pop(base, None)

    _ensure_one_hot_bases(
        row,
        [
            "housing_type",
            "user_burden_ratio",
            "care_status",
            "care_status_nursing",
            "dementia_level",
            "elderly_independence_level",
            "insurance_type",
            "insurance_category",
            "my_number_card",
            "support_type_1",
            "support_type_2",
            # living_status_1..4 は個別ベース
            "living_status_1",
            "living_status_2",
            "living_status_3",
            "living_status_4",
        ],
    )

    # one-hot のサフィックス置換
    for base, mapping in FORM1_ONEHOT_ALIASES.items():
        prefix = base + "_"
        for k in list(row.keys()):
            if not k.startswith(prefix):
                continue
            token = k[len(prefix):]
            alias = mapping.get(str(token))
            if alias:
                # care_status_nursing は alias に "nursing_" を含める指定があるが、
                # ベースに既に "care_status_nursing" を持つため二重化を避ける
                if base == "care_status_nursing" and str(alias).startswith("nursing_"):
                    alias = alias[len("nursing_"):]
                row[f"{base}_{alias}"] = row.pop(k)

    # 後期高齢者医療の負担割合プルダウンを確実に one-hot 化
    # - ペイロードに raw 値 'kouki_kourei_burden' が来た場合は 1/0 に展開
    # - 'insurance_category_elderly' が 1 の場合、未選択でも列を 0 で出力
    burden_choices = ["1割", "2割", "3割"]
    if "kouki_kourei_burden" in row and not any(
        f"kouki_kourei_burden_{c}" in row for c in burden_choices
    ):
        val = str(row.get("kouki_kourei_burden", "")).strip()
        for c in burden_choices:
            row[f"kouki_kourei_burden_{c}"] = 1 if val == c else 0
        # 生値は不要
        row.pop("kouki_kourei_burden", None)
    # 高齢者医療が選択されているが負担割合列が未生成なら 0 埋め
    if row.get("insurance_category_elderly", 0) == 1:
        for c in burden_choices:
            row.setdefault(f"kouki_kourei_burden_{c}", 0)

    # care_burden(1〜4) のフォールバック one-hot（生値が来た場合の保険）
    care_burden_alias = {"1": "working", "2": "studying", "3": "elderly", "4": "disabled", "5": "pregnant"}
    for i in ("1", "2", "3", "4"):
        raw_key = f"care_burden_{i}"
        # 既に one-hot 済みならスキップ
        if any(k.startswith(raw_key + "_") for k in row.keys()):
            continue
        if raw_key in row:
            val = str(row.get(raw_key, "")).strip()
            for num, alias in care_burden_alias.items():
                row[f"{raw_key}_{alias}"] = 1 if val == num else 0
            row.pop(raw_key, None)

    # care_status, care_status_nursing のフォールバック one-hot
    # 支援レベル（要支援1/2）
    if "care_status" in row and not any(k.startswith("care_status_") for k in row.keys()):
        val = str(row.get("care_status", "")).strip()
        for choice in ["要支援1", "要支援2", "要介護1", "要介護2", "要介護3", "要介護4", "要介護5"]:
            if choice.startswith("要支援"):
                row[f"care_status_{choice}"] = 1 if val == choice else 0
            else:
                # 介護レベルがここに来た場合は nursing 側へ振り分け
                row[f"care_status_nursing_{choice}"] = 1 if val == choice else 0
        row.pop("care_status", None)
    # 介護レベル（要介護1〜5）
    if "care_status_nursing" in row and not any(k.startswith("care_status_nursing_") for k in row.keys()):
        val = str(row.get("care_status_nursing", "")).strip()
        for choice in ["要介護1", "要介護2", "要介護3", "要介護4", "要介護5"]:
            row[f"care_status_nursing_{choice}"] = 1 if val == choice else 0
        row.pop("care_status_nursing", None)

    out: dict = {"timestamp": row.get("timestamp", "")}
    for col in FORM1_ORDER:
        if col in _FORM1_TEXT_COLS:
            out[col] = row.get(col, "")
        else:
            v = row.get(col, 0)
            if isinstance(v, str) and v.strip() == "":
                v = 0
            out[col] = v
    return out


# ------------------------------------------------------------
# 🔹 form2 固定スキーマ（列順のみ）
# ------------------------------------------------------------
FORM2_ORDER = [
    "activity_6_8","activity_8_10","activity_10_12","activity_12_14","activity_14_16","activity_16_18","activity_18_20","activity_20_22","activity_22_6",
    "expensive_cost_usage_0","expensive_cost_usage_1a","expensive_cost_usage_1b","expensive_cost_usage_2a","expensive_cost_usage_2b",
    "expensive_cost_no_reason","expensive_cost_reason",
    "public_medical_usage_0","public_medical_usage_1","public_medical_usage_2",
    # ご要望の並び（エイリアス列群）
    "public_medical_detail1a","public_medical_detail1b","public_medical_detail1c","public_medical_detail1d",
    "public_medical_detail2a","public_medical_detail2b","public_medical_detail2c",
    "public_medical_detail3","public_medical_detail4","public_medical_detail5",
    "public_medical_detail1d_reason","public_medical_detail2c_reason","public_medical_detail5_reason",
    "public_medical_usage_2_reason",
    "public_system_use_detail0","public_system_use_detail1","public_system_use_detail2",
    "public_system_detail_1_1","public_system_detail_1_2","public_system_detail_1_3","public_system_detail_1_4","public_system_detail_1_5","public_system_detail_1_6",
    "option_detail_1","option_detail_2","option_detail_3",
    "public_system2_reason",
    # 経済的状況
    "economic_status_1_1","economic_status_1_2","economic_status_1_3","economic_status_1_4","economic_status_1_5",
    "economic_status_2_1","economic_status_2_2","economic_status_2_3","economic_status_2_4","economic_status_2_5",
    "economic_status_3_food","economic_status_3_medical","economic_status_3_care","economic_status_3_transport",
    "economic_status_3_housing","economic_status_3_utilities","economic_status_3_leisure","economic_status_3_other_flag",
    "economic_status_3_difficulties_other",
]

# --- 追加: activity列を明示的に列挙してテキスト強制 ---
ACTIVITY_COLS = [
    "activity_6_8","activity_8_10","activity_10_12","activity_12_14",
    "activity_14_16","activity_16_18","activity_18_20","activity_20_22","activity_22_6",
]

_FORM2_TEXT_COLS = frozenset({
    *ACTIVITY_COLS,
    "expensive_cost_no_reason","expensive_cost_reason",
    "option_detail_1","option_detail_2","option_detail_3",
    "public_medical_detail_other","medical_disease_name",
    # 経済(3)の「その他」自由記述はテキスト扱い
    "economic_status_3_difficulties_other",
    # 追加: 理由メモの別名列はテキスト扱い
    "public_medical_detail1d_reason","public_medical_detail2c_reason","public_medical_detail5_reason",
    "public_medical_usage_2_reason","public_system2_reason",
})

def _form2_apply_order(row: dict) -> dict:
    # 単一要素リストをスカラーへ正規化（例: ["1"] → "1")
    for k, v in list(row.items()):
        if isinstance(v, list) and len(v) == 1:
            row[k] = v[0]

    # 一時デバッグ: activity 系の生データとテキスト列判定を確認
    try:
        print("▶ raw activity sample:", {k: row.get(k) for k in (ACTIVITY_COLS if 'ACTIVITY_COLS' in globals() else [])})
        print("▶ TEXT set contains activity_6_8?:", ("activity_6_8" in _FORM2_TEXT_COLS) if '_FORM2_TEXT_COLS' in globals() else False)
    except Exception:
        pass
    # form2: UI差異に由来するキーを正規化
    # 1) 公費医療の詳細（ドロップダウン） → one-hot（public_medical_detail_1..6）
    if "public_medical_detail_dropdown" in row and not any(
        (f"public_medical_detail_{i}" in row) for i in ("1","2","3","4","5","6")
    ):
        val = str(row.get("public_medical_detail_dropdown", "")).strip()
        for i in ("1","2","3","4","5","6"):
            row[f"public_medical_detail_{i}"] = 1 if val == i else 0
        # 生値は不要
        row.pop("public_medical_detail_dropdown", None)

    # 2) 公費医療・チェックボックスの別名補正（3 → 3_check）
    if "public_medical_detail_3" in row and "public_medical_detail_3_check" not in row:
        try:
            row["public_medical_detail_3_check"] = row.get("public_medical_detail_3", 0)
            del row["public_medical_detail_3"]
        except Exception:
            pass

    # 3) 経済的状況(3) チェックボックス（日本語）→ 固定英語列へ
    # _flatten_payload により economic_status_3_difficulties_* が立っている場合を集約
    econ_map = {
        "食料": "food",
        "医療": "medical",
        "介護": "care",
        "交通･電話": "transport",
        "住宅": "housing",
        "光熱水": "utilities",
        "教養娯楽": "leisure",
        "その他": "other_flag",
    }
    # 既に目標列がひとつも無い場合のみ、補完して立てる
    if not any(k.startswith("economic_status_3_") and k.split("_")[-1] in econ_map.values() for k in row.keys()):
        # いったん全部0に初期化
        for suffix in econ_map.values():
            row[f"economic_status_3_{suffix}"] = 0
        # 立っている difficulties_* 列を走査して1にする
        for k, v in list(row.items()):
            if not k.startswith("economic_status_3_difficulties_"):
                continue
            # 自由記述のテキスト欄は one-hot 集約対象から除外（値はそのままCSVへ出す）
            if k == "economic_status_3_difficulties_other":
                continue
            # 値が 1 と見なせる時のみ反映
            flag = 0
            try:
                flag = int(str(v)) if str(v).strip() != "" else 0
            except Exception:
                flag = 1 if v else 0
            token = k[len("economic_status_3_difficulties_"):]
            alias = econ_map.get(token)
            if alias:
                row[f"economic_status_3_{alias}"] = 1 if flag else 0
            # 中間生成列は削除
            if k != "economic_status_3_difficulties_other": del row[k]

    # --- ここを追加：activity系は必ず文字列で固定 ---
    for col in ACTIVITY_COLS:
        if col in row:
            row[col] = "" if row[col] is None else str(row[col])

    out: dict = {"timestamp": row.get("timestamp", "")}
    for col in FORM2_ORDER:
        if col in _FORM2_TEXT_COLS:
            out[col] = "" if row.get(col) is None else str(row.get(col, ""))
        else:
            v = row.get(col, 0)
            if isinstance(v, str) and v.strip() == "":
                v = 0
            out[col] = v
    # 入力制御: 2b（expensive_cost_usage_2b）が未選択なら、expensive_cost_reason は空にする
    try:
        if out.get("expensive_cost_usage_2b", 0) != 1:
            out["expensive_cost_reason"] = ""
    except Exception:
        pass
    # 別名列の値を補完（既存の列からコピー）
    try:
        def flag(k: str) -> int:
            return 1 if str(out.get(k, 0)) not in ("", "0", "false", "False") else 0
        # public_medical_detail の別名
        out["public_medical_detail1a"] = flag("public_medical_detail_1a")
        out["public_medical_detail1b"] = flag("public_medical_detail_1b")
        out["public_medical_detail1c"] = flag("public_medical_detail_1c")
        out["public_medical_detail1d"] = flag("public_medical_detail_1d")
        out["public_medical_detail2a"] = flag("public_medical_detail_2a")
        out["public_medical_detail2b"] = flag("public_medical_detail_2b")
        out["public_medical_detail2c"] = flag("public_medical_detail_2c")
        out["public_medical_detail3"]  = flag("public_medical_detail_3_check")
        out["public_medical_detail4"]  = flag("public_medical_detail_4")
        out["public_medical_detail5"]  = flag("public_medical_detail_5")
        # 理由メモの補完
        def _as_text(value) -> str:
            return "" if value is None else str(value)

        reason = _as_text(out.get("public_medical_reason", ""))
        detail1d_reason = _as_text(out.get("public_medical_detail1d_reason", "")) or reason
        detail2c_reason = _as_text(out.get("public_medical_detail2c_reason", "")) or reason
        detail5_reason  = _as_text(out.get("public_medical_detail5_reason", ""))  or reason
        out["public_medical_detail1d_reason"] = detail1d_reason
        out["public_medical_detail2c_reason"] = detail2c_reason
        out["public_medical_detail5_reason"]  = detail5_reason
        # --- 公費医療の自由記述欄を public_system_use_detail0〜2 にマッピング ---
        out["public_system_use_detail0"] = _as_text(row.get("infection_other_reason", ""))
        out["public_system_use_detail1"] = _as_text(row.get("public_medical_2c_other_reason", ""))
        out["public_system_use_detail2"] = _as_text(row.get("specified_rare_disease_name", ""))
        # --- 公費制度の記述欄を option_detail_1〜3 にマッピング ---
        out["option_detail_1"] = _as_text(row.get("public_system_handbook_detail", ""))
        out["option_detail_2"] = _as_text(row.get("public_system_handbook_grade", ""))
        out["option_detail_3"] = _as_text(row.get("public_system_mental_handbook_detail", ""))
        out["public_medical_usage_2_reason"]  = reason
        # --- 公費制度の「利用しない理由」を反映 ---
        out["public_system2_reason"] = _as_text(row.get("public_system_no_use_reason_detail", ""))

        # --- 公費制度の利用チェック（public_system_types[]）を one-hot 展開 ---
        system_map = {
            "障害手帳": "public_system_detail_1_1",
            "身障手帳（程度）": "public_system_detail_1_2",
            "精神障害者保健福祉手帳": "public_system_detail_1_3",
            "障害福祉サービス受給者証": "public_system_detail_1_4",
            "生活保護": "public_system_detail_1_5",
            "障害者年金": "public_system_detail_1_6",
        }

        # すべて初期化（0にリセット）
        for col in system_map.values():
            out[col] = 0

        # name="public_system_types[]" または public_system_types どちらも対応
        selected_systems = (
            row.get("public_system_types")
            or row.get("public_system_types[]")
            or []
        )

        # JSON形式でも文字列でも配列に変換
        if isinstance(selected_systems, str):
            import json
            try:
                parsed = json.loads(selected_systems)
                if isinstance(parsed, list):
                    selected_systems = parsed
                else:
                    selected_systems = [parsed]
            except Exception:
                selected_systems = [selected_systems]

        # チェックされている項目をマッピング
        for v in selected_systems:
            if v in system_map:
                out[system_map[v]] = 1
    except Exception:
        pass
    try:
        print("🟠 after form2_apply_order:", {k: out[k] for k in out.keys() if isinstance(k, str) and k.startswith("activity_")})
    except Exception:
        pass
    return out


# ------------------------------------------------------------
# 🔹 form3 固定スキーマ（列順）＋ 画像ファイル名の専用列
# ------------------------------------------------------------
FORM3_ORDER = [
    "residence_type_house_1f","residence_type_house_2f","residence_type_apartment","apartment_floor",
    "elevator_あり","elevator_不要",
    "entrance_to_road_危険あり","entrance_to_road_問題なし",
    "room_photo_image_filename1","room_photo_image_filename2","room_photo_image_filename3","room_safety",
    "expensive_cost_usage_0","expensive_cost_usage_1a","expensive_cost_usage_1b","expensive_cost_usage_2a",
    "public_medical_usage_0","public_medical_usage_1","public_medical_usage_2",
    "reform_need_0","reform_need_1",
    "reform_place_room","reform_place_bathroom","reform_place_datsuishitsu","reform_place_bathtub",
    "reform_place_toilet","reform_place_benki","reform_place_hallway","reform_place_entrance",
    "reform_place_garden","reform_place_stairs","reform_place_other",
    "care_tool_need_0","care_tool_need_1",
    "care_tool_type_move","care_tool_type_life","care_tool_type_assist",
    "equipment_need_0","equipment_need_1",
    "equipment_type_life_tool","equipment_type_electric","equipment_type_aircon","equipment_type_elevator",
    "equipment_type_other_flag","equipment_type_other",
    "social_service_usage_0","social_service_usage_1","social_service_usage_2","social_service_usage_3",
    "social_service_reason_text",
]

def _form3_apply_order_and_image(row: dict) -> dict:
    # ベース値しか来ていない場合の one-hot 補完
    def _ensure_one_hot_from_raw(target: dict, bases: list[str]) -> None:
        for base in bases:
            prefix = base + "_"
            if any(k.startswith(prefix) for k in target.keys()):
                continue
            if base not in target:
                continue
            choices = CHOICE_MASTER.get(base)
            if not choices:
                continue
            val = str(target.get(base, "")).strip()
            for choice in choices:
                target[f"{base}_{choice}"] = 1 if val == str(choice) else 0
            target.pop(base, None)

    _ensure_one_hot_from_raw(
        row,
        [
            "residence_type",
            "elevator",
            "entrance_to_road",
            # 追加: 在宅生活や療養室として適切ですか / 住居の安全性・適切な広さ
            "expensive_cost_usage",
            "public_medical_usage",
            "reform_need",
            "reform_place",
            "care_tool_need",
            "care_tool_type",
            "equipment_need",
            "equipment_type",
            "social_service_usage",
        ],
    )

    # one-hot のサフィックス置換（日本語→英別名）
    FORM3_ONEHOT_ALIASES = {
        "reform_place": {
            "居室": "room",
            "浴室": "bathroom",
            "脱衣室": "datsuishitsu",
            "浴槽": "bathtub",
            "トイレ": "toilet",
            "便器": "benki",
            "廊下": "hallway",
            "玄関": "entrance",
            "庭": "garden",
            "階段": "stairs",
            "その他": "other",
        },
        "care_tool_type": {
            "移動用具": "move",
            "生活用具": "life",
            "介助用具": "assist",
        },
        "equipment_type": {
            "障害者用生活用具": "life_tool",
            "電気": "electric",
            "冷暖房機": "aircon",
            "エレベータ": "elevator",
            "その他": "other_flag",
        },
    }
    for base, mapping in FORM3_ONEHOT_ALIASES.items():
        prefix = base + "_"
        for k in list(row.keys()):
            if not k.startswith(prefix):
                continue
            token = k[len(prefix):]
            alias = mapping.get(str(token))
            if alias:
                row[f"{base}_{alias}"] = row.pop(k)

    _FORM3_TEXT_COLS = {
        "room_photo_image_filename1","room_photo_image_filename2","room_photo_image_filename3",
        "room_safety",
        "equipment_type_other",
        "social_service_reason_text",
    }

    out: dict = {"timestamp": row.get("timestamp", "")}
    # 画像ファイル名の専用列に、先頭の画像ファイル名を反映（あれば）
    try:
        # 明示の1/2/3があればそれを採用、無ければ image_file を分割して埋める
        names = []
        for n in ("room_photo1_image_filename","room_photo2_image_filename","room_photo3_image_filename"):
            val = str(row.get(n, "") or "").strip()
            if val:
                names.append(val)
        if not names:
            names = [p.strip() for p in (row.get("image_file") or "").split(";") if p.strip()]
        # 1/2/3 列を埋める
        row["room_photo_image_filename1"] = names[0] if len(names) > 0 else ""
        row["room_photo_image_filename2"] = names[1] if len(names) > 1 else ""
        row["room_photo_image_filename3"] = names[2] if len(names) > 2 else ""
    except Exception:
        pass
    for col in FORM3_ORDER:
        if col in _FORM3_TEXT_COLS:
            out[col] = row.get(col, "")
            continue
        v = row.get(col, 0)
        if isinstance(v, str) and v.strip() == "":
            v = 0
        out[col] = v
    return out


# ------------------------------------------------------------
# 🔹 form4 固定スキーマ（列順）
# ------------------------------------------------------------
FORM4_ORDER = [
    "has_caregiver1","has_caregiver0",
    "care_burden_feeling_0","care_burden_feeling_1","care_burden_feeling_2","care_burden_feeling_3","care_burden_feeling_4",
    "care_burden_health_0","care_burden_health_1","care_burden_health_2","care_burden_health_3","care_burden_health_4",
    "care_burden_life_0","care_burden_life_1","care_burden_life_2","care_burden_life_3","care_burden_life_4",
    "care_burden_work_0","care_burden_work_1","care_burden_work_2","care_burden_work_3","care_burden_work_4",
    # 追加: 仕事影響の別名列（care_burden_impact_*）
    "care_burden_impact_0","care_burden_impact_1","care_burden_impact_2","care_burden_impact_3","care_burden_impact_4",
    "care_period_years","care_period_months",
    "care_intention_0","care_intention_1","care_intention_2","care_intention_3","care_intention_4","care_intention_5",
    "abuse_injury_0","abuse_injury_1","abuse_injury_2","abuse_injury_3","abuse_injury_4",
    "neglect_hygiene_0","neglect_hygiene_1","neglect_hygiene_2","neglect_hygiene_3","neglect_hygiene_4",
    "psychological_abuse_0","psychological_abuse_1","psychological_abuse_2","psychological_abuse_3","psychological_abuse_4",
    "neglect_care_0","neglect_care_1","neglect_care_2","neglect_care_3","neglect_care_4",
    "sexual_abuse_0","sexual_abuse_1","sexual_abuse_2","sexual_abuse_3","sexual_abuse_4",
    "financial_abuse_0","financial_abuse_1","financial_abuse_2","financial_abuse_3","financial_abuse_4",
    "memo",
]

def _form4_apply_order(row: dict) -> dict:
    # 追加: has_caregiver と impact 列の補完
    try:
        val = str(row.get("has_caregiver", "")).strip()
        if val in ("0","1"):
            row["has_caregiver1"] = 1 if val == "1" else 0
            row["has_caregiver0"] = 1 if val == "0" else 0
    except Exception:
        pass
    try:
        for i in range(5):
            src = row.get(f"care_burden_work_{i}", 0)
            row[f"care_burden_impact_{i}"] = src
    except Exception:
        pass
    out: dict = {"timestamp": row.get("timestamp", "")}
    for col in FORM4_ORDER:
        v = row.get(col, 0)
        if isinstance(v, str) and v.strip() == "":
            v = 0
        out[col] = v
    return out


# ------------------------------------------------------------
# 🔹 form5 固定スキーマ（列順）
# ------------------------------------------------------------
FORM5_ORDER = [
    # 社会参加（1-a〜d）
    "social_participation_1_a","social_participation_1_b","social_participation_1_c","social_participation_1_d",

    # 楽しみ1（あり・なし・なしのメモ）
    "enjoyment_1_あり","enjoyment_1_なし","enjoyment_1_text_none",

    # 楽しみ2
    "enjoyment_2_あり","enjoyment_2_なし","enjoyment_2_text_none",

    # 楽しみ3
    "enjoyment_3_あり","enjoyment_3_なし","enjoyment_3_text_none",

    # 理由
    "enjoyment_reason",

    # 関係性（0〜3）
    "relationship_status_0","relationship_status_1","relationship_status_2","relationship_status_3",

    # 相談の有無
    "consultation_status_0","consultation_status_1",

    # 支援者一覧
    "supporter_family","supporter_friend","supporter_minsei","supporter_center","supporter_service_staff",
    "supporter_neighbor","supporter_volunteer","supporter_guardian","supporter_delivery","supporter_public",
    "supporter_religious","supporter_other_flag","supporter_other",
]


_FORM5_TEXT_COLS = {
    "enjoyment_1_text","enjoyment_1_text_none","enjoyment_2_text","enjoyment_2_text_none",
    "enjoyment_3_text","enjoyment_3_text_none","enjoyment_reason","supporter_other",
}

def _form5_get_bool(row: dict, col: str) -> int:
    if col in row:
        v = row.get(col)
        if isinstance(v, str):
            return 0 if v.strip() == "" else (1 if v not in ("0","false","False") else 0)
        return 1 if v else 0
    # 代替: col_XXX の列が立っていれば 1 とみなす
    prefix = col + "_"
    for k, v in row.items():
        if k.startswith(prefix):
            if str(v) not in ("", "0", "false", "False"):
                return 1
    return 0

def _form5_apply_order(row: dict) -> dict:
    # --- 生値から one-hot 補完（form5専用） ---
    # 1) 社会参加（長文テキスト → a/b/c/d）
    try:
        raw = str(row.get("social_participation_1", row.get("social_participation_1_raw", ""))).strip()
        # 既存 one-hot が全て0（flattenでa/b/c/dにマッチせず0だけ作成された）なら上書きする
        existing_keys = [f"social_participation_1_{t}" for t in ("a","b","c","d")]
        existing_present = any(k in row for k in existing_keys)
        existing_all_zero = existing_present and all(str(row.get(k, "0")).strip() in ("", "0", "false", "False") for k in existing_keys)
        if (not existing_present) or existing_all_zero:
            if raw:
                map_sp = {
                    "週に3回以上は外出し家族や友人・支援・ネットワークなどと継続に連絡が取れている（デイケア・デイサービス、買物、近隣や親戚や知人等の付き合い、通勤、散歩、行楽、電話、ネット、手紙を含む）": "a",
                    "週に1〜2回は外出したり、家族や知人と連絡を取り社会参加している": "b",
                    "月に数回外出するがそれ以外の時は1人でいる、家族や知人に会うのは月に何回かである。月に1〜2回": "c",
                    "親戚や近隣・社会交流・社会的接触を全くしていない、デイケア等にも行っていない、昨年より外出が減った": "d",
                }
                alias = map_sp.get(raw)
                if alias:
                    for t in ("a","b","c","d"):
                        row[f"social_participation_1_{t}"] = 1 if alias == t else 0
    except Exception:
        pass
    # 2) 対人関係（1..4 → 0..3）
    try:
        if not any(k.startswith("relationship_status_") for k in row.keys()):
            raw = str(row.get("relationship_status", "")).strip()
            if raw.isdigit():
                idx = max(0, int(raw) - 1)
                for i in range(4):
                    row[f"relationship_status_{i}"] = 1 if i == idx else 0
    except Exception:
        pass
    # 3) 相談の有無（1/2 → 0/1）
    try:
        if not any(k.startswith("consultation_status_") for k in row.keys()):
            raw = str(row.get("consultation_status", "")).strip()
            if raw in ("1","2"):
                idx = 0 if raw == "1" else 1
                row["consultation_status_0"] = 1 if idx == 0 else 0
                row["consultation_status_1"] = 1 if idx == 1 else 0
    except Exception:
        pass
    # 4) 支援者（supporter[] 日本語 → 英別名）
    try:
        supporter_aliases = {
            "家族（身内・親族）": "family",
            "友人の支援者": "friend",
            "民生委員": "minsei",
            "地域包括支援センターや地域活動支援センター": "center",
            "介護保険サービスの担当者": "service_staff",
            "住民の役員・近隣者": "neighbor",
            "ボランティア": "volunteer",
            "成年後見人": "guardian",
            "宅配業者": "delivery",
            "郵便局・消防署・農協": "public",
            "信仰関係者": "religious",
            "その他": "other_flag",
        }
        # _flatten_payload により supporter_＜日本語＞=1 形式が来るため、それを英別名へ立て直す
        for k, v in list(row.items()):
            if not k.startswith("supporter_"):
                continue
            token = k[len("supporter_"):]
            if token in supporter_aliases:
                alias = supporter_aliases[token]
                row[f"supporter_{alias}"] = 1 if str(v) not in ("", "0", "false", "False") else 0
    except Exception:
        pass
    # 既定のフラグ列をすべて用意（欠けているキーは0で補完）→ ヘッダ拡張のため
    try:
        for i in range(4):
            row.setdefault(f"relationship_status_{i}", 0)
        for i in range(2):
            row.setdefault(f"consultation_status_{i}", 0)
        for t in ("a","b","c","d"):
            row.setdefault(f"social_participation_1_{t}", 0)
    except Exception:
        pass

    out: dict = {"timestamp": row.get("timestamp", "")}
    for col in FORM5_ORDER:
        if col in _FORM5_TEXT_COLS:
            out[col] = row.get(col, "")
        else:
            v = row.get(col, None)
            if v is None:
                out[col] = _form5_get_bool(row, col) if (col.startswith("supporter_") or col.startswith("relationship_status_") or col.startswith("consultation_status_") or col.startswith("enjoyment_") or col.startswith("social_participation_1_")) else 0
            else:
                if isinstance(v, str) and v.strip() == "":
                    out[col] = 0
                else:
                    out[col] = v
    return out


# ------------------------------------------------------------
# 🔹 form6 固定スキーマ（列順）
# ------------------------------------------------------------
FORM6_ORDER = [
    "alcohol_problem_0","alcohol_problem_1","alcohol_problem_2","alcohol_problem_3",
    "who_alcohol_criteria_1","who_alcohol_criteria_2","who_alcohol_criteria_3","who_alcohol_criteria_4",
    "who_alcohol_criteria_5","who_alcohol_criteria_6","who_alcohol_criteria_7","who_alcohol_criteria_8",
    "smoking_habit_0","smoking_habit_1","smoking_amount","smoking_years","brinkman_index","family_impact",
    "sleep_quality_0","sleep_quality_1","sleep_quality_2","sleep_quality_3",
    "fatigue_0","fatigue_1",
    "fatigue_detail_だるい","fatigue_detail_疲れやすい","fatigue_detail_疲れが残ってる","fatigue_detail_慢性的に疲れている",
    "allergy_0","allergy_1",
    "allergy_detail_花粉症","allergy_detail_食物アレルギー","allergy_detail_ハウスダスト","allergy_detail_薬物","allergy_detail_その他",
    "allergy_other",
    "physical_activity_0","physical_activity_1","physical_activity_detail",
    "disease_within_year_0","disease_within_year_1",
    "disease_type_a","disease_type_b","disease_type_c","disease_type_d","disease_type_e","disease_type_f",
    "disease_type_g","disease_type_h","disease_type_i","disease_type_j","disease_type_other",
    "vaccination_status_0","vaccination_status_1",
    "vaccination_a","vaccination_b","vaccination_c","vaccination_d","vaccination_e","vaccination_f","vaccination_h",
    "vaccination_other","vaccination_none_reason",
    "infection_control_0","infection_control_1","infection_control_2","infection_control_3","infection_control_4",
]

_FORM6_TEXT_COLS = {
    "smoking_amount","smoking_years","brinkman_index","family_impact",
    "allergy_other","physical_activity_detail","disease_type_other","vaccination_other","vaccination_none_reason",
}

def _form6_apply_order(row: dict) -> dict:
    # ベース値しか来ていない場合の one-hot 補完（form6）
    try:
        def _ensure_one_hot_from_raw(target: dict, base: str, choices: list[str]) -> None:
            prefix = base + "_"
            if any(k.startswith(prefix) for k in target.keys()):
                return
            if base not in target:
                return
            val = str(target.get(base, "")).strip()
            for c in choices:
                target[f"{base}_{c}"] = 1 if val == str(c) else 0
            target.pop(base, None)

        _ensure_one_hot_from_raw(row, "sleep_quality", ["0","1","2","3"])
        _ensure_one_hot_from_raw(row, "fatigue", ["0","1"])
        _ensure_one_hot_from_raw(row, "allergy", ["0","1"])
        _ensure_one_hot_from_raw(row, "physical_activity", ["0","1"])
        _ensure_one_hot_from_raw(row, "disease_within_year", ["0","1"])
        _ensure_one_hot_from_raw(row, "vaccination_status", ["0","1"])
        _ensure_one_hot_from_raw(row, "infection_control", ["0","1","2","3","4"])
        # disease_type は複数選択の可能性があるため、raw が残っていた場合の補完にも対応
        if not any(k.startswith("disease_type_") for k in row.keys()):
            if "disease_type" in row:
                raw = row.get("disease_type")
                tokens: list[str] = []
                if isinstance(raw, list):
                    tokens = [str(t).strip() for t in raw if str(t).strip()]
                else:
                    s = str(raw).strip()
                    if s:
                        tokens = [s]
                for c in ["a","b","c","d","e","f","g","h","i","j"]:
                    row[f"disease_type_{c}"] = 1 if c in tokens else 0
                # 生値は不要
                try:
                    row.pop("disease_type", None)
                except Exception:
                    pass
    except Exception:
        pass
    # フォールバック: ブリンクマン指数が未送信/0なら、(本数×年数) から算出して補完
    try:
        idx_raw = row.get("brinkman_index")
        def _to_num(x):
            try:
                # 小数を避けるためint優先、失敗時float
                return int(float(str(x)))
            except Exception:
                return None
        if str(idx_raw).strip() in ("", "0", "None") or idx_raw is None:
            amt = _to_num(row.get("smoking_amount"))
            yrs = _to_num(row.get("smoking_years"))
            if amt is not None and yrs is not None and amt > 0 and yrs > 0:
                row["brinkman_index"] = amt * yrs
    except Exception:
        pass
    out: dict = {"timestamp": row.get("timestamp", "")}
    for col in FORM6_ORDER:
        if col in _FORM6_TEXT_COLS:
            out[col] = row.get(col, "")
        else:
            v = row.get(col, 0)
            if isinstance(v, str) and v.strip() == "":
                v = 0
            out[col] = v
    return out


# ------------------------------------------------------------
# 🔹 form7 固定スキーマ（列順）
# ------------------------------------------------------------
FORM7_ORDER = [
    "bmi_category_0","bmi_category_1","bmi_category_2","bmi_category_3","bmi_category_4",
    "bmi_category_5","bmi_category_6","bmi_category_7","bmi_category_8",
    "height","weight","bmi_value",
    "weight_change_0","weight_change_1","weight_change_2","weight_change_3",
    "nutrition_self_management_0","nutrition_self_management_1","nutrition_self_management_2","nutrition_self_management_3","nutrition_self_management_4",
    "dietary_therapy_0","dietary_therapy_1","dietary_therapy_detail",
    "food_form_0","food_form_1","food_form_2","food_form_3","food_form_4","food_form_5","food_form_6",
    "meal_frequency_0","meal_frequency_1","meal_frequency_2","meal_frequency_3",
    "meal_with_others_0","meal_with_others_1","meal_with_others_2",
    "water_intake_0","water_intake_1","water_intake_2","water_intake_3",
    "swallowing_0","swallowing_1","swallowing_2","swallowing_3","swallowing_4",
    "oral_teeth_gum_0","oral_teeth_gum_1","oral_teeth_gum_2",
    "oral_denture_condition_0","oral_denture_condition_1","oral_denture_condition_2",
    "oral_saliva_flow_0","oral_saliva_flow_1","oral_saliva_flow_2",
    "oral_dryness_0","oral_dryness_1","oral_dryness_2",
    "oral_saliva_0","oral_saliva_1","oral_saliva_2",
    "oral_tongue_0","oral_tongue_1","oral_tongue_2",
    "oral_tongue_surface_0","oral_tongue_surface_1","oral_tongue_surface_2",
    "oral_mucosa_0","oral_mucosa_1",
    "oral_gum_0","oral_gum_1","oral_gum_2",
]

_FORM7_TEXT_COLS = {"dietary_therapy_detail","height","weight","bmi_value"}

def _form7_apply_order(row: dict) -> dict:
    # ベース値しか来ていない場合の one-hot 補完（念のため）
    try:
        def _normalize_choice(val: str, base: str, choices: list[str]) -> str:
            if val in choices:
                return val
            if val.startswith(base + "_"):
                suffix = val[len(base) + 1 :]
                if suffix in choices:
                    return suffix
            if "_" in val:
                suffix = val.split("_")[-1]
                if suffix in choices:
                    return suffix
            return val

        def _ensure_one_hot_from_raw(target: dict, base: str, choices: list[str]) -> None:
            prefix = base + "_"
            if any(k.startswith(prefix) for k in target.keys()):
                return
            if base not in target:
                return
            val = _normalize_choice(str(target.get(base, "")).strip(), base, choices)
            for c in choices:
                target[f"{base}_{c}"] = 1 if val == str(c) else 0
            target.pop(base, None)

        _ensure_one_hot_from_raw(row, "oral_tongue", ["0","1","2"])
        _ensure_one_hot_from_raw(row, "oral_tongue_surface", ["0","1","2"])
        # フロントの name とCSV列の整合: 「歯・義歯」→ oral_teeth_gum_* へマッピング
        # 口腔: 歯・義歯（oral_denture_condition）→ 従来列(oral_teeth_gum_*)と新列(oral_denture_condition_*)の両方を出力
        if "oral_denture_condition" in row:
            val = _normalize_choice(str(row.get("oral_denture_condition", "")).strip(), "oral_denture_condition", ["0","1","2"])
            for c in ["0","1","2"]:
                flag = 1 if val == c else 0
                row[f"oral_teeth_gum_{c}"] = flag
                row[f"oral_denture_condition_{c}"] = flag
            # 生値は残さない
            row.pop("oral_denture_condition", None)
        else:
            # 既に oral_teeth_gum_* が立っている場合は新列へコピー
            if any(k.startswith("oral_teeth_gum_") for k in row.keys()):
                for c in ["0","1","2"]:
                    flag = row.get(f"oral_teeth_gum_{c}", 0)
                    row.setdefault(f"oral_denture_condition_{c}", flag)
    except Exception:
        pass
    out: dict = {"timestamp": row.get("timestamp", "")}
    for col in FORM7_ORDER:
        if col in _FORM7_TEXT_COLS:
            out[col] = row.get(col, "")
        else:
            v = row.get(col, 0)
            if isinstance(v, str) and v.strip() == "":
                v = 0
            out[col] = v
    return out


# ------------------------------------------------------------
# 🔹 form8 固定スキーマ（列順）
# ------------------------------------------------------------
FORM8_ORDER = [
    "urination_status_0","urination_status_1",
    "urination_0","urination_1",
    "urination_frequency_0","urination_frequency_1","urination_frequency_2","urination_frequency_3",
    "urination_control_0","urination_control_1","urination_control_2","urination_control_3",

    "defecation_status_0","defecation_status_a","defecation_status_b","defecation_status_c","defecation_status_d","defecation_status_e",
    "defecation_frequency_0","defecation_frequency_1","defecation_frequency_2",
    "defecation_control_0","defecation_control_1","defecation_control_2","defecation_control_3","defecation_control_4",
    "defecation_method_0","defecation_method_1","defecation_method_2","defecation_method_3","defecation_method_4",

    "excretion_method_A","excretion_method_B","excretion_method_C","excretion_method_D","excretion_method_E","excretion_method_F",

    "skin_nail_care_0","skin_nail_care_1","skin_nail_care_2","skin_nail_care_3",
    "bedsore_wound_0","bedsore_wound_1","bedsore_wound_2","bedsore_wound_3",

    "skin_condition_0","skin_condition_1","skin_condition_2","skin_condition_3",
]


def _form8_apply_order(row: dict) -> dict:
    out: dict = {"timestamp": row.get("timestamp", "")}
    for col in FORM8_ORDER:
        v = row.get(col, 0)
        if isinstance(v, str) and v.strip() == "":
            v = 0
        out[col] = v
    return out


# ------------------------------------------------------------
# 🔹 form9 固定スキーマ（列順）
# ------------------------------------------------------------
FORM9_ORDER = [
    # ADL 基本動作①（身辺動作）
    "basic1_eating_0","basic1_eating_1","basic1_eating_2","basic1_eating_3","basic1_eating_4","basic1_eating_5","basic1_eating_note",
    "basic1_face_hair_0","basic1_face_hair_1","basic1_face_hair_2","basic1_face_hair_3","basic1_face_hair_4","basic1_face_hair_5","basic1_face_hair_note",
    "basic1_wipe_0","basic1_wipe_1","basic1_wipe_2","basic1_wipe_3","basic1_wipe_4","basic1_wipe_5","basic1_wipe_note",
    "basic1_upper_clothes_0","basic1_upper_clothes_1","basic1_upper_clothes_2","basic1_upper_clothes_3","basic1_upper_clothes_4","basic1_upper_clothes_5","basic1_upper_clothes_note",
    "basic1_lower_clothes_0","basic1_lower_clothes_1","basic1_lower_clothes_2","basic1_lower_clothes_3","basic1_lower_clothes_4","basic1_lower_clothes_5","basic1_lower_clothes_note",
    "basic1_toilet_0","basic1_toilet_1","basic1_toilet_2","basic1_toilet_3","basic1_toilet_4","basic1_toilet_5","basic1_toilet_note",
    "basic1_bath_0","basic1_bath_1","basic1_bath_2","basic1_bath_3","basic1_bath_4","basic1_bath_5","basic1_bath_note",
    # ADL 起居動作②
    "basic2_stand_0","basic2_stand_1","basic2_stand_2","basic2_stand_3","basic2_stand_4","basic2_stand_5","basic2_stand_note",
    "basic2_getup_0","basic2_getup_1","basic2_getup_2","basic2_getup_3","basic2_getup_4","basic2_getup_5","basic2_getup_note",
    "basic2_sit_0","basic2_sit_1","basic2_sit_2","basic2_sit_3","basic2_sit_4","basic2_sit_5","basic2_sit_note",
    "basic2_bed_chair_stand_0","basic2_bed_chair_stand_1","basic2_bed_chair_stand_2","basic2_bed_chair_stand_3","basic2_bed_chair_stand_4","basic2_bed_chair_stand_5","basic2_bed_chair_stand_note",
    "basic2_both_leg_stand_0","basic2_both_leg_stand_1","basic2_both_leg_stand_2","basic2_both_leg_stand_3","basic2_both_leg_stand_4","basic2_both_leg_stand_5","basic2_both_leg_stand_note",
    # ADL 移乗・移動③
    "basic3_transfer_0","basic3_transfer_1","basic3_transfer_2","basic3_transfer_3","basic3_transfer_4","basic3_transfer_5","basic3_transfer_note",
    "basic3_bath_inout_0","basic3_bath_inout_1","basic3_bath_inout_2","basic3_bath_inout_3","basic3_bath_inout_4","basic3_bath_inout_5","basic3_bath_inout_note",
    "basic3_walk_home_0","basic3_walk_home_1","basic3_walk_home_2","basic3_walk_home_3","basic3_walk_home_4","basic3_walk_home_5","basic3_walk_home_note",
    "basic3_walk_out_0","basic3_walk_out_1","basic3_walk_out_2","basic3_walk_out_3","basic3_walk_out_4","basic3_walk_out_5","basic3_walk_out_note",
    # IADL
    "iadl_phone_0","iadl_phone_1","iadl_phone_2","iadl_phone_3","iadl_phone_note",
    "iadl_shopping_0","iadl_shopping_1","iadl_shopping_2","iadl_shopping_3","iadl_shopping_note",
    "iadl_housework_0","iadl_housework_1","iadl_housework_2","iadl_housework_3","iadl_housework_note",
    "iadl_toilet_0","iadl_toilet_1","iadl_toilet_2","iadl_toilet_3","iadl_toilet_note",
    "iadl_clean_0","iadl_clean_1","iadl_clean_2","iadl_clean_3","iadl_clean_note",
    "iadl_move_0","iadl_move_1","iadl_move_2","iadl_move_3","iadl_move_4","iadl_move_note",
    "iadl_money_0","iadl_money_1","iadl_money_2","iadl_money_3","iadl_money_note",
    "iadl_medicine_0","iadl_medicine_1","iadl_medicine_2","iadl_medicine_3","iadl_medicine_note",
    "iadl_decision_0","iadl_decision_1","iadl_decision_2","iadl_decision_3","iadl_decision_note",
]

_FORM9_TEXT_COLS = {
    "basic1_eating_note","basic1_face_hair_note","basic1_wipe_note","basic1_upper_clothes_note","basic1_lower_clothes_note","basic1_toilet_note","basic1_bath_note",
    "basic2_stand_note","basic2_getup_note","basic2_sit_note","basic2_bed_chair_stand_note","basic2_both_leg_stand_note",
    "basic3_transfer_note","basic3_bath_inout_note","basic3_walk_home_note","basic3_walk_out_note",
    "iadl_phone_note","iadl_shopping_note","iadl_housework_note","iadl_toilet_note","iadl_clean_note","iadl_move_note","iadl_money_note","iadl_medicine_note","iadl_decision_note",
}

def _form9_apply_order(row: dict) -> dict:
    out: dict = {"timestamp": row.get("timestamp", "")}
    for col in FORM9_ORDER:
        if col in _FORM9_TEXT_COLS:
            out[col] = row.get(col, "")
        else:
            v = row.get(col, 0)
            if isinstance(v, str) and v.strip() == "":
                v = 0
            out[col] = v
    return out


# ------------------------------------------------------------
# 🔹 form10 固定スキーマ（列順）
# ------------------------------------------------------------
FORM10_ORDER = [
    # 3. コミュニケーション方法（a〜h）＋ i ＋ その他内容
    "nutrition_self_management_a","nutrition_self_management_b","nutrition_self_management_c","nutrition_self_management_d",
    "nutrition_self_management_e","nutrition_self_management_f","nutrition_self_management_g","nutrition_self_management_h",
    "nutrition_self_management_i","nutrition_self_management_other",
    # コミュニケーション（意思疎通）の程度（0〜3）
    "communication_level_0","communication_level_1","communication_level_2","communication_level_3",
    # 会話の程度（0〜3）
    "conversation_level_0","conversation_level_1","conversation_level_2","conversation_level_3",
    # 聴覚の程度（0〜4）
    "hearing_level_0","hearing_level_1","hearing_level_2","hearing_level_3","hearing_level_4",
    # 4. 日常の意思の伝達
    "daily_communication_0","daily_communication_1","daily_communication_2","daily_communication_3",
    "daily_judgement_0","daily_judgement_1","daily_judgement_2","daily_judgement_3",
    "delirium_signs_exist_0","delirium_signs_exist_1",
    "delirium_signs_a","delirium_signs_b","delirium_signs_c","delirium_signs_d","delirium_signs_e",
    # 5. 視力・視覚
    "visual_ability_0","visual_ability_1","visual_ability_2","visual_ability_3",
    "visual_condition_0","visual_condition_1",
    "visual_condition_a","visual_condition_b","visual_condition_c","visual_condition_d","visual_condition_e",
]

_FORM10_TEXT_COLS = {"nutrition_self_management_other"}
_FORM10_BOOL_COLS = {
    "nutrition_self_management_a","nutrition_self_management_b","nutrition_self_management_c","nutrition_self_management_d",
    "nutrition_self_management_e","nutrition_self_management_f","nutrition_self_management_g","nutrition_self_management_h",
    "nutrition_self_management_i",
    "delirium_signs_a","delirium_signs_b","delirium_signs_c","delirium_signs_d","delirium_signs_e",
}

def _form10_apply_order(row: dict) -> dict:
    out: dict = {"timestamp": row.get("timestamp", "")}
    for col in FORM10_ORDER:
        if col in _FORM10_TEXT_COLS:
            out[col] = row.get(col, "")
        elif col in _FORM10_BOOL_COLS:
            v = row.get(col, None)
            out[col] = 0 if (v is None or (isinstance(v, str) and v.strip() == "")) else 1
        else:
            v = row.get(col, 0)
            if isinstance(v, str) and v.strip() == "":
                v = 0
            out[col] = v
    return out


# ------------------------------------------------------------
# 🔹 form11 固定スキーマ（列順）
# ------------------------------------------------------------
FORM11_ORDER = [
    # Ⅰ 認知の状態（a〜h）
    "nutrition_self_management_a","nutrition_self_management_b","nutrition_self_management_c","nutrition_self_management_d",
    "nutrition_self_management_e","nutrition_self_management_f","nutrition_self_management_g","nutrition_self_management_h",
    # Ⅱ 病気のとらえ方（0〜4）
    "emotion_level_0","emotion_level_1","emotion_level_2","emotion_level_3","emotion_level_4",
    # Ⅲ うつ的状態（各2択）
    "m_health_1_1","m_health_1_2",
    "m_health_2_1","m_health_2_2",
    "m_health_3_1","m_health_3_2",
    "m_health_4_1","m_health_4_2",
    "m_health_5_1","m_health_5_2",
    "m_health_6_1","m_health_6_2",
    "m_health_7_1","m_health_7_2",
    "m_health_8_1","m_health_8_2",
    "m_health_8_detail",
    "a_positive_count",
]

_FORM11_TEXT_COLS = {"m_health_8_detail"}

def _form11_apply_order(row: dict) -> dict:
    # A項目（A.1〜A.5）の「はい」回答数を計算し、a_positive_count に格納
    try:
        # 認知状態 (nutrition_self_management) が raw 値の場合は one-hot 化
        if not any(k.startswith("nutrition_self_management_") for k in row.keys()):
            val = str(row.get("nutrition_self_management", "")).strip()
            # 値が 'nutrition_self_management_a' のような形式でも a〜h に正規化
            if val.startswith("nutrition_self_management_"):
                val = val[len("nutrition_self_management_"):]
            for token in ["a","b","c","d","e","f","g","h"]:
                row[f"nutrition_self_management_{token}"] = 1 if val == token else 0
            row.pop("nutrition_self_management", None)

        a_count = 0
        for i in range(1, 6):
            v_one_hot = row.get(f"m_health_{i}_1", None)
            if v_one_hot is not None:
                a_count += 1 if str(v_one_hot) == "1" or v_one_hot == 1 else 0
            else:
                v_raw = row.get(f"m_health_{i}", None)
                if v_raw is not None:
                    sval = str(v_raw).strip()
                    if sval == "1" or sval.endswith("_1"):
                        a_count += 1
        row["a_positive_count"] = a_count
    except Exception:
        pass
    out: dict = {"timestamp": row.get("timestamp", "")}
    for col in FORM11_ORDER:
        if col in _FORM11_TEXT_COLS:
            out[col] = row.get(col, "")
        else:
            v = row.get(col, 0)
            if isinstance(v, str) and v.strip() == "":
                v = 0
            out[col] = v
    return out


# ------------------------------------------------------------
# 🔹 form12 固定スキーマ（列順）
# ------------------------------------------------------------
FORM12_ORDER = [
    # 0. 精神疾患の有無
    "has_psy_0","has_psy_1",
    # Ⅰ 情報提供者（1〜6） + その他記入
    "information_provider_1","information_provider_2","information_provider_3","information_provider_4","information_provider_5","information_provider_6",
    "information_provider_other",
    # Ⅱ NPI-Q（各0〜3）
    "npiq_delusion_0","npiq_delusion_1","npiq_delusion_2","npiq_delusion_3",
    "npiq_hallucination_0","npiq_hallucination_1","npiq_hallucination_2","npiq_hallucination_3",
    "npiq_agitation_0","npiq_agitation_1","npiq_agitation_2","npiq_agitation_3",
    "npiq_depression_0","npiq_depression_1","npiq_depression_2","npiq_depression_3",
    "npiq_anxiety_0","npiq_anxiety_1","npiq_anxiety_2","npiq_anxiety_3",
    "npiq_euphoria_0","npiq_euphoria_1","npiq_euphoria_2","npiq_euphoria_3",
    "npiq_apathy_0","npiq_apathy_1","npiq_apathy_2","npiq_apathy_3",
    "npiq_disinhibition_0","npiq_disinhibition_1","npiq_disinhibition_2","npiq_disinhibition_3",
    "npiq_irritability_0","npiq_irritability_1","npiq_irritability_2","npiq_irritability_3",
    "npiq_abnormal_behavior_0","npiq_abnormal_behavior_1","npiq_abnormal_behavior_2","npiq_abnormal_behavior_3",
    "npiq_night_behavior_0","npiq_night_behavior_1","npiq_night_behavior_2","npiq_night_behavior_3",
    "npiq_eating_behavior_0","npiq_eating_behavior_1","npiq_eating_behavior_2","npiq_eating_behavior_3",
    # Ⅲ NPI-Q集計
    "npiq_total_score","npiq_score_note",
]

_FORM12_TEXT_COLS = {"information_provider_other","npiq_score_note"}

def _form12_apply_order(row: dict) -> dict:
    # NPI-Q 合計点（各領域の重症度 0〜3 の総和）を算出
    try:
        # has_psy の one-hot 補完（'0' なし / '1' あり）
        if not any(k.startswith("has_psy_") for k in row.keys()):
            val = str(row.get("has_psy", "")).strip()
            if val in ("0","1"):
                row["has_psy_0"] = 1 if val == "0" else 0
                row["has_psy_1"] = 1 if val == "1" else 0
        domains = [
            "npiq_delusion","npiq_hallucination","npiq_agitation","npiq_depression","npiq_anxiety",
            "npiq_euphoria","npiq_apathy","npiq_disinhibition","npiq_irritability","npiq_abnormal_behavior",
            "npiq_night_behavior","npiq_eating_behavior",
        ]
        total = 0
        for base in domains:
            # one-hot から復元（*_0..*_3 のうち 1 のインデックスを加算）
            added = False
            for i in ("0","1","2","3"):
                v = row.get(f"{base}_{i}", None)
                if v == 1 or (isinstance(v, str) and v.strip() == "1"):
                    total += int(i)
                    added = True
                    break
            if not added:
                # 生値（"0".."3"）が来ている場合
                raw = row.get(base, None)
                if raw is not None and str(raw).strip().isdigit():
                    total += int(str(raw).strip())
        row["npiq_total_score"] = total
    except Exception:
        pass
    out: dict = {"timestamp": row.get("timestamp", "")}
    for col in FORM12_ORDER:
        if col in _FORM12_TEXT_COLS:
            out[col] = row.get(col, "")
        else:
            v = row.get(col, 0)
            if isinstance(v, str) and v.strip() == "":
                v = 0
            out[col] = v
    return out


# ------------------------------------------------------------
# 🔹 form13 固定スキーマ（列順）
# ------------------------------------------------------------
FORM13_ORDER = [
    "gaf_score","gaf_note",
]

_FORM13_TEXT_COLS = {"gaf_note"}

def _form13_apply_order(row: dict) -> dict:
    out: dict = {"timestamp": row.get("timestamp", "")}
    for col in FORM13_ORDER:
        if col in _FORM13_TEXT_COLS:
            out[col] = row.get(col, "")
        else:
            v = row.get(col, 0)
            if isinstance(v, str) and v.strip() == "":
                v = 0
            out[col] = v
    return out

def _flatten_payload(payload: dict, field_types: dict | None = None) -> dict:
    """payload をフラット化し、空欄やリストを正規化"""
    try:
        print("▶ flatten IN:", {k: v for k, v in payload.items() if isinstance(k, str) and k.startswith("activity_")})
        print("🟡 flatten IN (activity):", {k: v for k, v in payload.items() if isinstance(k, str) and k.startswith("activity_")})
    except Exception:
        pass
    # name="xxx[]" の配列キーをベース名に正規化（例: public_medical_detail[] → public_medical_detail）
    normalized: dict = {}
    for k, v in list(payload.items()):
        if isinstance(k, str) and k.endswith("[]"):
            base = k[:-2]
            if isinstance(v, list):
                normalized[base] = v
            else:
                normalized[base] = [v] if v not in (None, "") else []
        else:
            normalized[k] = v
    payload = normalized

    out: dict = {}

    def _normalize_choice_value(val: str, base: str) -> str:
        if val is None:
            return ""
        sval = str(val).strip()
        choices = CHOICE_MASTER.get(base) if base in CHOICE_MASTER else None
        if not choices:
            return sval
        if sval in choices:
            return sval
        prefix = base + "_"
        if sval.startswith(prefix):
            suffix = sval[len(prefix):]
            if suffix in choices:
                return suffix
        if "_" in sval:
            suffix = sval.split("_")[-1]
            if suffix in choices:
                return suffix
        return sval

    for k, v in list(payload.items()):
        # activity_* は空文字でもそのまま残す（0にしない）
        if isinstance(k, str) and k.startswith("activity_"):
            if isinstance(v, list):
                out[k] = ";".join(map(str, v))
            else:
                out[k] = v if v is not None else ""
            continue
        # form14: 「有無」セレクト（'あり'）→ exist_0/1 にワンホット
        if k in (
            "frailty_exist","dementia_exist","cancer_exist","circulatory_exist","bone_exist","leg_circulation_exist",
            "nutrition_exist","injection_exist","catheter_exist","tracheotomy_exist","respiration_exist","dialysis_exist",
            "stoma_exist","wound_exist","pain_management_exist","self_measurement_exist","oral_care_exist","drug_management_exist",
            "rehab_equipment_exist","rehab_aids_exist",
        ):
            val = str(v).strip() if v is not None else ""
            if val == "":
                # 未選択は両方 0（デフォルトで「なし」にしない）
                out[f"{k}_0"] = 0
                out[f"{k}_1"] = 0
            else:
                out[f"{k}_0"] = 1 if val not in ("あり", "1") else 0
                out[f"{k}_1"] = 1 if val in ("あり", "1") else 0
            continue
        # form14: Yes/No セレクト→ yes_no_select_0/1 にワンホット、理由チェックも展開
        if k == "yes_no_select":
            val = (str(v).strip().lower() if v is not None else "")
            if val == "":
                out["yes_no_select_1"] = 0
                out["yes_no_select_0"] = 0
            else:
                out["yes_no_select_1"] = 1 if val in ("yes", "1", "あり") else 0
                out["yes_no_select_0"] = 1 if val in ("no", "0", "なし") else 0
            continue
        if k == "no_reason":
            # a〜f を no_reason_a..f に 0/1 出力
            if not isinstance(v, list):
                vals = [str(v).strip().lower()] if v not in (None, "") else []
            else:
                vals = [str(x).strip().lower() for x in v if str(x).strip() != ""]
            for letter in ["a","b","c","d","e","f"]:
                out[f"no_reason_{letter}"] = 1 if letter in vals else 0
            continue
        # form14: 麻薬の有無 yes/no → 列に反映
        if k == "narcotic_use":
            val = (str(v).strip().lower() if v is not None else "")
            if val == "":
                out["narcotic_use_yes"] = 0
                out["narcotic_use_no"] = 0
            else:
                out["narcotic_use_yes"] = 1 if val == "yes" else 0
                out["narcotic_use_no"] = 1 if val == "no" else 0
            continue
        # form14: 詳細セレクトを *_detail_* 列にワンホット
        if k in ("frailty_detail","dementia_detail_select","cancer_detail_select","bone_detail_select"):
            val = str(v).strip() if v is not None else ""
            base = "dementia_detail" if k == "dementia_detail_select" else ("cancer_detail" if k == "cancer_detail_select" else ("bone_detail" if k == "bone_detail_select" else "frailty_detail"))
            # 対象の番号レンジを定義
            ranges = {
                "frailty_detail": [str(i) for i in range(1, 5)],          # 1..4
                "dementia_detail": [str(i) for i in range(1, 5)],         # 1..4
                "cancer_detail": [str(i) for i in range(1, 8)],           # 1..7
                "bone_detail": [str(i) for i in range(1, 8)],             # 1..7
            }
            for i in ranges.get(base, []):
                out[f"{base}_{i}"] = 1 if val == i else 0
            # 「その他」はテキスト欄に入力されるため番号99はワンホット対象外
            continue
        # form10: コミュニケーション方法（a〜i）は配列チェック -> 専用ブール列へ
        if k == "nutrition_self_management" and isinstance(v, list):
            try:
                tokens = [str(t).strip().lower() for t in v if str(t).strip() != ""]
                for token in tokens:
                    if token in list("abcdefghi"):
                        out[f"nutrition_self_management_{token}"] = 1
            except Exception:
                pass
            continue
        # form14: 栄養タイプ（チェックボックス）- 古いname/valueの補正
        if k == "nutrition_type":
            # 文字列で来た場合でも配列化
            if not isinstance(v, list):
                v = [v] if v not in (None, "") else []
            # 値の別名補正（nasogastric → nasal）
            fixed: list[str] = []
            for token in v:
                t = str(token).strip().lower()
                fixed.append("nasal" if t == "nasogastric" else t)
            # one-hot 列へ（例: nutrition_type_nasal = 1）
            for token in fixed:
                out[f"nutrition_type_{token}"] = 1
            continue
        # form8 排尿: UI値→内部コードへ正規化してから one-hot（CHOICE_MASTER）へ流す
        if isinstance(k, str) and k in ("urination_status", "urination", "urination_frequency"):
            try:
                mapping = {
                    "urination_status": {"normal": "0", "abnormal": "1"},
                    "urination": {"yes": "0", "no": "1"},
                    "urination_frequency": {"4-7": "0", "1-2": "1", "8plus_day": "2", "none": "3"},
                }
                m = mapping.get(k)
                if m and isinstance(v, str):
                    vv = m.get(v.strip(), v)
                    payload[k] = vv
                    v = vv
            except Exception:
                pass
        # form8 排便: defecation_status は "0/a/b/c/d/e" を想定（古い "normal" → "0" に補正）
        if k == "defecation_status":
            try:
                if isinstance(v, str):
                    val = v.strip().lower()
                    if val == "normal":
                        payload[k] = "0"
                        v = "0"
            except Exception:
                pass
        # form5: 対人関係・相談の有無は固定の番号→one-hot へ補完（CHOICE_MASTERに無いため特別扱い）
        if k == "relationship_status":
            val = str(v).strip() if v is not None else ""
            try:
                idx = max(0, int(val) - 1) if val.isdigit() else None
            except Exception:
                idx = None
            for i in range(4):
                out[f"relationship_status_{i}"] = 1 if (idx is not None and i == idx) else 0
            # 生値も保持（デバッグ用）
            out["relationship_status"] = val
            continue
        if k == "consultation_status":
            val = str(v).strip() if v is not None else ""
            idx = 0 if val == "1" else (1 if val == "2" else None)
            for i in range(2):
                out[f"consultation_status_{i}"] = 1 if (idx is not None and i == idx) else 0
            out["consultation_status"] = val
            continue
        # form2 / form3 の自由記述テキストは 0 に潰さず空文字で保持
        if isinstance(k, str) and k in {
            "expensive_cost_no_reason",
            "expensive_cost_reason",
            "public_medical_reason",
            "option_detail_1",
            "option_detail_2",
            "option_detail_3",
            "public_medical_detail_other",
            "medical_disease_name",
            "economic_status_3_difficulties_other",
            # form3 テキスト列
            "room_safety",
            "equipment_type_other",
            "room_photo_image_filename",
            "social_service_reason_text",
        }:
            out[k] = "" if v in (None, "") else str(v)
            continue
        # form14: タイプ系チェックボックス/単一値の値 → 既定列名へマッピング
        #   - HTMLの value と CSV の列サフィックスに差異があるため補正する
        if k in ("injection_type", "catheter_type", "tracheotomy_type", "respiration_type", "oral_visit", "drug_management", "stoma_type", "pain_management"):
            # 配列でも単一値でも受理
            try:
                tokens = (
                    [str(x).strip().lower() for x in v if str(x).strip() != ""]
                    if isinstance(v, list)
                    else ([str(v).strip().lower()] if str(v).strip() != "" else [])
                )
            except Exception:
                tokens = []
            # それぞれのマッピング表（左: 受信値, 右: 既定列サフィックス）
            mapping_tables: dict[str, dict[str, str]] = {
                "injection_type": {
                    "subcutaneous_infusion": "subcutaneous_infusion",
                    "blood_transfusion": "infusion",
                    "insulin_self_injection": "intramuscular",
                    "intravenous_injection": "intravenous",
                    "drip_infusion": "drip_infusion",
                },
                "catheter_type": {
                    "indwelling_bladder_catheter": "indwelling_bladder_catheter",
                    "condom_catheter": "suprapubic_catheter",
                    "self_catheterization": "self_catheterization",
                },
                "tracheotomy_type": {
                    "suction": "suction",
                    "inhalation": "tracheostomy_tube",
                    "home_oxygen": "artificial_larynx",
                    "ventilator": "ventilator",
                },
                "respiration_type": {
                    "suction": "suction",
                    "inhalation": "inhalation",
                    "home_oxygen": "home_oxygen",
                    "cpap_bipap": "cpap_bipap",
                    "ventilator": "ventilator",
                },
                "oral_visit": {
                    "clinic": "clinic",
                    "home_visit": "home",
                    "dental_hygienist_visit": "dental_hygienist_visit",
                },
                "drug_management": {
                    "oral_medication": "oral_medication",
                    "external_medicine": "external_medication",
                    "eye_drops": "external_medication",
                    "suppository": "suppository",
                    "injection": "injection",
                },
                "stoma_type": {
                    "artificial_anus": "artificial_anus",
                    "artificial_bladder": "artificial_bladder",
                },
                "pain_management": {
                    "subcutaneous_injection": "subcutaneous_injection",
                    "epidural_injection": "iv_infusion",
                    "oral_medication": "oral",
                    "patch_or_mucosal": "patch_or_mucosal",
                },
            }
            expected_suffixes: dict[str, list[str]] = {
                "injection_type": ["subcutaneous_infusion","intramuscular","intravenous","infusion","drip_infusion"],
                "catheter_type": ["indwelling_bladder_catheter","suprapubic_catheter","self_catheterization"],
                "tracheotomy_type": ["suction","tracheostomy_tube","artificial_larynx","ventilator"],
                "respiration_type": ["suction","inhalation","home_oxygen","cpap_bipap","ventilator"],
                "oral_visit": ["clinic","home","dental_hygienist_visit"],
                "drug_management": ["oral_medication","external_medication","suppository","injection","dialysis_etc"],
                "stoma_type": ["artificial_anus","artificial_bladder"],
                "pain_management": ["subcutaneous_injection","oral","iv_infusion","patch_or_mucosal"],
            }
            table = mapping_tables.get(k, {})
            mapped = [table.get(t, t) for t in tokens]
            # 「注射･輸液･輸血･透析等」→ injection が選ばれたら dialysis_etc も 1 にする
            if k == "drug_management" and ("injection" in mapped):
                mapped.append("dialysis_etc")
            # 既定サフィックスのみ 0/1 を明示的に出力（未選択は0）
            for suf in expected_suffixes.get(k, []):
                out[f"{k}_{suf}"] = 1 if suf in mapped else 0
            continue
        # form10: コミュニケーション方法（a〜i）が単一文字列で届いた場合にも複数選択として解釈
        if k == "nutrition_self_management" and not isinstance(v, list):
            try:
                sval = str(v).strip()
                tokens: list[str] = []
                if sval != "":
                    # カンマ/セミコロン/空白で分割 or 文字列中の a..i を抽出
                    candidates = re.split(r"[,\s;]+", sval)
                    for c in candidates:
                        t = str(c).strip().lower()
                        if t == "":
                            continue
                        # 'nutrition_self_management_a' → 'a'
                        if t.startswith("nutrition_self_management_"):
                            t = t.split("_")[-1]
                        # 文字列全体からも a..i を抽出（"ab" や "a,b" にも対応）
                        letters = re.findall(r"[a-i]", t)
                        if letters:
                            tokens.extend(letters)
                        elif t in list("abcdefghi"):
                            tokens.append(t)
                # 1つも抽出できなければ通常処理へフォールバック
                if tokens:
                    for ch in list("abcdefghi"):
                        out[f"nutrition_self_management_{ch}"] = 1 if ch in tokens else 0
                    continue
            except Exception:
                # 失敗時は通常処理に任せる
                pass
        # 配列（チェックボックス複数）
        if isinstance(v, list):
            selected = [str(x).strip() for x in v if str(x).strip() != ""]
            if k in CHOICE_MASTER:
                # 特例: form6 疾病タイプは 'a.肺炎' などの表示値が来るため先頭の英字(a..j)に正規化
                if k == "disease_type":
                    norm_letters: list[str] = []
                    for token in selected:
                        # 先頭の英字を抽出（'a.肺炎' → 'a'）
                        m = re.match(r"\s*([a-jA-J])", token)
                        if m:
                            norm_letters.append(m.group(1).lower())
                        else:
                            # 既に 'a' などの場合も考慮
                            t = token.lower()
                            if t in ("a","b","c","d","e","f","g","h","i","j"):
                                norm_letters.append(t)
                    selected = norm_letters
                for choice in CHOICE_MASTER[k]:
                    out[f"{k}_{choice}"] = 1 if str(choice) in selected else 0
            else:
                for token in selected:
                    out[f"{k}_{token}"] = 1
            # form2: 公費医療の詳細（チェックボックス）で「3」は専用列にエイリアス
            if k == "public_medical_detail" and "public_medical_detail_3" in out:
                out["public_medical_detail_3_check"] = out.pop("public_medical_detail_3")
            continue
        # 単一選択（ドロップダウン/ラジオ）: CHOICE_MASTER があれば one-hot 展開
        if k in CHOICE_MASTER:
            val = _normalize_choice_value(v, k)
            # form5: 社会参加は a/b/c/d 以外（長文テキスト）が来るケースがあるため、生値も保持
            try:
                if k == "social_participation_1":
                    if val and val not in set(CHOICE_MASTER.get("social_participation_1", [])):
                        out["social_participation_1_raw"] = val
            except Exception:
                pass
            for choice in CHOICE_MASTER[k]:
                out[f"{k}_{choice}"] = 1 if val == str(choice) else 0
            continue
        # form15: フロントの別名をサーバの想定キーへマッピングして one-hot
        if k in ("vital_change_overall", "respiration_rate", "breath_grade"):
            alias_map = {
                "vital_change_overall": "strange_feeling",   # 0/1
                "respiration_rate": "vital_respiration",     # 0/1
                "breath_grade": "dyspnea_grade",             # 0..4
            }
            base = alias_map.get(k)
            val = str(v).strip() if v is not None else ""
            if base and base in CHOICE_MASTER:
                for choice in CHOICE_MASTER[base]:
                    out[f"{base}_{choice}"] = 1 if val == str(choice) else 0
                continue
        # form16: フロント name 'wound_redness_area'(r0..r6) → サーバ想定 'wound_granulation'(g0..g6)
        if k == "wound_redness_area":
            val = str(v).strip().lower() if v is not None else ""
            # r0.. → g0.. に置換
            if val.startswith("r") and len(val) >= 2:
                mapped = "g" + val[1:]
            else:
                mapped = val.replace("r", "g")
            # one-hot 展開（既定の g0..g6 レンジに合わせる）
            for choice in CHOICE_MASTER.get("wound_granulation", []):
                out[f"wound_granulation_{choice}"] = 1 if mapped == str(choice) else 0
            continue

        # それ以外
        # 特例: form17 の 'med_name_1..24' は空欄を 0 に潰さない（未選択は両方0にしたいので base を作らない）
        if isinstance(k, str) and re.match(r"^med_name_\d{1,2}$", k):
            if v in ("", None):
                # 未選択は base を生成しない → 後段の form17 固定スキーマで _0/_1 が 0 になる
                continue
            out[k] = v
            continue
        # デフォルト: 空文字や None は 0、それ以外はそのまま
        if v in ("", None):
            out[k] = 0
        else:
            out[k] = v

    # form2: 公費医療の詳細（ドロップダウン）を固定列 public_medical_detail_1..6 へ補完
    try:
        if "public_medical_detail_dropdown" in payload:
            val = str(payload.get("public_medical_detail_dropdown", "")).strip()
            for i in ("1","2","3","4","5","6"):
                out[f"public_medical_detail_{i}"] = 1 if val == i else 0
    except Exception:
        pass
    try:
        print("▶ flatten OUT:", {k: v for k, v in out.items() if isinstance(k, str) and k.startswith("activity_")})
        print("🟡 flatten OUT (activity):", {k: v for k, v in out.items() if isinstance(k, str) and k.startswith("activity_")})
    except Exception:
        pass
    return out


# ------------------------------------------------------------
# 🔹 form14 固定スキーマ（列順）
# ------------------------------------------------------------
FORM14_ORDER = [
    # Ⅰ 主な疾患・障害の有無
    "frailty_exist_0","frailty_exist_1",
    "frailty_detail_1","frailty_detail_2","frailty_detail_3","frailty_detail_4",
    "frailty_other",
    "dementia_exist_0","dementia_exist_1",
    "dementia_detail_1","dementia_detail_2","dementia_detail_3","dementia_detail_4",
    "dementia_other",
    "cancer_exist_0","cancer_exist_1",
    "cancer_detail_1","cancer_detail_2","cancer_detail_3","cancer_detail_4","cancer_detail_5","cancer_detail_6","cancer_detail_7",
    "cancer_other",
    "circulatory_exist_0","circulatory_exist_1","circulatory_freewrite_input",
    "bone_exist_0","bone_exist_1",
    "bone_detail_1","bone_detail_2","bone_detail_3","bone_detail_4","bone_detail_5","bone_detail_6","bone_detail_7",
    "bone_other",
    "leg_circulation_exist_0","leg_circulation_exist_1","leg_circulation_freewrite_input",
    # Ⅱ 主治医・診断・受診行動
    "doctor_diagnosis_note",
    "other_hospital_1","diagnosis_1","treatment_content_1","remarks_1",
    "other_hospital_2","diagnosis_2","treatment_content_2","remarks_2",
    "yes_no_select_0","yes_no_select_1",
    "no_reason_a","no_reason_b","no_reason_c","no_reason_d","no_reason_e","no_reason_f",
    # Ⅲ 医療処置・リハビリ・ケア
    "nutrition_exist_0","nutrition_exist_1",
    "nutrition_type_central_venous","nutrition_type_nasal","nutrition_type_peg",
    "injection_exist_0","injection_exist_1",
    "injection_type_subcutaneous_infusion","injection_type_intramuscular","injection_type_intravenous","injection_type_infusion","injection_type_drip_infusion",
    "catheter_exist_0","catheter_exist_1",
    "catheter_type_indwelling_bladder_catheter","catheter_type_suprapubic_catheter","catheter_type_self_catheterization",
    "tracheotomy_exist_0","tracheotomy_exist_1",
    "tracheotomy_type_suction","tracheotomy_type_tracheostomy_tube","tracheotomy_type_artificial_larynx","tracheotomy_type_ventilator",
    "respiration_exist_0","respiration_exist_1",
    "respiration_type_suction","respiration_type_inhalation","respiration_type_home_oxygen","respiration_type_cpap_bipap","respiration_type_ventilator",
    "dialysis_exist_0","dialysis_exist_1",
    "dialysis_type_capd_apd","dialysis_type_hemodialysis",
    "stoma_exist_0","stoma_exist_1",
    "stoma_type_artificial_anus","stoma_type_artificial_bladder",
    "wound_exist_0","wound_exist_1",
    "wound_type_pressure_ulcer","wound_type_wound",
    "pain_management_exist_0","pain_management_exist_1",
    "pain_management_subcutaneous_injection","pain_management_oral","pain_management_iv_infusion","pain_management_patch_or_mucosal",
    "narcotic_use_yes","narcotic_use_no",
    "self_measurement_exist_0","self_measurement_exist_1",
    "self_measurement_blood_glucose","self_measurement_continuous_monitor",
    "oral_care_exist_0","oral_care_exist_1",
    "oral_visit_clinic","oral_visit_home","oral_visit_dental_hygienist_visit",
    "drug_management_exist_0","drug_management_exist_1",
    "drug_management_oral_medication","drug_management_external_medication","drug_management_suppository","drug_management_injection","drug_management_dialysis_etc",
    "rehab_equipment_exist_0","rehab_equipment_exist_1","rehab_equipment_description",
    "rehab_aids_exist_0","rehab_aids_exist_1","rehab_aids_description",
]

_FORM14_TEXT_COLS = {
    "frailty_other","dementia_other","cancer_other","circulatory_freewrite_input","bone_other","leg_circulation_freewrite_input",
    "doctor_diagnosis_note","other_hospital_1","diagnosis_1","treatment_content_1","remarks_1",
    "other_hospital_2","diagnosis_2","treatment_content_2","remarks_2",
    "rehab_equipment_description","rehab_aids_description",
}

def _form14_apply_order(row: dict) -> dict:
    out: dict = {"timestamp": row.get("timestamp", "")}
    for col in FORM14_ORDER:
        if col in _FORM14_TEXT_COLS:
            out[col] = row.get(col, "")
        else:
            v = row.get(col, 0)
            if isinstance(v, str) and v.strip() == "":
                v = 0
            out[col] = v
    return out


# ------------------------------------------------------------
# 🔹 form15 固定スキーマ（列順）
# ------------------------------------------------------------
FORM15_ORDER = [
    # Ⅰ 何かが変だ
    "strange_feeling_0","strange_feeling_1",
    "vital_change_overall_detail",
    # Ⅱ バイタルサイン
    "vital_respiration_0","vital_respiration_1",
    "vital_spo2_0","vital_spo2_1",
    "vital_temp_0","vital_temp_1",
    "vital_bp_0","vital_bp_1",
    "vital_pulse_0","vital_pulse_1",
    "consciousness_level_0","consciousness_level_1","consciousness_level_2",
    "skin_changes_0","skin_changes_1",
    # Ⅲ 呼吸困難グレード
    "dyspnea_grade_0","dyspnea_grade_1","dyspnea_grade_2","dyspnea_grade_3","dyspnea_grade_4",
    # Ⅳ NYHA 分類
    "nyha_class_0","nyha_class_I","nyha_class_II","nyha_class_III","nyha_class_IV",
]

_FORM15_TEXT_COLS = {"vital_change_overall_detail"}

def _form15_apply_order(row: dict) -> dict:
    out: dict = {"timestamp": row.get("timestamp", "")}
    for col in FORM15_ORDER:
        if col in _FORM15_TEXT_COLS:
            out[col] = row.get(col, "")
        else:
            v = row.get(col, 0)
            if isinstance(v, str) and v.strip() == "":
                v = 0
            out[col] = v
    return out


# ------------------------------------------------------------
# 🔹 form16 固定スキーマ（列順）
# ------------------------------------------------------------
FORM16_ORDER = [
    # 褥瘡の有無
    "has_bedsore_0","has_bedsore_1",

    # 深さ
    "wound_depth_d0","wound_depth_d1","wound_depth_d2","wound_depth_d3",
    "wound_depth_d4","wound_depth_d5","wound_depth_dti","wound_depth_du",

    # 滲出液
    "wound_exudate_e0","wound_exudate_e1","wound_exudate_e3","wound_exudate_e6",

    # 大きさ（サイズ）
    "wound_size_s0","wound_size_s3","wound_size_s6","wound_size_s8",
    "wound_size_s9","wound_size_s12","wound_size_s15",

    # 炎症・感染
    "wound_infection_i0","wound_infection_i1","wound_infection_i3",
    "wound_infection_i3c","wound_infection_i9",

    # 肉芽
    "wound_granulation_g0","wound_granulation_g1","wound_granulation_g3",
    "wound_granulation_g4","wound_granulation_g5","wound_granulation_g6",

    # 壊死
    "wound_necrosis_n0","wound_necrosis_n3","wound_necrosis_n6",

    # ポケット
    "wound_pocket_p0","wound_pocket_p6","wound_pocket_p6_4to16",
    "wound_pocket_p12","wound_pocket_p24",

    # 合計
    "wound_total_score",

    # 画像（front/back）
    "pain_image_front","pain_image_back",
    "mahi_image_front","mahi_image_back",
    "kan_image_front","kan_image_back",
]


_FORM16_TEXT_COLS = {"wound_total_score","pain_image_front","pain_image_back","mahi_image_front","mahi_image_back","kan_image_front","kan_image_back"}

def _form16_apply_order(row: dict) -> dict:
    # raw has_bedsore → one-hot 補完
    try:
        if not any(k.startswith("has_bedsore_") for k in row.keys()):
            val = str(row.get("has_bedsore", "")).strip()
            if val in ("0","1"):
                row["has_bedsore_0"] = 1 if val == "0" else 0
                row["has_bedsore_1"] = 1 if val == "1" else 0
    except Exception:
        pass
    out: dict = {"timestamp": row.get("timestamp", "")}
    for col in FORM16_ORDER:
        if col in _FORM16_TEXT_COLS:
            out[col] = row.get(col, 0)
        else:
            v = row.get(col, 0)
            if isinstance(v, str) and v.strip() == "":
                v = 0
            out[col] = v
    return out


# ------------------------------------------------------------
# 🔹 画像一覧API（画像ファイル名を返す）
# ------------------------------------------------------------
@app.get("/api/uploads")
async def list_uploads(user_id: str | None = None, from_: str | None = Query(None, alias="from"), to: str | None = None):
    files: list[str] = []
    try:
        # ユーザー指定があれば CSV から紐づくファイル名を取得
        if user_id and os.path.exists(RECORDS_CSV_PATH):
            try:
                with open(RECORDS_CSV_PATH, "r", encoding="utf-8-sig", newline="") as rf:
                    reader = csv.DictReader(rf)
                    for row in reader:
                        if str(row.get("user_id", "")) != str(user_id):
                            continue
                        img = row.get("image_file", "")
                        if not img:
                            continue
                        for name in str(img).split(";"):
                            name = name.strip()
                            if name:
                                files.append(name)
            except Exception:
                pass

        # ユーザー指定が無い/CSVに無い場合は uploads ディレクトリから拾う
        if not files:
            try:
                for name in os.listdir(UPLOADS_DIR):
                    if name.lower().endswith(".jpg"):
                        files.append(name)
            except FileNotFoundError:
                files = []

        # 日付フィルタ（ファイル名中の _YYYYMMDD_HHMMSS を解釈）
        def parse_dt_from_name(n: str):
            m = re.search(r"_(\d{8}_\d{6})", n)
            if not m:
                return None
            try:
                return datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")
            except Exception:
                return None

        dt_from = None
        dt_to = None
        try:
            if from_:
                dt_from = datetime.strptime(from_ + " 00:00:00", "%Y-%m-%d %H:%M:%S")
            if to:
                dt_to = datetime.strptime(to + " 23:59:59", "%Y-%m-%d %H:%M:%S")
        except Exception:
            dt_from = dt_from
            dt_to = dt_to

        def in_range(n: str) -> bool:
            dt = parse_dt_from_name(n)
            if dt_from and dt and dt < dt_from:
                return False
            if dt_to and dt and dt > dt_to:
                return False
            return True

        files = [f for f in files if in_range(f)]

        # ソート（日時降順→名前）
        files.sort(key=lambda n: (parse_dt_from_name(n) or datetime.min, n), reverse=True)
        return files
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ------------------------------------------------------------
# 🔹 form17 固定スキーマ（薬剤一覧・副作用・飲み方）
# ------------------------------------------------------------
FORM17_ORDER = [
    # ①〜㉔ 薬カテゴリ（各 0/1）
    *[item for i in range(1, 25) for item in (f"med_name_{i}_0", f"med_name_{i}_1")],

    # 薬の写真（24枚）
    *[f"med_image_{i}_filename" for i in range(1, 25)],

    # 副作用
    "side_effect_0","side_effect_1","side_effect_detail",

    # 薬の飲み方
    "medicine_usage_0","medicine_usage_0a","medicine_usage_1",

    # 薬の詳細（a〜h）
    "medicine_detail_a","medicine_detail_b","medicine_detail_c","medicine_detail_d",
    "medicine_detail_e","medicine_detail_f","medicine_detail_g","medicine_detail_h",
]


_FORM17_TEXT_COLS = set(
    ["side_effect_detail","medicine_usage"]
    + [f"med_image_{i}_filename" for i in range(1, 25)]
    + [f"emotional_distress_{i}_filename" for i in range(0, 25)]
)

def _form17_apply_order(row: dict) -> dict:
    """form17: 一部の値を補正して列順を固定。
    - medicine_detail[]_x → medicine_detail_x にエイリアス
    - medicine_usage は one-hot から逆変換（'_0','_0a','_1' を統合）
    """
    # 薬のあり/なし（各 1..24）: 単一列の 0/1 を one-hot へ展開
    try:
        for i in range(1, 25):
            base = f"med_name_{i}"
            if base in row and (f"{base}_0" not in row and f"{base}_1" not in row):
                val = str(row.get(base, "")).strip().lower()
                if val in ("1", "あり", "yes"):
                    row[f"{base}_1"] = 1
                    row[f"{base}_0"] = 0
                elif val in ("0", "なし", "no"):
                    row[f"{base}_1"] = 0
                    row[f"{base}_0"] = 1
                else:
                    # 未選択は両方0
                    row[f"{base}_1"] = 0
                    row[f"{base}_0"] = 0
    except Exception:
        pass
    # side_effect（あり/なし）→ one-hot 補完
    try:
        if ("side_effect_0" not in row and "side_effect_1" not in row) and ("side_effect" in row):
            val = str(row.get("side_effect", "")).strip()
            if val in ("あり", "1", "yes", "Yes"):
                row["side_effect_1"] = 1
                row["side_effect_0"] = 0
            elif val in ("なし", "0", "no", "No"):
                row["side_effect_1"] = 0
                row["side_effect_0"] = 1
            else:
                row["side_effect_1"] = 0
                row["side_effect_0"] = 0
    except Exception:
        pass
    # medicine_usage（0 / 0a / 1）→ one-hot 補完
    try:
        if ("medicine_usage_0" not in row and "medicine_usage_0a" not in row and "medicine_usage_1" not in row):
            val = str(row.get("medicine_usage", "")).strip().lower()
            row["medicine_usage_0"] = 1 if val == "0" else 0
            row["medicine_usage_0a"] = 1 if val in ("0a", "0-a") else 0
            row["medicine_usage_1"] = 1 if val == "1" else 0
    except Exception:
        pass
    # medicine_detail の alias（[] が付いていた場合に対応）
    for key in list(row.keys()):
        if key.startswith("medicine_detail[]_"):
            suffix = key.split("_", 1)[1]  # 例: []_a
            alias = suffix.replace("[]_", "").lstrip("_")
            target = f"medicine_detail_{alias}"
            row[target] = row.get(key, 0)

    # medicine_usage の逆変換
    if "medicine_usage" not in row:
        for candidate in ["0a","0","1"]:
            k = f"medicine_usage_{candidate}"
            v = row.get(k, 0)
            try:
                v = int(v)
            except Exception:
                v = 0 if str(v).strip() in ("", "0") else 1
            if v == 1:
                row["medicine_usage"] = candidate
                break
        if "medicine_usage" not in row:
            row["medicine_usage"] = ""

    out: dict = {"timestamp": row.get("timestamp", "")}
    for col in FORM17_ORDER:
        if col in _FORM17_TEXT_COLS:
            out[col] = row.get(col, "")
        else:
            v = row.get(col, 0)
            if isinstance(v, str) and v.strip() == "":
                v = 0
            out[col] = v
    return out


# ------------------------------------------------------------
# 🔹 form18 固定スキーマ（EOL・症状スコア・希望・意思決定）
# ------------------------------------------------------------
FORM18_SCALE_BASES = [
    "physical_activity","pain","numbness","drowsiness","fatigue",
    "shortness_of_breath","loss_of_appetite","nausea","sleep","emotional_distress",
]

# 0-10 スケール列の出力名エイリアス（フォーム間の衝突回避）
FORM18_SCALE_ALIASES = {
    "fatigue": "fatigue_score",
    "physical_activity": "physical_activity_score",
}

def _encode_0_10(out: dict, row: dict, base: str):
    try:
        val_str = str(row.get(base, "")).strip()
        sel = int(val_str) if val_str != "" else None
    except Exception:
        sel = None
    out_base = FORM18_SCALE_ALIASES.get(base, base)
    # ループを使わず固定で 0..10 を埋める
    out[f"{out_base}_0"]  = 1 if (sel == 0)  else 0
    out[f"{out_base}_1"]  = 1 if (sel == 1)  else 0
    out[f"{out_base}_2"]  = 1 if (sel == 2)  else 0
    out[f"{out_base}_3"]  = 1 if (sel == 3)  else 0
    out[f"{out_base}_4"]  = 1 if (sel == 4)  else 0
    out[f"{out_base}_5"]  = 1 if (sel == 5)  else 0
    out[f"{out_base}_6"]  = 1 if (sel == 6)  else 0
    out[f"{out_base}_7"]  = 1 if (sel == 7)  else 0
    out[f"{out_base}_8"]  = 1 if (sel == 8)  else 0
    out[f"{out_base}_9"]  = 1 if (sel == 9)  else 0
    out[f"{out_base}_10"] = 1 if (sel == 10) else 0
    # 物理的活動は CSV で専用名（_f18）としても出力（ユーザー要望の明示列）
    if base == "physical_activity":
        out[f"physical_activity_f18_0"]  = 1 if (sel == 0)  else 0
        out[f"physical_activity_f18_1"]  = 1 if (sel == 1)  else 0
        out[f"physical_activity_f18_2"]  = 1 if (sel == 2)  else 0
        out[f"physical_activity_f18_3"]  = 1 if (sel == 3)  else 0
        out[f"physical_activity_f18_4"]  = 1 if (sel == 4)  else 0
        out[f"physical_activity_f18_5"]  = 1 if (sel == 5)  else 0
        out[f"physical_activity_f18_6"]  = 1 if (sel == 6)  else 0
        out[f"physical_activity_f18_7"]  = 1 if (sel == 7)  else 0
        out[f"physical_activity_f18_8"]  = 1 if (sel == 8)  else 0
        out[f"physical_activity_f18_9"]  = 1 if (sel == 9)  else 0
        out[f"physical_activity_f18_10"] = 1 if (sel == 10) else 0

FORM18_ORDER = [

    # Ⅰ エンドオブライフ判断
    "induction_consultation_0","induction_consultation_1",
    "induction_detail_discussion","induction_detail_support","induction_detail_values",

    # Ⅱ 症状スコア（0〜10、各11個）
    # 1. 身体活動
    *[f"physical_activity_f18_{i}" for i in range(0, 11)],

    # 2. 痛み
    *[f"pain_{i}" for i in range(0, 11)],

    # 3. しびれ
    *[f"numbness_{i}" for i in range(0, 11)],

    # 4. 眠け
    *[f"drowsiness_{i}" for i in range(0, 11)],

    # 5. だるさ（疲れ）
    *[f"fatigue_score_{i}" for i in range(0, 11)],

    # 6. 息切れ
    *[f"shortness_of_breath_{i}" for i in range(0, 11)],

    # 7. 食欲不振
    *[f"loss_of_appetite_{i}" for i in range(0, 11)],

    # 8. 吐き気
    *[f"nausea_{i}" for i in range(0, 11)],

    # 9. 睡眠
    *[f"sleep_{i}" for i in range(0, 11)],

    # 10. 気持ちのつらさ
    *[f"emotional_distress_{i}" for i in range(0, 11)],

    # Ⅲ 救急搬送（a〜f）
    "emergency_transport_wish_a","emergency_transport_wish_b",
    "emergency_transport_wish_c","emergency_transport_wish_d",
    "emergency_transport_wish_e","emergency_transport_wish_f",

    # Ⅳ 望む治療 / 望まない治療（0/1）
    "treatment_respirator_0","treatment_respirator_1",
    "treatment_central_venous_nutrition_0","treatment_central_venous_nutrition_1",
    "treatment_infusion_hydration_0","treatment_infusion_hydration_1",
    "treatment_chemotherapy_0","treatment_chemotherapy_1",
    "treatment_tube_feeding_0","treatment_tube_feeding_1",
    "treatment_drug_therapy_0","treatment_drug_therapy_1",
    "treatment_dialysis_0","treatment_dialysis_1",
    "treatment_blood_transfusion_0","treatment_blood_transfusion_1",
    "treatment_cardiac_massage_0","treatment_cardiac_massage_1",
    "treatment_other_detail",

    # Ⅴ 延命措置（3択）
    "life_prolongation_no_prolongation",
    "life_prolongation_palliative_care",
    "life_prolongation_withdraw_life_support",

    # Ⅵ 受入れ
    "acceptance_individual_0","acceptance_individual_1",
    "acceptance_family_0","acceptance_family_1",
]


_FORM18_TEXT_COLS = {
    "treatment_other_detail",
    "induction_detail_discussion_text","induction_detail_support_text","induction_detail_values_text",
}

def _form18_apply_order(row: dict) -> dict:
    out: dict = {"timestamp": row.get("timestamp", "")}
    # エンドオブライフ判断（0/1）を one-hot に補完
    try:
        val = str(row.get("induction_consultation", "")).strip()
        if val in ("0", "1"):
            out["induction_consultation_0"] = 1 if val == "0" else 0
            out["induction_consultation_1"] = 1 if val == "1" else 0
    except Exception:
        pass
    # form18: 疲労スコアは別名からも受理
    if "fatigue" not in row and "fatigue_score" in row:
        row["fatigue"] = row.get("fatigue_score", "")

    # エンドオブライフ詳細（複数選択）→ one-hot（discussion/support/values）
    try:
        vals = row.get("induction_detail[]")
        if vals is None:
            vals = row.get("induction_detail")
        if isinstance(vals, str) and vals != "":
            vals = [vals]
        if not isinstance(vals, list):
            vals = []
        vals = [str(v).strip().lower() for v in vals if str(v).strip() != ""]
        m = {
            "discussion": "induction_detail_discussion",
            "support": "induction_detail_support",
            "values": "induction_detail_values",
        }
        for key, col in m.items():
            text_val = row.get(col, "")
            if isinstance(text_val, list):
                text_val = ";".join(str(x) for x in text_val)
            row[f"{col}_text"] = "" if text_val in ("", None) else str(text_val)
            row[col] = 1 if key in vals else 0
    except Exception:
        for col in ("induction_detail_discussion","induction_detail_support","induction_detail_values"):
            row.setdefault(f"{col}_text", "")
            row.setdefault(col, 0)
    # 救急搬送の希望 a..f（数字1..6や大文字A..Fでも受理）→ one-hot
    try:
        wish_raw = str(row.get("emergency_transport_wish", "")).strip()
        wish = wish_raw.lower()
        # 既に列名（emergency_transport_wish_a など）で来た場合は末尾を利用
        if wish.startswith("emergency_transport_wish_"):
            wish = wish.split("_")[-1]
        # 数字や大文字を a..f に正規化
        num_to_letter = {"1":"a","2":"b","3":"c","4":"d","5":"e","6":"f"}
        if wish in num_to_letter:
            wish = num_to_letter[wish]
        if wish in ("a","b","c","d","e","f","A","B","C","D","E","F"):
            wish = wish.lower()
        # one-hot 出力（未該当は 0）
        for ch in ["a","b","c","d","e","f"]:
            out[f"emergency_transport_wish_{ch}"] = 1 if wish == ch else 0
    except Exception:
        pass
    # 望む/望まない治療（0/1）を one-hot
    try:
        treatment_bases = [
            "treatment_respirator",
            "treatment_central_venous_nutrition",
            "treatment_infusion_hydration",
            "treatment_chemotherapy",
            "treatment_tube_feeding",
            "treatment_drug_therapy",
            "treatment_dialysis",
            "treatment_blood_transfusion",
            "treatment_cardiac_massage",
        ]
        for base in treatment_bases:
            tv = str(row.get(base, "")).strip()
            if tv in ("0","1"):
                out[f"{base}_0"] = 1 if tv == "0" else 0
                out[f"{base}_1"] = 1 if tv == "1" else 0
    except Exception:
        pass
    # 延命の希望（単一選択）→ one-hot
    try:
        lp = str(row.get("life_prolongation", "")).strip()
        for key in ["no_prolongation","palliative_care","withdraw_life_support"]:
            out[f"life_prolongation_{key}"] = 1 if lp == key else 0
    except Exception:
        pass
    # 受入れ（本人/家族 0/1）→ one-hot
    try:
        for base in ["acceptance_individual","acceptance_family"]:
            v = str(row.get(base, "")).strip()
            if v in ("0","1"):
                out[f"{base}_0"] = 1 if v == "0" else 0
                out[f"{base}_1"] = 1 if v == "1" else 0
            out[base] = v if v in ("0","1") else ""
    except Exception:
        pass
    # 0-10 スケールを強制 one-hot 化
    for b in FORM18_SCALE_BASES:
        _encode_0_10(out, row, b)
    # 通常列
    for col in FORM18_ORDER:
        if col in out:
            continue
        if col in _FORM18_TEXT_COLS:
            out[col] = row.get(col, "")
        elif col.endswith(tuple(str(i) for i in range(0,11))) and any(col.startswith(f"{FORM18_SCALE_ALIASES.get(b, b)}_") for b in FORM18_SCALE_BASES):
            # すでに out に設定済み（スケール）
            continue
        else:
            v = row.get(col, 0)
            if isinstance(v, str) and v.strip() == "":
                v = 0
            out[col] = v
    return out


# ------------------------------------------------------------
# 🔹 form19 固定スキーマ（転倒・不安・骨折・体温調節・虐待・孤独死・火水・NEWS・特異行動）
# ------------------------------------------------------------
FORM19_ORDER = [
    # ① 転倒・転落
    "fall_0","fall_1","fall_count","fall_detail",
    # ② 転倒の不安
    "fall_anxiety_0","fall_anxiety_1","fall_anxiety_2",
    "anxiety_reason_aging_muscle","anxiety_reason_disease","anxiety_reason_medicine",
    "anxiety_reason_internal_other","internal_other_text","anxiety_reason_environment_external",
    # ③ 骨折・その可能性
    "fracture_0","fracture_1","fracture_cause_fall","fracture_cause_other",
    "fracture_count","fracture_location","height_decrease_check","height_decrease",
    "back_curved","back_pain",
    # ③.5 薬物乱用/向精神薬過剰服用
    "drug_abuse_0","drug_abuse_1","drug_abuse_detail_a","drug_abuse_detail_b","drug_abuse_detail_c",
    # ④ 体温調節機能・皮膚感覚の低下
    "choking_risk_0","choking_risk_1","choking_detail_a","choking_detail_b","choking_detail_c",
    # ⑤ 虐待総合評価
    "abuse_evaluation_0","abuse_evaluation_1","abuse_detail_a","abuse_detail_b","abuse_detail_c",
    # ⑥ 孤独死
    "kodokushi_feeling_0","kodokushi_feeling_1","kodokushi_feeling_2","kodokushi_feeling_3",
    # ⑦ 火や水道の不始末
    "fire_water_negligence_0","fire_water_negligence_1","fire_water_detail_a","fire_water_detail_b","fire_water_detail_c",
    # ⑧ NEWS評価
    "news_eval_0","news_eval_1",
    # ⑨ 脱水予防
    "dehydration_0","dehydration_1",
    # ⑩ 特異行動の重症度
    "abnormal_behavior_0","abnormal_behavior_1","abnormal_behavior_2","abnormal_behavior_3",
]

_FORM19_TEXT_COLS = {"fall_detail","fracture_location","internal_other_text"}
_FORM19_NUMERIC_COLS = {"fall_count","fracture_count","height_decrease"}

def _form19_apply_order(row: dict) -> dict:
    out: dict = {"timestamp": row.get("timestamp", "")}
    # --- 受信値 → 固定スキーマ one-hot の補完（UIの name を列名へ変換）---
    # 事前クリア: 自動保存等で送られてくる既存 one-hot 値（FORM19_ORDERに含まれる列）は一旦除去して再計算する
    try:
        for key in list(row.keys()):
            if key in FORM19_ORDER:
                row.pop(key, None)
    except Exception:
        pass
    try:
        # レガシー名の補正（back_curv → back_curved）
        if "back_curv" in row and "back_curved" not in row:
            row["back_curved"] = row.get("back_curv")
        # ① 転倒・転落（select: fall 0/1 → fall_0/fall_1）
        _v = str(row.get("fall", "")).strip()
        if _v in ("0", "1"):
            row["fall_0"] = 1 if _v == "0" else 0
            row["fall_1"] = 1 if _v == "1" else 0
        # ② 転倒の不安（select: 0/1/2 → fall_anxiety_0/1/2）
        _v = str(row.get("fall_anxiety", "")).strip()
        if _v in ("0", "1", "2"):
            row["fall_anxiety_0"] = 1 if _v == "0" else 0
            row["fall_anxiety_1"] = 1 if _v == "1" else 0
            row["fall_anxiety_2"] = 1 if _v == "2" else 0
        # ② 不安の要因（checkbox: anxiety_reason[]）
        reasons = row.get("anxiety_reason[]") or row.get("anxiety_reason")
        if isinstance(reasons, str):
            # 送信側が単一文字列の場合も配列化
            reasons = [reasons]
        if isinstance(reasons, list):
            flags = {
                "aging_muscle": "anxiety_reason_aging_muscle",
                "disease": "anxiety_reason_disease",
                "medicine": "anxiety_reason_medicine",
                "internal_other": "anxiety_reason_internal_other",
                "environment_external": "anxiety_reason_environment_external",
            }
            for key, col in flags.items():
                row[col] = 1 if key in reasons else 0
        # ③ 骨折（select: fracture 0/1 → fracture_0/1）
        _v = str(row.get("fracture", "")).strip()
        if _v in ("0", "1"):
            row["fracture_0"] = 1 if _v == "0" else 0
            row["fracture_1"] = 1 if _v == "1" else 0
        # ③ 骨折原因（radio: fracture_cause fall/other → fracture_cause_fall/other）
        _v = str(row.get("fracture_cause", "")).strip()
        if _v in ("fall", "other"):
            row["fracture_cause_fall"] = 1 if _v == "fall" else 0
            row["fracture_cause_other"] = 1 if _v == "other" else 0
        # ③ 身長低下フラグ（数値 > 0 なら 1）
        try:
            hd = row.get("height_decrease", 0)
            if isinstance(hd, str) and hd.strip() != "":
                hd_num = float(hd)
            elif isinstance(hd, (int, float)):
                hd_num = float(hd)
            else:
                hd_num = 0.0
            row["height_decrease_check"] = 1 if hd_num > 0 else 0
        except Exception:
            pass
        # ③ チェックボックス群（back_curved/back_pain）を 0/1 に正規化
        def _to01(val):
            if isinstance(val, list):
                return 1 if len(val) > 0 else 0
            if isinstance(val, str):
                s = val.strip().lower()
                return 1 if s in ("on", "1", "true", "yes") else 0
            if isinstance(val, (int, float)):
                return 1 if float(val) != 0.0 else 0
            return 1 if val else 0
        if "back_curved" in row:
            row["back_curved"] = _to01(row.get("back_curved"))
        if "back_pain" in row:
            row["back_pain"] = _to01(row.get("back_pain"))
        # ③.5 薬物乱用/向精神薬過剰服用（drug_abuse 0/1 → drug_abuse_0/1）
        _v = str(row.get("drug_abuse", "")).strip()
        if _v in ("0", "1"):
            row["drug_abuse_0"] = 1 if _v == "0" else 0
            row["drug_abuse_1"] = 1 if _v == "1" else 0
        # ③.5 詳細（radio: drug_abuse_type a/b/c → drug_abuse_detail_a/b/c）
        _v = str(row.get("drug_abuse_type", "")).strip().lower()
        if _v in ("a", "b", "c"):
            for t in ("a", "b", "c"):
                row[f"drug_abuse_detail_{t}"] = 1 if _v == t else 0
        # ④ 体温調節/皮膚感覚低下（UI名は choking_risk）→ choking_risk_0/1
        _v = str(row.get("choking_risk", "")).strip()
        if _v in ("0", "1"):
            row["choking_risk_0"] = 1 if _v == "0" else 0
            row["choking_risk_1"] = 1 if _v == "1" else 0
        # ④ 詳細（radio: choking_detail_type a/b/c → choking_detail_a/b/c）
        _v = str(row.get("choking_detail_type", "")).strip().lower()
        if _v in ("a", "b", "c"):
            for t in ("a", "b", "c"):
                row[f"choking_detail_{t}"] = 1 if _v == t else 0
        # ⑤ 虐待総合評価（abuse_evaluation 0/1 → abuse_evaluation_0/1）
        _v = str(row.get("abuse_evaluation", "")).strip()
        if _v in ("0", "1"):
            row["abuse_evaluation_0"] = 1 if _v == "0" else 0
            row["abuse_evaluation_1"] = 1 if _v == "1" else 0
        # ⑤ 虐待の詳細（radio: abuse_detail_type a/b/c → abuse_detail_a/b/c）
        _v = str(row.get("abuse_detail_type", "")).strip()
        if _v in ("a", "b", "c"):
            for t in ("a", "b", "c"):
                row[f"abuse_detail_{t}"] = 1 if _v == t else 0
        # ⑥ 孤独死（kodokushi_feeling 0..3 → kodokushi_feeling_0..3）
        _v = str(row.get("kodokushi_feeling", "")).strip()
        if _v in ("0", "1", "2", "3"):
            for t in ("0", "1", "2", "3"):
                row[f"kodokushi_feeling_{t}"] = 1 if _v == t else 0
        # ⑦ 火や水道の不始末（fire_water_negligence 0/1 → fire_water_negligence_0/1）
        _v = str(row.get("fire_water_negligence", "")).strip()
        if _v in ("0", "1"):
            row["fire_water_negligence_0"] = 1 if _v == "0" else 0
            row["fire_water_negligence_1"] = 1 if _v == "1" else 0
        # ⑦ 詳細（radio: fire_water_detail_type a/b/c → fire_water_detail_a/b/c）
        _v = str(row.get("fire_water_detail_type", "")).strip()
        if _v in ("a", "b", "c"):
            for t in ("a", "b", "c"):
                row[f"fire_water_detail_{t}"] = 1 if _v == t else 0
        # ⑧ NEWS評価（UI名: news_risk 0/1 → news_eval_0/1）
        _v = str(row.get("news_risk", "")).strip()
        if _v in ("0", "1"):
            row["news_eval_0"] = 1 if _v == "0" else 0
            row["news_eval_1"] = 1 if _v == "1" else 0
        # ⑨ 脱水予防（UI名: dehydration_prevention 0/1 → dehydration_0/1）
        _v = str(row.get("dehydration_prevention", "")).strip()
        if _v in ("0", "1"):
            row["dehydration_0"] = 1 if _v == "0" else 0
            row["dehydration_1"] = 1 if _v == "1" else 0
        # ⑩ 特異行動の重症度（UI名: abnormal_behavior_severity 0..3 → abnormal_behavior_0..3）
        _v = str(row.get("abnormal_behavior_severity", "")).strip()
        if _v in ("0", "1", "2", "3"):
            for t in ("0", "1", "2", "3"):
                row[f"abnormal_behavior_{t}"] = 1 if _v == t else 0
    except Exception:
        pass

    for col in FORM19_ORDER:
        if col in _FORM19_TEXT_COLS:
            out[col] = row.get(col, "")
        else:
            v = row.get(col, 0)
            if isinstance(v, str):
                if v.strip() == "":
                    v = 0 if col not in _FORM19_TEXT_COLS else ""
                else:
                    if col in _FORM19_NUMERIC_COLS:
                        try:
                            v = int(v)
                        except Exception:
                            try:
                                v = float(v)
                            except Exception:
                                v = 0
            out[col] = v
    return out

# ------------------------------------------------------------
# 🔹 CSV 読み込み
# ------------------------------------------------------------
def _read_header(path: str) -> list[str] | None:
    """既存CSVのヘッダを取得"""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as rf:
            reader = csv.reader(rf)
            header = next(reader, None)
            return header
    except Exception as e:
        print("⚠️ ヘッダ読み込み失敗:", e)
        return None





# ------------------------------------------------------------
# 🔹 CSV アップサート（ユーザー1人＝1行）
# ------------------------------------------------------------
def _upsert_row(path: str, row: dict, key_fields: list[str] | None = None):
    """
    key_fields（例: user_id）で既存行を特定し、見つかればその行を更新、なければ追加。
    - 列は自動で拡張（既存列 + 新規列）
    - 同一フォームから送られた値は空文字でも上書き（テキストのクリア操作を反映）
    """
    key_fields = key_fields or ["user_id"]
    # 必須キーが無い場合は保存をスキップ（行を増やさない）
    if all((not str(row.get(k, "")).strip()) for k in key_fields):
        print(f"⚠️ upsert: 必須キー {key_fields} が空のためスキップします。")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)

    drop_columns = {"session", "form_id", "pain_management_suppository", "side_effect"}
    # 旧仕様の「activity_*（時間帯の後半が無い）」列は廃止して新仕様 activity_6_8 等へ一本化
    legacy_activity_cols = {
        "activity_6","activity_8","activity_10","activity_12","activity_14",
        "activity_16","activity_18","activity_20","activity_22",
    }
    drop_columns |= legacy_activity_cols
    # form19 のレガシー列（表記ゆれ）
    legacy_form19_cols = {
        "back_curv",  # 正式名は back_curved
    }
    drop_columns |= legacy_form19_cols
    # 旧 form3 のベース列/レガシー列をヘッダから除去（one-hot 列のみ残す）
    legacy_form3_cols = {
        # ベースキー（one-hot 化後は不要）
        "residence", "residence_type", "apartment",
        "elevator",
        "entrance", "entrance_to_road",
        "reform_need", "reform_place",
        "care_tool_need", "care_tool_type",
        "equipment_need", "equipment_type",
        "social_service_usage",
        # 旧画像用一時列（現在は image_file/image_url と room_photo_image_filename を使用）
        "room_photo_image",
    }
    drop_columns |= legacy_form3_cols
    # form18 のスケール旧列（衝突回避のため別名に移行）
    legacy_form18_fatigue = {f"fatigue_{i}" for i in range(2, 11)}
    legacy_form18_physical = {f"physical_activity_{i}" for i in range(2, 11)}
    drop_columns |= legacy_form18_fatigue
    drop_columns |= legacy_form18_physical
    # form17 のレガシー列（単一列 0/1 → one-hot に移行）
    legacy_form17_cols = {f"med_name_{i}" for i in range(1, 25)}
    drop_columns |= legacy_form17_cols

    existing_header = _read_header(path)
    if existing_header is not None:
        existing_header = [h for h in existing_header if h not in drop_columns]
    rows = []
    if existing_header is not None:
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as rf:
                reader = csv.DictReader(rf)
                loaded = list(reader)
                # 既存行からも不要列を除去して保持
                rows = []
                for r in loaded:
                    filtered = {k: v for k, v in r.items() if k not in drop_columns}
                    rows.append(filtered)
        except Exception as e:
            print("⚠️ 既存データ読み込み失敗:", e)
            rows = []

    # ヘッダをマージ
    if existing_header is None:
        # 新規作成時は全フォームの固定スキーマを統合したマスタヘッダで初期化
        def _get_master_header() -> list[str]:
            base = ["timestamp", "office_id", "personal_id", "user_id"]
            orders: list[list[str]] = []
            for i in range(0, 20):
                name = f"FORM{i}_ORDER"
                if name in globals():
                    orders.append(list(globals()[name]))
            seen = set(base)
            header = list(base)
            for order in orders:
                for col in order:
                    if col not in seen:
                        header.append(col)
                        seen.add(col)
            # 画像列は最後尾に
            for col in ("image_file", "image_url"):
                if col not in seen:
                    header.append(col)
                    seen.add(col)
            # 念のため現在の行キーも取り込む
            for col in row.keys():
                if col not in seen:
                    header.append(col)
                    seen.add(col)
            return header

        merged_header = [h for h in _get_master_header() if h not in drop_columns]
    else:
        # 既存 + マスタヘッダ + 今回の行 で欠けを補完
        def _get_master_header() -> list[str]:
            base = ["timestamp", "user_id"]
            orders: list[list[str]] = []
            for i in range(0, 20):
                name = f"FORM{i}_ORDER"
                if name in globals():
                    orders.append(list(globals()[name]))
            seen = set(base)
            header = list(base)
            for order in orders:
                for col in order:
                    if col not in seen:
                        header.append(col)
                        seen.add(col)
            for col in ("image_file", "image_url"):
                if col not in seen:
                    header.append(col)
                    seen.add(col)
            return header

        master_header = [h for h in _get_master_header() if h not in drop_columns]
        seen_order = list(existing_header)
        # まず既存を基準に保持
        # 次にマスタにあるが既存に無い列を追加
        for k in master_header:
            if k not in seen_order:
                seen_order.append(k)
        # 最後に今回の行で新規の列を追加
        for k in row.keys():
            if k not in seen_order:
                seen_order.append(k)
        # 並び順の補正：physical_activity_f18_* を pain_* より前（かつ physical_activity_score_* の直後）に移動
        try:
            pa_f18_cols = [c for c in seen_order if c.startswith("physical_activity_f18_")]
            if pa_f18_cols:
                # いったん削除
                seen_order = [c for c in seen_order if not c.startswith("physical_activity_f18_")]
                # 挿入位置を決定
                insert_idx = None
                # 1) pain_0 の直前に入れる
                if "pain_0" in seen_order:
                    insert_idx = seen_order.index("pain_0")
                else:
                    # 2) physical_activity_score_* の直後に入れる
                    pa_score_cols = [c for c in seen_order if c.startswith(f"{FORM18_SCALE_ALIASES.get('physical_activity','physical_activity')}_")]
                    if pa_score_cols:
                        last_pa_score = max(pa_score_cols, key=lambda x: int(x.rsplit("_", 1)[1]) if x.rsplit("_",1)[1].isdigit() else -1)
                        insert_idx = seen_order.index(last_pa_score) + 1
                # 3) 見つからなければ先頭近く（EOL 後）に入れる
                if insert_idx is None:
                    try:
                        # "induction_detail_values" の直後
                        insert_idx = seen_order.index("induction_detail_values") + 1
                    except Exception:
                        insert_idx = 0
                # 挿入
                seen_order = seen_order[:insert_idx] + pa_f18_cols + seen_order[insert_idx:]
        except Exception:
            pass
        merged_header = seen_order

    # デバッグ: レガシー activity 列の残存とヘッダ先頭の確認
    try:
        legacy_present = [c for c in merged_header if c in legacy_activity_cols]
        if legacy_present:
            print("⚠️ legacy activity columns still present in header (will be dropped):", legacy_present)
        print("📋 merged header sample:", merged_header[:40])
    except Exception:
        pass

    # 既存ヘッダとCHOICE_MASTERから one-hot のベース候補を推定
    def infer_one_hot_bases(headers: list[str]) -> set[str]:
        bases: set[str] = set(CHOICE_MASTER.keys())
        for col in headers:
            if "_" in col and col not in {"timestamp", "form_id", "image_file", "image_url", "user_id", "office_id", "personal_id"}:
                base = col.rsplit("_", 1)[0]
                if base:
                    bases.add(base)
        return bases

    one_hot_bases = infer_one_hot_bases(merged_header)

    def is_one_hot_col(col: str) -> bool:
        # form2 の activity_* はテキスト列なので one-hot 対象外
        if isinstance(col, str) and col.startswith("activity_"):
            return False
        # form2 の自由記述や詳細テキストは one-hot 対象外
        if isinstance(col, str) and (
            col.startswith("option_detail_")
            or col in {
                "public_medical_reason",
                "public_medical_detail_other",
                "medical_disease_name",
                "economic_status_3_difficulties_other",
                "room_safety",
                "room_photo_image_filename",
                "social_service_reason_text",
            }
        ):
            return False
        if "_" not in col:
            return False
        base = col.rsplit("_", 1)[0]
        return base in one_hot_bases

    # 既存行の検索
    def match_key_set(keys: list[str], r: dict) -> bool:
        for k in keys:
            if str(r.get(k, "")).strip() != str(row.get(k, "")).strip():
                return False
        return True

    # マッチ候補（user_id が無ければ office_id+personal_id で探す）
    key_candidates: list[list[str]] = []
    key_candidates.append(key_fields)
    if (not row.get("user_id")) and row.get("office_id") and row.get("personal_id"):
        key_candidates.append(["office_id","personal_id"])

    matched_index = None
    for idx, r in enumerate(rows):
        for keys in key_candidates:
            if match_key_set(keys, r):
                matched_index = idx
                break
        if matched_index is not None:
            break

    def choose_value(col: str, old: str):
        if col in row:
            v = row[col]
            # フォーム側で空欄にした場合は空文字で上書きしてクリアを反映する
            return v
        return old

    if matched_index is None:
        # 新規追加（キー欠落時はappend）
        for k in key_fields:
            if k not in row or row[k] in (None, ""):
                # user_id が無いが office_id+personal_id がある場合は生成
                if k == "user_id" and row.get("office_id") and row.get("personal_id"):
                    row["user_id"] = f"{row.get('office_id')}_{row.get('personal_id')}"
                else:
                    print(f"⚠️ upsert: key '{k}' が無く1行化できません。appendします。")
        new_row = {}
        for k in merged_header:
            v = row.get(k, "")
            # 未入力は one-hot 列なら 0 を入れる
            if (v == "" or v is None) and is_one_hot_col(k):
                v = "0"
            new_row[k] = v
        rows.append(new_row)
        target_index = len(rows) - 1
    else:
        cur = rows[matched_index]
        updated = {k: choose_value(k, cur.get(k, "")) for k in merged_header}
        rows[matched_index] = updated
        target_index = matched_index

    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8-sig", newline="") as wf:
        writer = csv.DictWriter(wf, fieldnames=merged_header)
        writer.writeheader()
        for idx, r in enumerate(rows):
            out_row = {}
            for k in merged_header:
                v = r.get(k, "")
                if (v == "" or v is None) and is_one_hot_col(k):
                    v = "0"
                out_row[k] = v
            # デバッグ: 書き込み直前の form2 用 activity_* を確認
            if idx == target_index:
                try:
                    # テキスト列フラグの確認を同時に出力
                    try:
                        print("🧪 check text flags:", {c: (c in _FORM2_TEXT_COLS) for c in (ACTIVITY_COLS if 'ACTIVITY_COLS' in globals() else [])})
                    except Exception:
                        pass
                    debug_csv = {k: out_row.get(k, "") for k in (
                        "activity_6_8","activity_8_10","activity_10_12","activity_12_14",
                        "activity_14_16","activity_16_18","activity_18_20","activity_20_22","activity_22_6",
                    )}
                    print("🧩 before CSV write:", debug_csv)
                    # form2 の public_medical / option_detail まわりの直前値も確認
                    keys_pub = [
                        "public_medical_usage_0","public_medical_usage_1","public_medical_usage_2",
                        "public_medical_detail_1","public_medical_detail_2","public_medical_detail_3",
                        "public_medical_detail_4","public_medical_detail_5","public_medical_detail_6",
                        "public_medical_detail_1a","public_medical_detail_1b","public_medical_detail_1c","public_medical_detail_1d",
                        "public_medical_detail_2a","public_medical_detail_2b","public_medical_detail_2c",
                        "public_medical_detail_3_check","public_medical_detail_other","medical_disease_name",
                    ]
                    keys_opt = ["option_detail_1","option_detail_2","option_detail_3"]
                    print("🧩 before CSV write (public_medical):", {k: out_row.get(k, "") for k in keys_pub if k in out_row})
                    print("🧩 before CSV write (option_detail):", {k: out_row.get(k, "") for k in keys_opt if k in out_row})
                    print("▶ upsert OUT:", {k: out_row.get(k, "") for k in (ACTIVITY_COLS if 'ACTIVITY_COLS' in globals() else [])})
                except Exception:
                    pass
            writer.writerow(out_row)
    os.replace(tmp_path, path)


# ------------------------------------------------------------
# 🔹 動作確認用ルート
# ------------------------------------------------------------
@app.get("/")
async def root():
    """動作確認用のルート"""
    return {"status": "running", "message": "FastAPI server for APOS-HC is active."}

# ------------------------------------------------------------
# 🔹 本番用ヘルパー群（画像保存/ディレクトリ作成/Refererからform_id抽出）
# ------------------------------------------------------------
def _ensure_dirs():
    os.makedirs(os.path.dirname(RECORDS_CSV_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(DEMO_CSV_PATH), exist_ok=True)
    os.makedirs(UPLOADS_DIR, exist_ok=True)


def _extract_form_id_from_referer(referer: str | None) -> str | None:
    if not referer:
        return None
    m = re.search(r"/forms/(form\d+)\.html", referer)
    if m:
        return m.group(1)
    m = re.search(r"/(form\d+)\.html", referer)
    return m.group(1) if m else None


def _decode_and_save_images(payload: dict, form_id: str, now: datetime):
    """
    画像DataURLを保存し、(保存ファイル一覧, 元キー名→ファイル名の対応) を返す。
    """
    saved_files: list[str] = []
    key_to_filename: dict[str, str] = {}
    ts = now.strftime("%Y%m%d_%H%M%S")
    idx = 1
    for k, v in list(payload.items()):
        if not isinstance(v, str):
            continue
        if not v.startswith("data:image/"):
            continue
        try:
            header, b64data = v.split(",", 1)
        except ValueError:
            continue
        # 画像タイプの許容（JPEG/PNG）。PNGでも受け取り、拡張子はjpgで保存
        lower = header.lower()
        if not (lower.startswith("data:image/jpeg") or lower.startswith("data:image/jpg") or lower.startswith("data:image/png")):
            continue
        try:
            binary = base64.b64decode(b64data, validate=True)
        except Exception:
            continue
        fname = f"{form_id}_{ts}_{idx}.jpg"
        fpath = os.path.join(UPLOADS_DIR, fname)
        with open(fpath, "wb") as wf:
            wf.write(binary)
        saved_files.append(fname)
        key_to_filename[k] = fname
        idx += 1
        # CSVが肥大化しないよう、payloadから画像データを除去
        del payload[k]
    return saved_files, key_to_filename




# ------------------------------------------------------------
# 🟩 共通保存エンドポイント（form0, form1, form2…を統一管理）
# ------------------------------------------------------------
@app.post("/api/form{form_num}")
async def save_form_section(form_num: int, request: Request):
    """
    form0.html / form1.html / form2.html などのページデータを共通保存
    """
    try:
        _ensure_dirs()

        payload = await request.json()
        if not isinstance(payload, dict):
            return {"status": "error", "message": "Invalid JSON"}

        # form_idを自動設定
        form_id = payload.get("form_id") or f"form{form_num}"
        now = datetime.now(timezone(timedelta(hours=9)))
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

        # 画像保存 + データをフラット化（DataURL → jpg ファイル）
        image_files, image_key_map = _decode_and_save_images(payload, form_id, now)
        field_types = payload.pop("field_types", None)
        flattened = _flatten_payload(payload, field_types)

        # ユーザー識別
        uid = (payload.get("user_id") or flattened.get("user_id") or "").strip()
        office_id = (payload.get("office_id") or flattened.get("office_id") or "").strip()
        personal_id = (payload.get("personal_id") or flattened.get("personal_id") or "").strip()
        if not uid and office_id and personal_id:
            uid = f"{office_id}_{personal_id}"
            flattened["user_id"] = uid

        # 行データ作成
        row = {"timestamp": timestamp, "form_id": form_id}
        row.update(flattened)
        if uid:
            row["user_id"] = uid

        # 画像列は常に出力（無ければ空文字）
        row["image_file"] = ";".join(image_files) if image_files else ""
        row["image_url"] = ";".join(f"{BASE_UPLOAD_URL}/{fname}" for fname in image_files) if image_files else ""

     

         elif form_id == "form2":
            form2_only = _form2_apply_order(row)
            # デバッグ: _form2_apply_order 適用後の主要列を確認
            try:
                debug_after_activity = {
                    k: form2_only.get(k, "")
                    for k in (
                        "activity_6_8","activity_8_10","activity_10_12","activity_12_14",
                        "activity_14_16","activity_16_18","activity_18_20","activity_20_22","activity_22_6",
                    )
                }
                debug_after_public = {
                    k: form2_only.get(k, "")
                    for k in form2_only.keys()
                    if isinstance(k, str)
                    and (
                        k.startswith("public_medical_")
                        or k.startswith("expensive_cost_")
                        or k.startswith("economic_status_")
                        or k.startswith("option_detail_")
                    )
                }
                print("✅ after _form2_apply_order (activity):", debug_after_activity)
                print("✅ after _form2_apply_order (public/exp/econ/option):", debug_after_public)
            except Exception:
                pass
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form2_only["timestamp"], "form_id": form_id, "user_id": uid}, **form2_only, **img_cols}
        elif form_id == "form3":
            form3_only = _form3_apply_order_and_image(row)
            # デバッグ: form3 の主要 one-hot / 数値・テキスト列を確認
            try:
                debug_f3 = {}
                for k in list(form3_only.keys()):
                    if (
                        k.startswith("residence_type_")
                        or k.startswith("elevator_")
                        or k.startswith("entrance_to_road_")
                        or k.startswith("reform_need_")
                        or k.startswith("reform_place_")
                        or k.startswith("care_tool_need_")
                        or k.startswith("care_tool_type_")
                        or k.startswith("equipment_need_")
                        or k.startswith("equipment_type_")
                        or k.startswith("social_service_usage_")
                        or k in ("apartment_floor","room_safety","room_photo_image_filename","social_service_reason_text")
                    ):
                        debug_f3[k] = form3_only.get(k, "")
                print("🏠 form3 payload (residence/elevator/entrance/reform/tools/equipment):", debug_f3)
            except Exception:
                pass
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form3_only["timestamp"], "form_id": form_id, "user_id": uid}, **form3_only, **img_cols}
        elif form_id == "form4":
            form4_only = _form4_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form4_only["timestamp"], "form_id": form_id, "user_id": uid}, **form4_only, **img_cols}
        elif form_id == "form5":
            form5_only = _form5_apply_order(row)
            # デバッグ: form5 の主要列を確認
            try:
                keys_rel = [f"relationship_status_{i}" for i in range(4)]
                keys_con = [f"consultation_status_{i}" for i in range(2)]
                keys_sp1 = [f"social_participation_1_{t}" for t in ("a","b","c","d")]
                debug_f5 = {k: form5_only.get(k, "") for k in (keys_rel + keys_con + keys_sp1)}
                print("🏷 form5 payload (rel/consult/sp1):", debug_f5)
            except Exception:
                pass
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form5_only["timestamp"], "form_id": form_id, "user_id": uid}, **form5_only, **img_cols}
        elif form_id == "form6":
            form6_only = _form6_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form6_only["timestamp"], "form_id": form_id, "user_id": uid}, **form6_only, **img_cols}
        elif form_id == "form7":
            form7_only = _form7_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form7_only["timestamp"], "form_id": form_id, "user_id": uid}, **form7_only, **img_cols}
        elif form_id == "form8":
            form8_only = _form8_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form8_only["timestamp"], "form_id": form_id, "user_id": uid}, **form8_only, **img_cols}
        elif form_id == "form9":
            form9_only = _form9_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form9_only["timestamp"], "form_id": form_id, "user_id": uid}, **form9_only, **img_cols}
        elif form_id == "form10":
            form10_only = _form10_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            # form10 は URL 列は不要
            img_cols.pop("image_url", None)
            row = {**{"timestamp": form10_only["timestamp"], "form_id": form_id, "user_id": uid}, **form10_only, **img_cols}
        elif form_id == "form11":
            form11_only = _form11_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form11_only["timestamp"], "form_id": form_id, "user_id": uid}, **form11_only, **img_cols}
        elif form_id == "form12":
            form12_only = _form12_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form12_only["timestamp"], "form_id": form_id, "user_id": uid}, **form12_only, **img_cols}
        elif form_id == "form13":
            form13_only = _form13_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form13_only["timestamp"], "form_id": form_id, "user_id": uid}, **form13_only, **img_cols}
        elif form_id == "form14":
            form14_only = _form14_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form14_only["timestamp"], "form_id": form_id, "user_id": uid}, **form14_only, **img_cols}
        elif form_id == "form15":
            form15_only = _form15_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form15_only["timestamp"], "form_id": form_id, "user_id": uid}, **form15_only, **img_cols}
        elif form_id == "form16":
            form16_only = _form16_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form16_only["timestamp"], "form_id": form_id, "user_id": uid}, **form16_only, **img_cols}
        elif form_id == "form17":
            form17_only = _form17_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form17_only["timestamp"], "form_id": form_id, "user_id": uid}, **form17_only, **img_cols}
        elif form_id == "form18":
            form18_only = _form18_apply_order(row)
            img_cols = {k: row[k] for k in ("image_file","image_url") if k in row}
            row = {**{"timestamp": form18_only["timestamp"], "form_id": form_id, "user_id": uid}, **form18_only, **img_cols}
        # 不要列をCSVから除外
        for k in ("session", "form_id"):
            row.pop(k, None)

        # CSVへアップサート
        _upsert_row(RECORDS_CSV_PATH, row, KEY_FIELDS)

        return {"status": "ok", "form_id": form_id, "timestamp": timestamp}

    except Exception as e:
        return {"status": "error", "message": str(e)}

