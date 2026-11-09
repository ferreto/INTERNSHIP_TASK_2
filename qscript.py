import json
import os
import random
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PATH_TO_VIDEO_FOLDER = "./video"

_ACTIVE_PAGE = None


CURSOR_SCRIPT = r"""
(() => {
  const INSTALL = () => {
    if (!document.documentElement) { setTimeout(INSTALL, 0); return; }
    if (document.getElementById('__pw_cursor_root')) return;

    const root = document.createElement('div');
    root.id = '__pw_cursor_root';
    root.style.cssText =
      'position:fixed;inset:0;pointer-events:none;z-index:2147483647;overflow:hidden;';
    document.documentElement.appendChild(root);

    const circle = document.createElement('div');
    circle.style.cssText =
      'position:fixed;width:64px;height:64px;border-radius:50%;' +
      'background:rgba(255,235,59,0.45);transform:translate(-50%,-50%);' +
      'left:-9999px;top:-9999px;pointer-events:none;';
    root.appendChild(circle);

    const svgNS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('width', '32');
    svg.setAttribute('height', '32');
    svg.style.cssText =
      'position:fixed;left:-9999px;top:-9999px;pointer-events:none;' +
      'filter:drop-shadow(0 0 2px rgba(0,0,0,0.4));';
    const path = document.createElementNS(svgNS, 'path');
    path.setAttribute('d', 'M4,4 L4,26 L11,20 L15,29 L19,27 L15,18 L24,18 Z');
    path.setAttribute('fill', 'white');
    path.setAttribute('stroke', 'black');
    path.setAttribute('stroke-width', '2');
    path.setAttribute('stroke-linejoin', 'round');
    svg.appendChild(path);
    root.appendChild(svg);

    const zoomRing = document.createElement('div');
    zoomRing.style.cssText =
      'position:fixed;width:100px;height:100px;border-radius:50%;' +
      'border:6px solid transparent;transform:translate(-50%,-50%);' +
      'left:-9999px;top:-9999px;pointer-events:none;transition:border-color 0.2s;';
    root.appendChild(zoomRing);

    let lastX = 0, lastY = 0;
    let isZoomed = false;

    window.__pw_cursor_move = (x, y) => {
      lastX = x; lastY = y;
      circle.style.left = x + 'px';
      circle.style.top  = y + 'px';
      svg.style.left = (x - 4) + 'px';
      svg.style.top  = (y - 4) + 'px';
      if (isZoomed) {
        zoomRing.style.left = x + 'px';
        zoomRing.style.top  = y + 'px';
      }
    };

    window.__pw_cursor_ripple = (x, y) => {
      const r = document.createElement('div');
      r.style.cssText =
        'position:fixed;left:' + x + 'px;top:' + y + 'px;' +
        'width:10px;height:10px;border-radius:50%;' +
        'background:rgba(255,235,59,0.7);transform:translate(-50%,-50%);' +
        'pointer-events:none;' +
        'transition:width 0.5s ease-out,height 0.5s ease-out,opacity 0.5s ease-out;';
      root.appendChild(r);
      requestAnimationFrame(() => {
        r.style.width = '72px';
        r.style.height = '72px';
        r.style.opacity = '0';
      });
      setTimeout(() => r.remove(), 600);
    };

    window.__pw_cursor_callout = (text, bg, fg, fade) => {
      const box = document.createElement('div');
      box.style.cssText =
        'position:fixed;left:60px;bottom:60px;' +
        'background:' + bg + ';color:' + fg + ';' +
        'font-family:sans-serif;font-size:16pt;padding:10px 16px;' +
        'border-radius:8px;pointer-events:none;opacity:0;' +
        'transition:opacity ' + fade + 'ms ease-in-out;' +
        'box-shadow:0 2px 8px rgba(0,0,0,0.3);max-width:70vw;z-index:1;';
      box.textContent = text;
      root.appendChild(box);
      requestAnimationFrame(() => { box.style.opacity = '1'; });
      setTimeout(() => { box.style.opacity = '0'; }, fade + 2000);
      setTimeout(() => { box.remove(); }, fade * 2 + 2500);
    };

    function applyZoomVisual(zoomed, x, y) {
      if (zoomed) {
        zoomRing.style.borderColor = 'rgba(255, 0, 0, 0.8)';
        zoomRing.style.left = x + 'px';
        zoomRing.style.top = y + 'px';
      } else {
        zoomRing.style.borderColor = 'transparent';
        zoomRing.style.left = '-9999px';
        zoomRing.style.top = '-9999px';
      }
    }

    function toggleZoom(x, y) {
      isZoomed = !isZoomed;
      const type = isZoomed ? "in" : "out";
      if (window.report_zoom) {
        window.report_zoom({ x: Math.round(x), y: Math.round(y), type: type });
      }
      applyZoomVisual(isZoomed, x, y);
    }

    window._zoomAt = (x, y) => { toggleZoom(x, y); };

    // Non-interfering pulse: ignores if already zoomed, always closes
    // with the SAME coordinates it opened with. Used by the automation
    // scenario to demonstrate the programmatic hook without fighting
    // with a manual F5 press by the operator.
    window._zoomPulse = (x, y, ms) => {
      if (isZoomed) return;
      toggleZoom(x, y);
      setTimeout(() => {
        if (isZoomed) toggleZoom(x, y);
      }, ms);
    };

    window.__sync_zoom_state = (zoomed) => {
      if (isZoomed === zoomed) return;
      isZoomed = zoomed;
      applyZoomVisual(isZoomed, lastX, lastY);
    };

    document.addEventListener('keydown', (e) => {
      if (e.key === 'F5') {
        e.preventDefault();
        toggleZoom(lastX, lastY);
      }
    }, true);

    document.addEventListener('mousemove',
      (e) => window.__pw_cursor_move(e.clientX, e.clientY), true);
    document.addEventListener('mousedown',
      (e) => window.__pw_cursor_ripple(e.clientX, e.clientY), true);
  };

  INSTALL();
})();
"""


