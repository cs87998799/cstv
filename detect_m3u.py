
import re
import json
import html
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from pathlib import Path

SITE = "https://www.tv.cricflixs.com/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
}

session = requests.Session()
session.headers.update(HEADERS)

found = set()
checked_pages = set()
errors = []

def get_page(url):
    try:
        response = session.get(url, timeout=25)
        response.raise_for_status()
        return response.text
    except Exception as e:
        errors.append(f"{url}: {e}")
        print(f"[ERROR] {url}: {e}")
        return ""

def extract_urls(text, base):
    text = html.unescape(text)
    text = text.replace("\\/", "/").replace("\\u0026", "&")

    patterns = [
        r'https?://[^\s"\'<>\\]+',
        r'(?:https?:)?//[^\s"\'<>\\]+',
        r'["\']([^"\']+\.(?:m3u8?|m3u)(?:\?[^"\']*)?)["\']',
        r'["\']([^"\']*(?:get\.php|playlist)[^"\']*)["\']'
    ]

    for pattern in patterns:
        for match in re.findall(pattern, text, re.I):
            url = match if isinstance(match, str) else match[0]
            url = url.strip().rstrip("),;")
            if url.startswith("//"):
                url = "https:" + url
            elif not url.startswith("http"):
                url = urljoin(base, url)

            if url.startswith(("http://", "https://")):
                parsed = urlparse(url)
                if re.search(r'\.(m3u8?|m3u)(?:$|\?)', parsed.path, re.I) or re.search(
                    r'(?:get\.php|playlist)', url, re.I
                ):
                    found.add(url)

def scan_site():
    queue = [SITE]

    while queue:
        page_url = queue.pop(0)

        if page_url in checked_pages:
            continue

        checked_pages.add(page_url)
        print(f"[SCAN] {page_url}")

        source = get_page(page_url)
        if not source:
            continue

        extract_urls(source, page_url)
        soup = BeautifulSoup(source, "html.parser")

        # Scan JavaScript files
        for tag in soup.find_all("script", src=True):
            script_url = urljoin(page_url, tag["src"])
            script = get_page(script_url)
            if script:
                extract_urls(script, script_url)

        # Scan same-site linked pages (maximum 30)
        for tag in soup.find_all("a", href=True):
            link = urljoin(page_url, tag["href"])
            parsed = urlparse(link)

            if (parsed.netloc == urlparse(SITE).netloc
                    and parsed.scheme in ("http", "https")
                    and link not in checked_pages
                    and len(checked_pages) + len(queue) < 30):
                queue.append(link)

        # Scan iframe sources
        for tag in soup.find_all("iframe", src=True):
            link = urljoin(page_url, tag["src"])
            if urlparse(link).netloc == urlparse(SITE).netloc:
                if link not in checked_pages:
                    queue.append(link)

def validate(url):
    try:
        response = session.get(
            url, timeout=20, stream=True,
            headers={"Range": "bytes=0-65535"}
        )

        content_type = response.headers.get("Content-Type", "").lower()
        first = next(response.iter_content(4096), b"")
        response.close()

        is_playlist = (
            b"#EXTM3U" in first
            or "mpegurl" in content_type
        )

        return {
            "url": url,
            "status": response.status_code,
            "content_type": content_type,
            "playlist_detected": is_playlist
        }

    except Exception as e:
        return {
            "url": url,
            "status": "ERROR",
            "playlist_detected": False,
            "error": str(e)
        }

scan_site()

print(f"\nFound candidates: {len(found)}")

results = [validate(url) for url in sorted(found)]

valid = [r for r in results if r["playlist_detected"]]

Path("detected-m3u.txt").write_text(
    "\n".join(r["url"] for r in valid) + ("\n" if valid else ""),
    encoding="utf-8"
)

Path("m3u_sources.json").write_text(
    json.dumps(results, indent=2, ensure_ascii=False),
    encoding="utf-8"
)

report = [
    "# Cricflix M3U Detection Report",
    "",
    f"- Website: {SITE}",
    f"- Pages scanned: {len(checked_pages)}",
    f"- Candidate links: {len(found)}",
    f"- Playlist responses detected: {len(valid)}",
    "",
    "## Detected playlist URLs",
    ""
]

report += [f"- {r['url']}" for r in valid]
report += ["", "## Scan errors", ""]
report += [f"- {e}" for e in errors]

Path("report.md").write_text("\n".join(report), encoding="utf-8")

print(f"Verified playlist responses: {len(valid)}")
print("Detection completed.")
