import os
import time
import subprocess
import sys
from urllib.parse import quote

import psycopg2
import psycopg2.extras
from pathlib import Path
from flask import Flask, request, jsonify, g, send_from_directory

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "videos")
DB_USER = os.environ.get("DB_USER", "video_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "video_pass")


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = psycopg2.connect(
            host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
        )
        db.cursor_factory = psycopg2.extras.DictCursor
    return db


@app.teardown_appcontext
def close_db(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    retries = 10
    for attempt in range(retries):
        try:
            with psycopg2.connect(
                host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
                user=DB_USER, password=DB_PASSWORD,
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS videos (
                            id SERIAL PRIMARY KEY,
                            company_name TEXT NOT NULL UNIQUE,
                            file_path TEXT NOT NULL,
                            video_url TEXT NOT NULL,
                            processed_video_url TEXT,
                            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                        )
                    """)
                    cur.execute("ALTER TABLE videos ADD COLUMN IF NOT EXISTS processed_video_url TEXT;")
                conn.commit()
            print("[web_service] Database initialized successfully.")
            return
        except psycopg2.OperationalError:
            print(f"[web_service] Database not ready (attempt {attempt + 1}/{retries}). Waiting...")
            time.sleep(2)
    raise RuntimeError("Database initialization failed")


def _sanitize_filename(name):
    """Convert 'Acme Corp' -> 'Acme_Corp'. Spaces are not URL-safe.
    Matches the spec example ('ACME_GmbH.webm')."""
    cleaned = "".join(
        c if c.isalnum() or c in "-_" else "_" for c in name
    ).strip("_")
    return cleaned or "video"


@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files['file']
    company_name = request.form.get('company_name', '').strip()

    if not file or file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    if not company_name:
        return jsonify({"error": "No company_name provided"}), 400

    safe_name = _sanitize_filename(company_name)
    ext = os.path.splitext(file.filename)[1] or ".webm"
    filename = f"{safe_name}{ext}"
    filepath = UPLOAD_DIR / filename
    file.save(filepath)

    sidecar_file = request.files.get('sidecar')
    has_sidecar = False
    if sidecar_file and sidecar_file.filename != '':
        sidecar_path = str(filepath) + ".zoom.json"
        sidecar_file.save(sidecar_path)
        has_sidecar = True

    # URL-encode filename so spaces/special chars are safe in the URL.
    video_url = f"{request.host_url.rstrip('/')}/media/{quote(filename)}"
    processed_url = None

    zoomed_filename = f"{safe_name}_zoomed.webm"
    zoomed_path = UPLOAD_DIR / zoomed_filename

    if zoomed_path.exists():
        try:
            zoomed_path.unlink()
        except Exception as e:
            print(f"[web_service] Could not remove stale zoomed file: {e}")

    if has_sidecar:
        print(f"[web_service] Processing zoom for {filename}...")
        zoom_script = str(BASE_DIR / "apply_zoom.py")
        try:
            subprocess.run(
                [sys.executable, zoom_script, "--video", str(filepath), "--output", str(zoomed_path)],
                check=True, capture_output=True, text=True, timeout=300,
            )
            if zoomed_path.exists():
                processed_url = f"{request.host_url.rstrip('/')}/media/{quote(zoomed_filename)}"
                print(f"[web_service] Zoom applied: {processed_url}")
        except subprocess.CalledProcessError as e:
            print(f"[web_service] ffmpeg error: {e.stderr}")
        except FileNotFoundError as e:
            print(f"[web_service] ffmpeg/apply_zoom.py not found: {e}")
        except subprocess.TimeoutExpired:
            print("[web_service] ffmpeg timed out")
        except Exception as e:
            print(f"[web_service] unexpected error during zoom: {e}")

    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("""
                INSERT INTO videos (company_name, file_path, video_url, processed_video_url)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (company_name) DO UPDATE SET
                    file_path = EXCLUDED.file_path,
                    video_url = EXCLUDED.video_url,
                    processed_video_url = EXCLUDED.processed_video_url,
                    updated_at = NOW()
            """, (company_name, str(filepath), video_url, processed_url))
        db.commit()
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "company_name": company_name,
        "video_url": video_url,
        "processed_video_url": processed_url,
    }), 200


@app.route('/get_video_url', methods=['GET'])
def get_video_url():
    company_name = request.args.get('company_name', '').strip()
    if not company_name:
        return jsonify({"error": "company_name is required"}), 400

    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT video_url, processed_video_url FROM videos WHERE company_name = %s", (company_name,))
        row = cur.fetchone()

    if row:
        return jsonify({
            "company_name": company_name,
            "video_url": row["video_url"],
            "processed_video_url": row["processed_video_url"],
        }), 200
    else:
        return jsonify({"error": "Not found"}), 404


@app.route('/media/<path:filename>', methods=['GET'])
def serve_media(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route('/videos', methods=['GET'])
def list_videos():
    db = get_db()
    with db.cursor() as cur:
        cur.execute("SELECT * FROM videos ORDER BY updated_at DESC")
        rows = cur.fetchall()
    return jsonify([dict(r) for r in rows]), 200


init_db()