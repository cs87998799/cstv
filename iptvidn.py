#!/usr/bin/env python3
"""
iptvidn.py (v3) - teleghor.online theke channel detect kore.

Site ta JavaScript diye ekta M3U playlist load kore ("Loading channels from
playlist"). Ei script:
  1) page + JS file theke playlist/m3u/m3u8 URL khuje
  2) playlist parse kore (name, logo, group, url)
  3) (optional) live check kore
  4) iptvidn.json ar iptvidn.m3u likhe

Kichu na pele debug_page.html + debug_report.txt toiri hoy.
Env: CHECK_LIVE=0 dile live check skip hobe (druto).
"""
import html
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import requests

SITE = "https://teleghor.online/"
OUT_JSON = "iptvidn.json"
OUT_M3U = "iptvidn.m3u"
CHECK_LIVE = os.environ.get("CHECK_LIVE", "1") != "0"
MAX_FETCH = 30
TIMEOUT = 15
WORKERS = 24

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": SITE,
    "Accept": "*/*",
}
session = requests.Session()
session.headers.update(HEADERS)
report = []


def log(msg):
    print(msg)
    report.append(msg)


def get(url):
    try:
        r = session.get(url, timeout=TIMEOUT)
        log(f"[GET] {r.status_code} {url} ({len(r.text)} chars)")
        return r.text if r.ok else ""
    except requests.RequestException as e:
        log(f"[ERR] {url} -> {e}")
        return ""


def clean(t):
    return html.unescape(t.replace("\\/", "/").replace("\\u0026", "&"))


# playlist / m3u / api hishebe sondehojonok URL
URL_RE = re.compile(r'["\'`]((?:https?:)?//[^"\'`\s<>]+|/[A-Za-z0-9_\-./?=&%]+)["\'`]')
HINT = re.compile(r"\.m3u8?(?:$|\?)|playlist|\.txt(?:$|\?)|\.json(?:$|\?)|raw\.githubusercontent|"
                  r"/api/|channels|iptv", re.I)
ATTR_RE = re.compile(r'(?:src|href)=["\']([^"\']+\.js[^"\']*)["\']', re.I)


def find_candidates(text, base):
    text = clean(text)
    out = set()
    for raw in URL_RE.findall(text):
        full = urljoin(base, raw)
        if full.startswith("http") and HINT.search(full):
            out.add(full)
    for raw in ATTR_RE.findall(text):
        out.add(urljoin(base, raw))
    return out


# M3U parse
ATTR_KV = re.compile(r'([\w-]+)="([^"]*)"')


def parse_m3u(text):
    items, cur, extra = [], None, []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            head, _, name = line.partition(",")
            attrs = dict(ATTR_KV.findall(head))
            cur = {"name": name.strip() or attrs.get("tvg-name", "Unknown"),
                   "logo": attrs.get("tvg-logo", ""),
                   "group": attrs.get("group-title", "General")}
            extra = []
        elif line.startswith("#EXTVLCOPT") or line.startswith("#EXTHTTP"):
            extra.append(line)
        elif line.startswith("#"):
            continue
        elif cur is not None:
            cur["url"] = line
            cur["extra"] = extra
            items.append(cur)
            cur, extra = None, []
    return items


def looks_like_playlist(text):
    return text.lstrip().startswith("#EXTM3U") and "#EXTINF" in text


def is_live(ch):
    try:
        with session.get(ch["url"], timeout=8, stream=True) as r:
            if r.status_code != 200:
                return False
            head = next(r.iter_content(512), b"")
            return b"#EXTM3U" in head or len(head) > 0
    except requests.RequestException:
        return False


def main():
    page = get(SITE)
    open("debug_page.html", "w", encoding="utf-8").write(page)

    queue = list(find_candidates(page, SITE))
    seen, channels, js_texts = set(), [], []

    while queue and len(seen) < MAX_FETCH:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        text = get(url)
        if not text:
            continue
        if looks_like_playlist(text):
            items = parse_m3u(text)
            log(f"[PLAYLIST] {url} -> {len(items)} channel")
            channels += items
        else:
            # JSON/JS er moddhe aro URL thakte pare
            for c in find_candidates(text, url):
                if c not in seen:
                    queue.append(c)

    # page er moddhe shorashori inline M3U thakle
    if looks_like_playlist(page):
        channels += parse_m3u(page)

    # duplicate bad (same url)
    uniq = {}
    for ch in channels:
        uniq.setdefault(ch["url"], ch)
    channels = list(uniq.values())
    log(f"[info] total {len(channels)} channel pawa gese")

    if CHECK_LIVE and channels:
        with ThreadPoolExecutor(WORKERS) as ex:
            flags = list(ex.map(is_live, channels))
        channels = [c for c, ok in zip(channels, flags) if ok]
        log(f"[info] live: {len(channels)}")

    if not channels:
        log("\n[!] Kono channel paini. Karon hote pare:")
        log("  1) Playlist URL JS er moddhe encode/obfuscate kora")
        log("  2) Playlist API server IP/Referer block kore")
        log("\nCandidate URL gulo:")
        for u in sorted(seen):
            log("  " + u)
        open("debug_report.txt", "w", encoding="utf-8").write("\n".join(report))

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump({"source": SITE,
                   "updated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
                   "count": len(channels),
                   "channels": [{k: v for k, v in c.items() if k != "extra"} for c in channels]},
                  f, ensure_ascii=False, indent=2)

    with open(OUT_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for c in channels:
            f.write(f'#EXTINF:-1 tvg-logo="{c["logo"]}" group-title="{c["group"]}",{c["name"]}\n')
            for e in c.get("extra", []):
                f.write(e + "\n")
            f.write(c["url"] + "\n")

    log(f"[done] {len(channels)} channel save hoyeche")


if __name__ == "__main__":
    main()
