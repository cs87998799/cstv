#!/usr/bin/env python3
"""kbhub.online er M3U playlist download kore sarah.m3u ar sarah.json e channel save kore."""
import json
import os
import re
import sys
import urllib.request

SITE = "https://kbhub.online/"
M3U_FILE = "sarah.m3u"
JSON_FILE = "sarah.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; sarah-updater/1.0)"}
ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def find_m3u_url() -> str | None:
    url = os.environ.get("M3U_URL", "").strip()
    if url:
        return url
    html = fetch(SITE)
    m = re.search(r"https?://[^\s\"'<>]+\.m3u8?[^\s\"'<>]*", html)
    return m.group(0) if m else None


def parse_m3u(text: str) -> list[dict]:
    channels, current = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            head, _, name = line.partition(",")
            attrs = dict(ATTR_RE.findall(head))
            current = {
                "name": name.strip() or attrs.get("tvg-name", ""),
                "id": attrs.get("tvg-id", ""),
                "logo": attrs.get("tvg-logo", ""),
                "group": attrs.get("group-title", ""),
                "url": "",
            }
        elif line.startswith("#"):
            continue
        elif current is not None:
            current["url"] = line
            channels.append(current)
            current = None
    return channels


def write_m3u(channels: list[dict]) -> None:
    lines = ["#EXTM3U"]
    for c in channels:
        lines.append(
            f'#EXTINF:-1 tvg-id="{c["id"]}" tvg-logo="{c["logo"]}" '
            f'group-title="{c["group"]}",{c["name"]}'
        )
        lines.append(c["url"])
    with open(M3U_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main() -> int:
    url = find_m3u_url()
    if not url:
        print("M3U link paoa jayni. M3U_URL secret/env set korun.", file=sys.stderr)
        return 1

    print(f"Downloading: {url}")
    text = fetch(url)
    if "#EXTM3U" not in text[:200]:
        print("Response valid M3U na.", file=sys.stderr)
        return 1

    channels = parse_m3u(text)
    if not channels:
        print("Kono channel paoa jayni.", file=sys.stderr)
        return 1

    write_m3u(channels)
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"total": len(channels), "channels": channels},
            f, ensure_ascii=False, indent=2,
        )
    print(f"Done: {len(channels)} channels -> {M3U_FILE}, {JSON_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
