# Camtasia-style Zoom Effect for Recorded Videos

This project extends a Dockerized browser automation video recorder with a "Camtasia-style" zoom effect.

During recording, a zoom can be triggered around the current mouse position via an F5 hotkey or programmatically. After recording, the video is automatically post-processed inside the Docker stack to render a smooth zoom-in, hold, and zoom-out effect.

## Architecture

- **Web (`web` container)**: Apache + `mod_wsgi` serving the Flask application. Listens on host port `8000`.
- **Database (`db` container)**: PostgreSQL 16. Data is persisted in a named Docker volume (`db_data`).
- **Uploads volume**: Persists recorded videos in `/app/uploads` across container restarts.
- **Recorder (Client)**: Playwright (sync API) records the browser, captures zoom events, and uploads both the video and a sidecar JSON file to the server.
- **Post-processor**: `ffmpeg` (installed inside the `web` container) processes the video based on the sidecar JSON to apply the zoom effect.

## Requirements

- [Docker](https://www.docker.com/) and Docker Compose
- Python 3.9+ (for running the local client and tests)
- FFmpeg (only if you want to run `apply_zoom.py` manually outside Docker; it is pre-installed inside the Docker container)

## 1. How to run the server (Docker)

From the root of the project:

```bash
docker compose up --build -d
```

This command will:
1. Build the `web` image (Apache, Python deps, `mod_wsgi`, `ffmpeg`).
2. Start PostgreSQL.
3. Wait for the database to be healthy.
4. Start the web server on `http://127.0.0.1:8000`.

## 2. How to record a video with zoom (Local Client)

1. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   # Windows:
   .\.venv\Scripts\activate
   # macOS/Linux:
   source .venv/bin/activate
   ```

2. Install dependencies and Playwright's Chromium:
   ```bash
   pip install -r requirements.txt
   python -m playwright install chromium
   ```

3. Run the recorder:
   ```bash
   python capture_video.py --server http://127.0.0.1:8000 --view-seconds 5
   ```

4. **Triggering Zoom during recording:**

   There are two independent ways to trigger a zoom.

   **F5 Hotkey (manual)**
   - First press: starts a zoom-in at the current mouse position (a red ring appears around the cursor).
   - Second press: starts a zoom-out.
   - If you press F5 only once and the recording ends, the zoom holds to the end of the video.

   **Programmatic hook `window._zoomAt(x, y)` and `window._zoomPulse(x, y, ms)` (automatic)**
   - The automation scenario in `qscript.py` demonstrates the programmatic hook by calling `window._zoomPulse(cx, cy, 800)` on the search box during typing.
   - This is required by the task specification (*"window._zoomAt toggles in/out from the scenario"*), and it proves the programmatic API works end-to-end.
   - `_zoomPulse` is a **non-interfering** wrapper around `_zoomAt`: it opens a zoom pair and closes it after `ms`, at the **same** `(x, y)` coordinates. If a manual zoom is already active (`isZoomed === true`), the pulse is a no-op.
   - **As a result, every recorded video will include one auto-zoom pair (in → 800 ms → out) on the search box, even if you never press F5.**

   **Coexisting with a manual F5**
   - If you press F5 *before* the pulse starts, the pulse yields (`if (isZoomed) return`).
   - If you press F5 *during* the pulse, the pulse's scheduled `out` is skipped (it also checks `if (isZoomed)`), and your manual F5 becomes the closing event.
   - The sidecar may then contain a pair whose `in` and `out` coordinates differ — that's expected, the video crop still uses the `in` point.

   **Want an F5-only recording?**
   - Comment out the `page.evaluate("window._zoomPulse(...)")` line in `_run_scenario()` inside `qscript.py`.
   - **Note:** this technically removes the scenario's use of `_zoomAt`/`_zoomPulse`, which the acceptance checklist explicitly requires. Only do this for private experimentation, not for submission.

   **Sidecar generation**
   - A `<video>.zoom.json` file is created next to the video **only if at least one zoom event occurred**.
   - If you disable the auto-zoom and never press F5, no sidecar is created.

## 3. File names and URLs

Uploaded videos are named after the company with spaces and unsafe characters replaced by underscores, matching the spec example (`ACME_GmbH.webm`).

| Company name | Uploaded file |
|---|---|
| `Acme Corp`  | `Acme_Corp.webm` (and `Acme_Corp_zoomed.webm`) |
| `Globex`     | `Globex.webm` (and `Globex_zoomed.webm`) |

The `video_url` and `processed_video_url` fields returned by the API are always URL-encoded (via `urllib.parse.quote`), so they can be opened directly in a browser or fetched by any HTTP client without extra escaping.

Example:

```json
{
  "company_name": "Acme Corp",
  "video_url": "http://127.0.0.1:8000/media/Acme_Corp.webm",
  "processed_video_url": "http://127.0.0.1:8000/media/Acme_Corp_zoomed.webm"
}
```

## 4. Testing the Zoom Logic

The zoom math, coordinate clamping, and sidecar parsing are covered by unit tests. No `ffmpeg` installation is required to run these tests.

```bash
pytest test_apply_zoom.py -v
```

*All 16 tests should pass.*

## 5. API Endpoints

- **`POST /upload`**
  Accepts `multipart/form-data` with `file` (video), `company_name` (string), and an optional `sidecar` (JSON). Saves the file, processes the zoom (if sidecar is present), and upserts the record in PostgreSQL. Returns JSON with `company_name`, `video_url`, and `processed_video_url`.

- **`GET /get_video_url?company_name=<name>`**
  Returns JSON with `company_name`, `video_url`, and `processed_video_url`. Returns HTTP 404 if the company is not found.

- **`GET /media/<filename>`**
  Serves the uploaded video file (original or processed) for playback in the browser.

- **`GET /videos`**
  Returns a JSON list of all stored video records (useful for debugging).

## 6. Data Persistence

The project uses named Docker volumes (`db_data` and `uploads`).
If you stop the containers with `docker compose down`, your videos and database records will **not** be lost.

## Project Structure

- `qscript.py` — Playwright automation, custom cursor, F5 zoom capture, programmatic `_zoomAt`/`_zoomPulse`, sidecar generation.
- `capture_video.py` — Local client entry point (reads CSV, triggers recording).
- `video_client.py` — HTTP client for uploading video and sidecar to the server.
- `apply_zoom.py` — FFmpeg post-processing script (uses `ffprobe` to preserve resolution and fps).
- `test_apply_zoom.py` — Pytest unit tests.
- `web_service.py` — Flask application (PostgreSQL + ffmpeg integration).
- `Dockerfile` — Builds the Apache + Flask + FFmpeg image.
- `docker-compose.yml` — Defines the `web` and `db` services, volumes, and healthcheck.
- `apache-config.conf` — Apache VirtualHost configuration.
- `web_service.wsgi` — WSGI entry point for Apache.
- `requirements.txt` — Python dependencies.