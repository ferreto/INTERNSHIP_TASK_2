import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Apply Camtasia-style zoom to a video based on a sidecar JSON.")
    parser.add_argument("--video", required=True, help="Path to the input video")
    parser.add_argument("--output", help="Output video path (default: <input>_zoomed.webm)")
    parser.add_argument("--dry-run", action="store_true", help="Print the ffmpeg command without executing it")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="Path to the ffmpeg binary")
    parser.add_argument("--ffprobe", default="ffprobe", help="Path to the ffprobe binary")
    return parser.parse_args()


def load_sidecar(video_path):
    sidecar_path = Path(str(video_path) + ".zoom.json")
    if not sidecar_path.exists():
        return None
    with open(sidecar_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_video_info(video_path, ffprobe="ffprobe"):
    """Get width, height, and fps of the video using ffprobe."""
    try:
        result = subprocess.run([
            ffprobe, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate",
            "-of", "csv=p=0", str(video_path)
        ], capture_output=True, text=True, check=True, timeout=30)
        parts = result.stdout.strip().split(",")
        width = int(parts[0])
        height = int(parts[1])
        fps_str = parts[2]
        if "/" in fps_str:
            num, den = fps_str.split("/")
            fps = float(num) / float(den)
        else:
            fps = float(fps_str)
        return width, height, fps
    except Exception as e:
        print(f"[apply_zoom] ffprobe failed: {e}. Falling back to sidecar defaults.")
        return None, None, None


def _has_audio_stream(video_path, ffprobe="ffprobe"):
    """Check if the video has an audio stream."""
    try:
        result = subprocess.run([
            ffprobe, "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=codec_type", "-of", "csv=p=0",
            str(video_path)
        ], capture_output=True, text=True, check=True, timeout=10)
        return "audio" in result.stdout.lower()
    except Exception:
        return False


def build_zoom_filter(data, video_width=None, video_height=None, video_fps=None):
    events = data.get("events", [])
    if not events:
        return None

    viewport = data.get("viewport", {"width": 1280, "height": 720})
    vp_w = viewport.get("width", 1280)
    vp_h = viewport.get("height", 720)

    width = video_width if video_width else vp_w
    height = video_height if video_height else vp_h
    fps = video_fps if video_fps else data.get("fps", 25)

    zoom_factor = data.get("zoom_factor", 2.0)
    ramp_sec = data.get("ramp_sec", 0.5)
    ramp_frames = max(1, int(ramp_sec * fps))

    scale_x = width / vp_w if vp_w > 0 else 1.0
    scale_y = height / vp_h if vp_h > 0 else 1.0

    events = sorted(events, key=lambda e: e.get("t", 0))

    pairs = []
    current_in = None
    for ev in events:
        ev_type = ev.get("type")
        if ev_type == "in":
            if current_in is not None:
                pairs.append((current_in, {"t": ev["t"], "type": "out", "synthetic": True}))
            current_in = ev
        elif ev_type == "out":
            if current_in is not None:
                pairs.append((current_in, ev))
                current_in = None

    if current_in is not None:
        pairs.append((current_in, None))

    if not pairs:
        return None

    segments = []
    for in_ev, out_ev in pairs:
        in_frame = int(in_ev["t"] * fps)
        out_frame = int(out_ev["t"] * fps) if out_ev else 999999

        actual_ramp = min(ramp_frames, (out_frame - in_frame) // 2)
        if actual_ramp < 1:
            actual_ramp = 1

        px = int(in_ev.get("x", 640) * scale_x)
        py = int(in_ev.get("y", 360) * scale_y)

        segments.append((in_frame, in_frame + actual_ramp, "in", px, py, actual_ramp))
        segments.append((in_frame + actual_ramp, out_frame - actual_ramp, "hold", px, py, actual_ramp))
        if out_ev:
            segments.append((out_frame - actual_ramp, out_frame, "out", px, py, actual_ramp))

    z_expr = "1"
    px_expr = str(width // 2)
    py_expr = str(height // 2)

    for start, end, typ, px, py, ramp in reversed(segments):
        if end <= start:
            continue

        if typ == "in":
            t = f"((on-{start})/{ramp})"
            eased = f"({t}*{t}*(3-2*{t}))"
            seg_z = f"1+({zoom_factor}-1)*{eased}"
        elif typ == "hold":
            seg_z = f"{zoom_factor}"
        elif typ == "out":
            t = f"((on-{start})/{ramp})"
            eased = f"({t}*{t}*(3-2*{t}))"
            seg_z = f"{zoom_factor}-({zoom_factor}-1)*{eased}"
        else:
            continue

        z_expr = f"(({seg_z})*between(on,{start},{end})) + (({z_expr})*(1-between(on,{start},{end})))"
        px_expr = f"({px}*between(on,{start},{end})) + (({px_expr})*(1-between(on,{start},{end})))"
        py_expr = f"({py}*between(on,{start},{end})) + (({py_expr})*(1-between(on,{start},{end})))"

    x_expr = f"max(0,min(iw-iw/zoom,{px_expr}-iw/(2*zoom)))"
    y_expr = f"max(0,min(ih-ih/zoom,{py_expr}-ih/(2*zoom)))"

    return f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d=1:s={width}x{height}:fps={fps}"


def main():
    args = parse_args()
    video_path = Path(args.video)
    if not video_path.exists():
        print(f"Error: Video not found: {video_path}")
        return 1

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = video_path.parent / f"{video_path.stem}_zoomed.webm"

    data = load_sidecar(video_path)
    if data is None or not data.get("events"):
        if args.dry_run:
            print(f"Dry run. Would copy {video_path} to {output_path} (no zoom events).")
            return 0
        print("No zoom events found. Copying video unchanged.")
        try:
            shutil.copy2(video_path, output_path)
            print(f"Success! Copied unchanged to: {output_path}")
        except Exception as e:
            print(f"Error copying file: {e}")
            return 1
        return 0

    width, height, fps = get_video_info(video_path, args.ffprobe)

    zoom_filter = build_zoom_filter(data, width, height, fps)
    if not zoom_filter:
        if args.dry_run:
            print(f"Dry run. Would copy {video_path} to {output_path} (no valid zoom segments).")
            return 0
        print("No valid zoom segments generated. Copying unchanged.")
        # FIX: wrap in try/except for consistency with the no-events branch
        try:
            shutil.copy2(video_path, output_path)
            print(f"Success! Copied unchanged to: {output_path}")
        except Exception as e:
            print(f"Error copying file: {e}")
            return 1
        return 0

    input_ext = video_path.suffix.lower()
    if _has_audio_stream(video_path, args.ffprobe) and input_ext != ".webm":
        audio_args = ["-c:a", "libopus", "-b:a", "128k"]
    else:
        audio_args = ["-c:a", "copy"]

    cmd = [
        args.ffmpeg, "-y",
        "-i", str(video_path),
        "-vf", zoom_filter,
        "-c:v", "libvpx-vp9",
        "-crf", "30", "-b:v", "0",
        *audio_args,
        str(output_path),
    ]

    if args.dry_run:
        print("Dry run. The ffmpeg command would be:")
        print(" ".join(f'"{c}"' if " " in c else c for c in cmd))
        return 0

    print(f"Processing {video_path}...")
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=300)
        print(f"Success! Saved to: {output_path}")
    except subprocess.CalledProcessError as e:
        print(f"ffmpeg error:\n{e.stderr.decode() if e.stderr else 'unknown'}")
        return 1
    except subprocess.TimeoutExpired:
        print("ffmpeg timed out")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())