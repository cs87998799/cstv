#!/usr/bin/env python3
"""
iptvidn.py (v2) - JS file, JSON, relative link shob jaygay m3u8 khuje.
Kichu na pele debug_page.html ar debug_report.txt toiri kore.
"""
import html
import json
import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests

SITE = "http://iptvidn.com/"
OUT_JSON = "iptvidn.json"
OUT_M3U = "iptvidn.m3u"
GROUP = "IPTVIDN"
MAX_PAGES = 25
TIMEOUT = 15

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120 Mobile Safari/537.36",
    "Referer": SITE,
    "Accept": "*/*",
}

# absolute m3u8 (token thak ba na thak)
ABS_RE = re.compile(r'https?://[^\s"\'<>\\)]+?\.m3u8(?:\?[^\s"\'<>\\)]*)?')
# relative m3u8
REL_RE = re.compile(r'["\'(]((?:/|\./)?[A-Za-z0-9_\-./]+\.m3u8(?:\?[^"\')\s]*)?)["\')]')
# link/script/api khujar jonno
ATTR_RE = re.compile(r'(?:href|src|data-src|data-url|action)=["\']([^"\']+)["\']', re.I)
JS_URL_RE = re.compile(r'["\']((?:https?:)?//[^"\']+|/[A-Za-z0-9_\-./?=&%]+)["\']')
HINT_WORDS = ("api", "channel", "stream", "live", "token", "playlist", ".json", "player")

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


def clean(text):
    return html.unescape(text.replace("\\/", "/").replace("\\u0026", "&"))


def extract(text, base):
    text = clean(text)
    found = {m.group(0) for m in ABS_RE.finditer(text)}
    for m in REL_RE.finditer(text):
        found.add(urljoin(base, m.group(1)))
    return found


def channel_name(url):
    parts = [p for p in urlparse(url).path.split("/") if p]
    name = parts[0] if parts else "Unknown"
    if "tracks-v1" in parts:
        i = parts.index("tracks-v1")
        if i > 0:
            name = parts[i - 1]
    return name.replace("-", " ").replace("_", " ").strip().title()


def is_live(url):
    try:
        with session.get(url, timeout=TIMEOUT, stream=True) as r:
            if r.status_code != 200:
                return False
            return b"#EXTM3U" in next(r.iter_content(512), b"")
    except requests.RequestException:
        return False


def crawl(site):
    links, candidates, seen = set(), set(), set()
    queue = [site]
    host = urlparse(site).netloc

    while queue and len(seen) < MAX_PAGES:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        text = get(url)
        if not text:
            continue
        if url == site:
            open("debug_page.html", "w", encoding="utf-8").write(text)

        links |= extract(text, url)

        # json response hole parse kore dekho
        try:
            data = json.loads(text)
            links |= extract(json.dumps(data), url)
        except ValueError:
            pass

        # same-host page, JS file, API gulo queue te
        for raw in ATTR_RE.findall(text) + JS_URL_RE.findall(text):
            full = urljoin(url, raw)
            p = urlparse(full)
            if p.netloc == host and full not in seen:
                if any(w in full.lower() for w in HINT_WORDS) or full.endswith((".js", ".json", "/")):
                    queue.append(full)
                    if any(w in full.lower() for w in HINT_WORDS):
                        candidates.add(full)
    return links, candidates


def main():
    links, candidates = crawl(SITE)
    log(f"[info] {len(links)} m3u8 link pawa gese")

    channels = []
    for url in sorted(links, key=channel_name):
        live = is_live(url)
        log(f"[{'OK ' if live else 'DEAD'}] {channel_name(url)} {url[:90]}")
        if live:
            channels.append({"name": channel_name(url), "group": GROUP, "url": url})

    unique = {}
    for ch in channels:
        unique.setdefault(ch["name"], ch)
    channels = list(unique.values())

    if not channels:
        log("\n[!] Kono channel paini. Possible karon:")
        log("  1) Link JavaScript diye runtime e toiri hoy (API call)")
        log("  2) Site GitHub/server IP block korche")
        log("  3) Page e login lage")
        log("\nCandidate API/JS URL gulo:")
        for c in sorted(candidates):
            log("  " + c)
        open("debug_report.txt", "w", encoding="utf-8").write("\n".join(report))

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump({"source": SITE,
                   "updated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
                   "count": len(channels), "channels": channels},
                  f, ensure_ascii=False, indent=2)

    with open(OUT_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for ch in channels:
            f.write(f'#EXTINF:-1 group-title="{ch["group"]}",{ch["name"]}\n{ch["url"]}\n')

    log(f"[done] {len(channels)} live channel")


if __name__ == "__main__":
    main()
