import re, json
from datetime import datetime, timezone
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

URL = "https://nexflixtv.lovable.app/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
EXT = re.compile(r"\.(m3u8?|mpd)(\?|#|$)", re.I)
BODY_URL = re.compile(r"https?://[^\s\"'<>\\)]+?\.(?:m3u8?|mpd)[^\s\"'<>\\)]*", re.I)

found = {}     # url -> {"name":..., "headers":{...}, "src":...}
log = []
state = {"label": None}


def add(url, src, headers=None):
    url = url.replace("\\/", "/").replace("\\u0026", "&")
    item = found.setdefault(url, {"name": state["label"], "headers": {}, "src": src})
    if headers:
        item["headers"].update(headers)
    if not item["name"] and state["label"]:
        item["name"] = state["label"]


def scan_text(text, src):
    text = text.replace("\\/", "/").replace("\\u0026", "&")
    for u in BODY_URL.findall(text):
        add(u, src)


def on_request(r):
    log.append(f"{r.method} {r.resource_type} {r.url}")
    if EXT.search(r.url):
        h = r.headers
        add(r.url, "request", {k: h[k] for k in ("referer", "origin", "user-agent") if k in h})


def on_response(r):
    try:
        ct = (r.headers.get("content-type") or "").lower()
        if any(k in ct for k in ("json", "javascript", "text", "mpegurl", "xml")):
            body = r.text()
            if len(body) < 8_000_000:
                if body.lstrip().startswith("#EXTM3U"):
                    add(r.url, "playlist-body")
                scan_text(body, "body:" + r.url[:80])
    except Exception:
        pass


with sync_playwright() as p:
    browser = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
    ctx = browser.new_context(viewport={"width": 1366, "height": 900}, user_agent=UA)
    page = ctx.new_page()
    page.on("request", on_request)
    page.on("response", on_response)

    page.goto(URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(5000)
    for _ in range(4):
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(800)
    page.screenshot(path="debug_page.png", full_page=True)
    open("debug_page.html", "w", encoding="utf-8").write(page.content())

    # Click every candidate (channel card/button) one by one,
    # so each stream gets matched with the channel name.
    SEL = "a, button, [role=button], [class*=card], [class*=channel], [class*=Card], li"
    total = len(page.query_selector_all(SEL))
    for idx in range(min(total, 40)):
        try:
            page.goto(URL, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)
            els = page.query_selector_all(SEL)
            if idx >= len(els):
                break
            el = els[idx]
            label = (el.inner_text() or el.get_attribute("alt") or "").strip().split("\n")[0][:50]
            state["label"] = label or f"Channel {idx+1}"
            el.click(timeout=2000)
            page.wait_for_timeout(4000)
            # click a play button if the player needs it
            for sel in ["video", "[aria-label*=lay]", "button:has-text('Play')"]:
                try:
                    page.click(sel, timeout=1000)
                    page.wait_for_timeout(2000)
                except Exception:
                    pass
        except Exception:
            pass
    state["label"] = None
    scan_text(page.content(), "rendered-html")

    # Test every link with the same headers the site used
    channels = []
    for i, (u, it) in enumerate(sorted(found.items()), 1):
        hdr = {"user-agent": UA, "referer": URL, "origin": URL.rstrip("/")}
        hdr.update(it["headers"])
        status, ok = None, False
        try:
            resp = ctx.request.get(u, headers=hdr, timeout=15000)
            status = resp.status
            ok = resp.ok and ("#EXTM3U" in resp.text()[:200] or "<MPD" in resp.text()[:500])
        except Exception as e:
            status = f"error: {str(e)[:60]}"
        name = it["name"] or urlparse(u).path.rstrip("/").split("/")[-1] or f"Channel {i}"
        channels.append({"id": i, "name": name, "url": u, "http_status": status,
                         "valid_playlist": ok, "headers": hdr, "found_in": it["src"]})
    browser.close()

open("debug_requests.txt", "w", encoding="utf-8").write("\n".join(log))

with open("Sarah.json", "w", encoding="utf-8") as f:
    json.dump({"source": URL, "generated": datetime.now(timezone.utc).isoformat(),
               "count": len(channels), "channels": channels}, f, indent=2, ensure_ascii=False)

with open("Sarah.m3u", "w", encoding="utf-8") as f:
    f.write("#EXTM3U\n")
    for c in channels:
        f.write(f'#EXTINF:-1 tvg-id="{c["id"]}",{c["name"]}\n')
        f.write(f'#EXTVLCOPT:http-referrer={c["headers"].get("referer", URL)}\n')
        f.write(f'#EXTVLCOPT:http-user-agent={c["headers"].get("user-agent", UA)}\n')
        f.write(c["url"] + "\n")

print(f"Found {len(channels)} link(s)")
for c in channels:
    print(c["name"], "|", c["http_status"], "| valid:", c["valid_playlist"], "|", c["url"])
