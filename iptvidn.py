#!/usr/bin/env python3
"""
iptvidn.py
Site theke .m3u8 link khuje ber kore, live check kore,
iptvidn.json ar iptvidn.m3u toiri kore.

Use: python iptvidn.py
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
MAX_SUBPAGES = 20
TIMEOUT = 10

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120 Mobile Safari/537.36"
}

M3U8_RE = re.compile(r'https?://[^\s"\'<>\\]+?\.m3u8\?[^\s"\'<>\\]+')
HREF_RE = re.compile(r'(?:href|src)=["\']([^"\']+)["\']', re.I)


def get(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.ok:
            return r.text
    except requests.RequestException as e:
        print(f"[warn] {url} -> {e}", file=sys.stderr)
    return ""


def clean(text):
    return html.unescape(text.replace("\\/", "/"))


def find_links(text):
    return {m.group(0) for m in M3U8_RE.finditer(clean(text))}


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
        with requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True) as r:
            if r.status_code != 200:
                return False
            head = next(r.iter_content(512), b"")
            return b"#EXTM3U" in head
    except requests.RequestException:
        return False


def crawl(site):
    links = set()
    page = get(site)
    links |= find_links(page)

    host = urlparse(site).netloc
    subpages = []
    for href in HREF_RE.findall(page):
        full = urljoin(site, href)
        if urlparse(full).netloc == host and full not in subpages and full != site:
            subpages.append(full)

    for sp in subpages[:MAX_SUBPAGES]:
        links |= find_links(get(sp))
    return links


def main():
    found = crawl(SITE)
    print(f"[info] {len(found)} link pawa gese")

    channels = []
    for url in sorted(found, key=channel_name):
        live = is_live(url)
        print(f"[{'OK ' if live else 'DEAD'}] {channel_name(url)}")
        if live:
            channels.append({"name": channel_name(url), "group": GROUP, "url": url})

    # Same channel er duplicate bad
    unique = {}
    for ch in channels:
        unique.setdefault(ch["name"], ch)
    channels = list(unique.values())

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(
            {
                "source": SITE,
                "updated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
                "count": len(channels),
                "channels": channels,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    with open(OUT_M3U, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for ch in channels:
            f.write(
                f'#EXTINF:-1 group-title="{ch["group"]}",{ch["name"]}\n{ch["url"]}\n'
            )

    print(f"[done] {len(channels)} live channel save hoyeche")


if __name__ == "__main__":
    main()
