import re
import json
import html
import time
import requests

from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlsplit, urlunsplit

# =====================================
# CONFIGURATION
# =====================================

SITE = "https://www.tv.cricflixs.com/"
MAX_PAGES = 25
TIMEOUT = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/130 Safari/537.36"
    ),
    "Accept": "*/*",
}

session = requests.Session()
session.headers.update(HEADERS)

found = set()
visited = set()
errors = []
results = []

# =====================================
# SAFE URL NORMALIZATION
# =====================================

def normalize_url(raw, base):
    try:
        raw = html.unescape(str(raw))
        raw = raw.replace("\\/", "/")
        raw = raw.replace("\\u0026", "&")
        raw = raw.strip()

        raw = raw.strip("\"'<> \t\r\n")
        raw = raw.rstrip(".,;:!?)")

        if not raw:
            return None

        if raw.startswith("//"):
            raw = "https:" + raw

        elif not raw.startswith(("http://", "https://")):
            raw = urljoin(base, raw)

        parsed = urlsplit(raw)

        if parsed.scheme not in ("http", "https"):
            return None

        if not parsed.hostname:
            return None

        # Force port validation
        _ = parsed.port

        return urlunsplit(parsed)

    except (ValueError, TypeError, UnicodeError):
        print("[SKIP] Invalid URL:", str(raw)[:150])
        return None


def is_playlist_url(url):
    try:
        parsed = urlsplit(url)

        target = parsed.path + "?" + parsed.query

        return bool(re.search(
            r"\.(?:m3u8?|m3u)(?:$|[?&])|"
            r"(?:get\.php|playlist|manifest)",
            target,
            re.I
        ))

    except (ValueError, TypeError):
        return False


# =====================================
# HTTP REQUEST
# =====================================

def fetch(url):
    try:
        response = session.get(
            url,
            timeout=TIMEOUT,
            allow_redirects=True
        )

        response.raise_for_status()

        return response.text

    except requests.RequestException as e:
        errors.append(f"{url} : {e}")
        print("[FETCH ERROR]", str(e)[:200])
        return ""


# =====================================
# URL EXTRACTION
# =====================================

def extract_urls(source, base):
    if not source:
        return

    source = html.unescape(source)
    source = source.replace("\\/", "/")
    source = source.replace("\\u0026", "&")

    patterns = [
        r'https?://[^\s"\'<>\\]+',
        r'(?<!:)//[a-zA-Z0-9.-]+(?::\d+)?/[^\s"\'<>\\]+',
        r'["\']([^"\']+\.(?:m3u8?|m3u)(?:\?[^"\']*)?)["\']',
        r'["\']([^"\']*(?:get\.php|playlist|manifest)[^"\']*)["\']'
    ]

    for pattern in patterns:
        try:
            matches = re.findall(pattern, source, re.I)
        except re.error:
            continue

        for item in matches:
            if isinstance(item, tuple):
                item = item[0]

            url = normalize_url(item, base)

            if url and is_playlist_url(url):
                found.add(url)
                print("[FOUND]", url)


# =====================================
# SCAN HTML / JAVASCRIPT
# =====================================

def scan_page(url):
    print("\n[SCAN]", url)

    source = fetch(url)

    if not source:
        return

    extract_urls(source, url)

    try:
        soup = BeautifulSoup(source, "html.parser")
    except Exception as e:
        errors.append(f"HTML parse error: {e}")
        return

    # Inline JavaScript and JSON
    for script in soup.find_all("script"):
        if script.string:
            extract_urls(script.string, url)

        elif script.get_text():
            extract_urls(script.get_text(), url)

    # External JavaScript
    for tag in soup.find_all("script", src=True):
        script_url = normalize_url(tag["src"], url)

        if not script_url:
            continue

        print("[JS]", script_url)

        js_source = fetch(script_url)

        if js_source:
            extract_urls(js_source, script_url)

    # Iframes
    for tag in soup.find_all("iframe", src=True):
        frame_url = normalize_url(tag["src"], url)

        if frame_url:
            host = urlsplit(frame_url).hostname

            if host == urlsplit(SITE).hostname:
                if frame_url not in visited:
                    scan_queue.append(frame_url)

    # Same-site internal pages
    for tag in soup.find_all("a", href=True):
        link = normalize_url(tag["href"], url)

        if not link:
            continue

        try:
            if urlsplit(link).hostname == urlsplit(SITE).hostname:
                if link not in visited and len(scan_queue) < MAX_PAGES:
                    scan_queue.append(link)
        except ValueError:
            continue


