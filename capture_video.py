import argparse
import csv
import os
import sys
from pathlib import Path

import qscript


def _field(row, key):
    value = row.get(key, "")
    return (value or "").strip()


def _preview_video(url, view_seconds):
    """Открывает браузер для предпросмотра загруженного видео."""
    # Ленивый импорт, чтобы скрипт работал без Playwright, если превью не нужно
    from playwright.sync_api import sync_playwright

    print(f"    Opening preview (view-seconds={view_seconds}): {url}")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            page.goto(url)
            
            if view_seconds > 0:
                page.wait_for_timeout(view_seconds * 1000)
            else:
                print("    >>> Press ENTER in the terminal to close the preview <<<")
                input()
            
            browser.close()
    except Exception as e:
        print(f"    PREVIEW ERROR: {e}")


def main(argv):
    parser = argparse.ArgumentParser(description="Record browser automation videos and optionally upload them.")
    parser.add_argument("csv_path", nargs="?", default="input.csv", help="Path to CSV file (default: input.csv)")
    parser.add_argument("--server", help="Server URL for uploading (e.g. http://127.0.0.1:8000)", default=None)
    parser.add_argument("--view-seconds", type=int, default=0, help="Seconds to keep preview open (0 = wait for Enter)")
    
    args = parser.parse_args(argv[1:])
    csv_path = args.csv_path

    if not os.path.exists(csv_path):
        print(f"[capture_video] CSV not found: {csv_path}")
        return 1

    # Make sure the video folder exists and is absolute.
    video_dir = Path(qscript.PATH_TO_VIDEO_FOLDER).resolve()
    video_dir.mkdir(parents=True, exist_ok=True)
    qscript.PATH_TO_VIDEO_FOLDER = str(video_dir)

    total = 0
    ok = 0
    failed = 0

    # Ленивый импорт клиента и requests, только если указан сервер
    if args.server:
        try:
            import video_client
        except ImportError:
            print("[capture_video] ERROR: 'requests' or 'video_client' missing. Run pip install -r requirements.txt")
            return 1

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(
            f, delimiter=";", quotechar='"', skipinitialspace=True
        )
        for i, row in enumerate(reader, start=1):
            row = {(k or "").strip(): v for k, v in row.items()}

            total += 1
            company_name = _field(row, "Company Name") or f"row_{i}"
            url = _field(row, "URL")

            print(f"\n[{i}] {company_name} -> {url}")
            try:
                result = qscript.CaptureVideo_Magento(
                    url=url,
                    company_name=company_name,
                    language=_field(row, "Language"),
                    country=_field(row, "Country"),
                    postcode=_field(row, "Postcode"),
                    city=_field(row, "City"),
                    street=_field(row, "Street"),
                    house_no=_field(row, "HouseNo"),
                )
            except Exception as e:
                print(f"    ERROR: {e}")
                failed += 1
                continue

            if result:
                print(f"    Saved: {result}")
                ok += 1
                
                # Загрузка и превью, если указан сервер
                if args.server:
                    try:
                        video_url = video_client.UploadVideo(args.server, result, company_name)
                        print(f"    Uploaded: {video_url}")
                        _preview_video(video_url, args.view_seconds)
                    except Exception as e:
                        print(f"    UPLOAD/PREVIEW ERROR: {e}")
            else:
                print("    FAILED (no video)")
                failed += 1

    print(f"\nDone. rows={total} ok={ok} failed={failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