def _smooth_move(page, from_xy, to_xy, duration_ms=700, steps=30):
    x1, y1 = from_xy
    x2, y2 = to_xy
    for i in range(1, steps + 1):
        t = i / steps
        e = t * t * (3 - 2 * t)
        page.mouse.move(x1 + (x2 - x1) * e, y1 + (y2 - y1) * e)
        page.wait_for_timeout(max(5, duration_ms // steps))
    return (x2, y2)


SEARCH_BUTTON_SELECTORS = (
    'button[type="submit"][aria-label="Search"]',
    'button[aria-label="Search"]',
    'form button[type="submit"]',
    'form input[type="submit"]',
)


def _find_visible(page, selectors, timeout_ms=8000):
    waited = 0
    while True:
        for sel in selectors:
            try:
                for loc in page.locator(sel).all():
                    if loc.is_visible() and loc.bounding_box():
                        return loc
            except Exception:
                pass
        if waited >= timeout_ms:
            return None
        page.wait_for_timeout(250)
        waited += 250


def _human_type(page, text, min_delay=40, max_delay=130):
    for ch in text:
        page.keyboard.type(ch)
        page.wait_for_timeout(random.randint(min_delay, max_delay))


CAPTCHA_SELECTORS = (
    "form[action*='anomaly']",
    "input[name='challenge']",
    "div[id*='anomaly']",
    "div[class*='captcha']",
    "[data-testid='anomaly-modal']",
)
CAPTCHA_TEXT_MARKERS = (
    "bots use duckduckgo too",
    "confirm this search was made by a human",
)


def _is_captcha_shown(page):
    for sel in CAPTCHA_SELECTORS:
        try:
            if page.locator(sel).first.count() > 0:
                return True
        except Exception:
            pass
    try:
        text = page.locator("body").inner_text(timeout=2000).lower()
    except Exception:
        return False
    return any(m in text for m in CAPTCHA_TEXT_MARKERS)


def _restore_cursor(page, pos, zoom_active=False):
    try:
        page.evaluate(
            "([x, y, zoomed]) => { "
            "if (window.__pw_cursor_move) window.__pw_cursor_move(x, y); "
            "if (window.__sync_zoom_state) window.__sync_zoom_state(zoomed); "
            "}",
            [pos[0], pos[1], zoom_active],
        )
    except Exception:
        pass


def _discard_video(video_obj):
    try:
        video_obj.delete()
    except Exception as e:
        print(f"[qscript] could not delete the failed recording: {e}")


def ShowCallout(text, bgColor="yellow", textColor="black", fade=2000):
    page = _ACTIVE_PAGE
    if page is None:
        return
    try:
        page.evaluate(
            "([t,b,f,d]) => { if (window.__pw_cursor_callout) "
            "window.__pw_cursor_callout(t, b, f, d); }",
            [text, bgColor, textColor, fade],
        )
    except Exception:
        pass


def _run_scenario(page, url, city, zoom_state):
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(500)

    if _is_captcha_shown(page):
        raise RuntimeError("DuckDuckGo showed a CAPTCHA right away.")

    pos = (640, 360)
    page.mouse.move(*pos)
    page.wait_for_timeout(200)

    ShowCallout(f"Searching Magento developers in {city}", fade=1500)
    page.wait_for_timeout(400)

    search_box = page.locator('textarea[name="q"]').first
    search_box.wait_for(state="visible", timeout=15000)
    bb = search_box.bounding_box()
    target = (bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
    pos = _smooth_move(page, pos, target, duration_ms=800, steps=40)
    page.wait_for_timeout(200)

    page.mouse.click(*pos)
    page.wait_for_timeout(300)

    # Demonstrates the programmatic zoom hook required by the spec:
    # "window._zoomAt toggles in/out from the scenario".
    # Uses _zoomPulse so the pair is self-contained (in → 800 ms → out
    # at the same coordinates) and does not fight a manual F5 press.
    page.evaluate(f"window._zoomPulse({pos[0]}, {pos[1]}, 800)")

    _human_type(page, f"Magento developer in {city}")
    page.wait_for_timeout(500)

    submit = _find_visible(page, SEARCH_BUTTON_SELECTORS)
    sb = submit.bounding_box() if submit is not None else None
    if not sb:
        raise RuntimeError("Search button not found")
    target = (sb["x"] + sb["width"] / 2, sb["y"] + sb["height"] / 2)
    pos = _smooth_move(page, pos, target, duration_ms=700, steps=30)
    page.wait_for_timeout(300)
    page.mouse.click(*pos)

    selectors = ['a[data-testid="result-title-a"]', "#links .result__a", "a.result__a"]
    first_result = None
    for attempt in range(120):
        _restore_cursor(page, pos, zoom_state["active"])
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.bounding_box():
                    first_result = loc
                    break
            except Exception:
                pass
        if first_result is not None:
            break
        if attempt % 4 == 3 and _is_captcha_shown(page):
            raise RuntimeError("DuckDuckGo showed a CAPTCHA after search.")
        page.wait_for_timeout(250)

    if first_result is None:
        raise RuntimeError("No search results appeared")

    page.wait_for_timeout(300)
    rb = first_result.bounding_box()
    target = (rb["x"] + rb["width"] / 2, rb["y"] + rb["height"] / 2)
    pos = _smooth_move(page, pos, target, duration_ms=700, steps=30)
    page.wait_for_timeout(300)
    page.mouse.click(*pos)
    page.wait_for_timeout(1500)

    _restore_cursor(page, pos, zoom_state["active"])


def CaptureVideo_Magento(
    url, company_name, language, country, postcode, city, street, house_no,
):
    global _ACTIVE_PAGE
    Path(PATH_TO_VIDEO_FOLDER).mkdir(parents=True, exist_ok=True)

    src = None
    zoom_events = []
    zoom_state = {"active": False}
    out_path = None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = None
            video_obj = None
            succeeded = False
            try:
                context = browser.new_context(
                    record_video_dir=PATH_TO_VIDEO_FOLDER,
                    record_video_size={"width": 1280, "height": 720},
                    viewport={"width": 1280, "height": 720},
                )
                start_time = time.time()
                context.add_init_script(CURSOR_SCRIPT)
                page = context.new_page()
                _ACTIVE_PAGE = page
                video_obj = page.video

                def on_zoom_event(source, event_data):
                    zoom_state["active"] = (event_data["type"] == "in")
                    t = round(time.time() - start_time, 2)
                    event_data["t"] = t
                    zoom_events.append(event_data)
                    print(f"    [ZOOM EVENT] t={t}, x={event_data['x']}, y={event_data['y']}, type={event_data['type']}")

                page.expose_binding("report_zoom", on_zoom_event)

                _run_scenario(page, url, city, zoom_state)
                succeeded = True
            finally:
                if context is not None:
                    try:
                        context.close()
                    except Exception:
                        pass
                if video_obj is not None:
                    if succeeded:
                        try:
                            src = str(video_obj.path())
                        except Exception as e:
                            print(f"[qscript] video.path() failed: {e}")
                    else:
                        _discard_video(video_obj)
                try:
                    browser.close()
                except Exception:
                    pass

    except Exception as e:
        print(f"[qscript] CaptureVideo_Magento failed: {e}")
        return None
    finally:
        _ACTIVE_PAGE = None

    if not src or not os.path.exists(src):
        return None

    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in (company_name or "")).strip() or "video"
    target_path = os.path.abspath(os.path.join(PATH_TO_VIDEO_FOLDER, f"{safe}.webm"))

    sidecar_at_src = src + ".zoom.json"
    sidecar_at_target = target_path + ".zoom.json"

    def _write_sidecar(path):
        sidecar_data = {
            "viewport": {"width": 1280, "height": 720},
            "fps": 25,
            "zoom_factor": 2.0,
            "ramp_sec": 0.5,
            "events": zoom_events,
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(sidecar_data, f, indent=2)
            print(f"    [ZOOM] Sidecar saved: {path}")
        except Exception as e:
            print(f"[qscript] failed to save sidecar: {e}")

    try:
        os.replace(src, target_path)
        out_path = target_path
    except Exception as e:
        print(f"[qscript] rename failed: {e}")
        out_path = os.path.abspath(src)

    if zoom_events:
        _write_sidecar(out_path + ".zoom.json")
    else:
        for p in (sidecar_at_src, sidecar_at_target, out_path + ".zoom.json"):
            if os.path.exists(p):
                try:
                    os.remove(p)
                    print(f"    [ZOOM] Stale sidecar removed: {p}")
                except Exception as e:
                    print(f"[qscript] failed to remove stale sidecar {p}: {e}")

    return out_path