# =====================================
# VALIDATE PLAYLIST
# =====================================

def validate(url):
    print("\n[CHECK]", url)

    item = {
        "url": url,
        "status": None,
        "content_type": "",
        "playlist_detected": False,
        "error": None
    }

    try:
        response = session.get(
            url,
            timeout=TIMEOUT,
            stream=True,
            allow_redirects=True,
            headers={"Range": "bytes=0-65535"}
        )

        item["status"] = response.status_code
        item["content_type"] = response.headers.get(
            "Content-Type", ""
        )

        first = next(response.iter_content(4096), b"")
        response.close()

        content_type = item["content_type"].lower()

        is_m3u = (
            b"#EXTM3U" in first
            or "mpegurl" in content_type
        )

        item["playlist_detected"] = is_m3u

        if is_m3u:
            print("[VALID PLAYLIST]", url)
        else:
            print("[NOT VERIFIED]", url)

    except requests.RequestException as e:
        item["error"] = str(e)
        print("[VALIDATION ERROR]", str(e)[:150])

    return item


# =====================================
# MAIN
# =====================================

scan_queue = [SITE]

def main():
    print("=" * 50)
    print("CRICFLIX M3U DETECTOR")
    print("=" * 50)

    while scan_queue and len(visited) < MAX_PAGES:

        page = scan_queue.pop(0)

        if page in visited:
            continue

        visited.add(page)

        scan_page(page)

    print("\n" + "=" * 50)
    print("SCANNING COMPLETED")
    print("Pages scanned:", len(visited))
    print("Candidates found:", len(found))
    print("=" * 50)

    # Validate all detected candidates
    for url in sorted(found):
        results.append(validate(url))
        time.sleep(0.2)

    valid = [
        x for x in results
        if x["playlist_detected"]
    ]

    # TXT
    Path("detected-m3u.txt").write_text(
        "\n".join(x["url"] for x in valid),
        encoding="utf-8"
    )

    # JSON
    Path("m3u_sources.json").write_text(
        json.dumps(
            results,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    # REPORT
    report = [
        "# CRICFLIX M3U DETECTION REPORT",
        "",
        f"Website: {SITE}",
        f"Pages scanned: {len(visited)}",
        f"Candidates: {len(found)}",
        f"Verified playlists: {len(valid)}",
        "",
        "## Verified Playlist URLs",
        ""
    ]

    if valid:
        for item in valid:
            report.append(f"- {item['url']}")
    else:
        report.append("No verified playlist found.")

    report.extend([
        "",
        "## All Candidates",
        ""
    ])

    for item in results:
        report.append(
            f"- {item['url']} | "
            f"HTTP: {item['status']} | "
            f"Playlist: {item['playlist_detected']}"
        )

    report.extend(["", "## Errors", ""])

    report.extend(
        f"- {error}" for error in errors
    )

    Path("report.md").write_text(
        "\n".join(report),
        encoding="utf-8"
    )

    print("\n" + "=" * 50)
    print("FINAL RESULT")
    print("Candidates:", len(found))
    print("Verified:", len(valid))
    print("Errors:", len(errors))
    print("Files generated:")
    print("1. detected-m3u.txt")
    print("2. m3u_sources.json")
    print("3. report.md")
    print("=" * 50)


if __name__ == "__main__":
    main()
