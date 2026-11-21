import json
import re
import time
import ipaddress
from urllib.parse import urljoin, urlparse

import requests
from playwright.sync_api import sync_playwright

SITE = "https://nexflixtv.lovable.app/"
JSON_FILE = "Khusbu.json"
M3U_FILE = "Khusbu.m3u"
MAX_CHANNEL_PAGES = 900
PAGE_WAIT_MS = 2500

found = {}          # stream URL -> channel/page label
channel_pages = []
resource_urls = set()
errors = []

URL_RE = re.compile(r"""https?://[^\s"'<>\\]+""", re.I)
REL_RE = re.compile(
    r"""["']([^"']+\.(?:m3u8?|m3u)(?:\?[^"']*)?)["']""", re.I
)
STREAM_RE = re.compile(
    r"""https?://[^\s"'<>\\]+?\.(?:m3u8?|m3u)(?:\?[^\s"'<>\\]*)?""",
    re.I
)


def clean_url(value):
    return value.rstrip("),];}")


def inspect_text(text, base_url, label):
    if not text:
        return
    for raw in URL_RE.findall(text):
        url = clean_url(raw)
        path = urlparse(url).path.lower()
        if path.endswith((".m3u", ".m3u8")):
            found.setdefault(url, label)

    for raw in REL_RE.findall(text):
        found.setdefault(urljoin(base_url, raw), label)


def is_public_http_url(url):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        try:
            ip = ipaddress.ip_address(parsed.hostname)
            return not (
                ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast
            )
        except ValueError:
            return True
    except Exception:
        return False


def main():
    print("Khusbu detector: scanning homepage and channel watch pages")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
        )
        page = context.new_page()
        current_label = {"value": "Homepage"}

        def on_request(request):
            resource_urls.add(request.url)
            low = request.url.lower()
            if ".m3u8" in low or ".m3u" in low:
                found.setdefault(request.url, current_label["value"])

        def on_response(response):
            try:
                url = response.url
                ctype = response.headers.get("content-type", "").lower()
                if ".m3u8" in url.lower() or ".m3u" in url.lower():
                    found.setdefault(url, current_label["value"])
                if any(x in ctype for x in (
                    "javascript", "json", "text", "mpegurl"
                )):
                    if response.request.resource_type in (
                        "document", "script", "xhr", "fetch", "media"
                    ):
                        body = response.text()
                        if len(body) <= 5_000_000:
                            inspect_text(body, url, current_label["value"])
            except Exception:
                pass

        page.on("request", on_request)
        page.on("response", on_response)

        try:
            page.goto(SITE, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(8000)
            inspect_text(page.content(), SITE, "Homepage")

            # Extract all visible channel watch links from the SPA homepage.
            links = page.locator('a[href*="/watch/"]').evaluate_all(
                "(els) => els.map(a => ({href:a.href, name:(a.innerText||a.getAttribute('aria-label')||'Channel').trim()}))"
            )
            seen = set()
            for item in links:
                href = item.get("href", "")
                if "/watch/" in href and href not in seen:
                    seen.add(href)
                    channel_pages.append({
                        "url": href,
                        "name": item.get("name") or "Channel"
                    })

            # Also inspect hrefs found in rendered source, including SPA route strings.
            for href in re.findall(r"""["'](/watch/[^"' ]+)["']""", page.content()):
                full = urljoin(SITE, href)
                if full not in seen:
                    seen.add(full)
                    channel_pages.append({"url": full, "name": "Channel"})

            channel_pages[:] = channel_pages[:MAX_CHANNEL_PAGES]
            print("Watch pages found:", len(channel_pages))

            for index, item in enumerate(channel_pages, 1):
                current_label["value"] = item["name"] or f"Channel {index}"
                try:
                    page.goto(item["url"], wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(PAGE_WAIT_MS)
                    inspect_text(page.content(), item["url"], current_label["value"])

                    # Some players expose source URLs in video/source elements.
                    media = page.locator("video, source").evaluate_all(
                        """els => els.map(e => ({
                            src: e.currentSrc || e.src || e.getAttribute('src') || ''
                        }))"""
                    )
                    for entry in media:
                        src = entry.get("src", "")
                        if src.startswith("http"):
                            low = src.lower()
                            if ".m3u8" in low or ".m3u" in low:
                                found.setdefault(src, current_label["value"])
                    if index % 25 == 0:
                        print(f"Scanned {index}/{len(channel_pages)} watch pages; candidates={len(found)}")
                except Exception as exc:
                    errors.append(f"{item['url']}: {str(exc)[:180]}")

        except Exception as exc:
            errors.append(f"Homepage: {str(exc)[:250]}")
        finally:
            browser.close()

    # Test only publicly exposed candidate URLs. HTTP status alone does not
    # prove playback; record content type and final URL for manual review.
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 KhusbuDetector/2.0"})
    results = []

    for url, channel in sorted(found.items()):
        row = {
            "channel": channel,
            "url": url,
            "http_status": "NOT_TESTED",
            "content_type": ""
        }
        if is_public_http_url(url):
            try:
                response = session.get(
                    url,
                    headers={"Range": "bytes=0-2047"},
                    timeout=15,
                    stream=True,
                    allow_redirects=True
                )
                row["http_status"] = response.status_code
                row["content_type"] = response.headers.get("Content-Type", "")
                row["final_url"] = response.url
                response.close()
            except requests.RequestException as exc:
                row["http_status"] = "ERROR"
                row["error"] = str(exc)[:200]
        else:
            row["http_status"] = "SKIPPED_INVALID_OR_PRIVATE_HOST"
        results.append(row)

    report = {
        "website": SITE,
        "watch_pages_found": len(channel_pages),
        "watch_pages_scanned": len(channel_pages),
        "network_resources_seen": len(resource_urls),
        "total_playlist_candidates": len(results),
        "results": results,
        "errors": errors,
        "note": "Only URLs publicly exposed to the browser were inspected. No login, DRM, paywall, or access-control bypass is attempted."
    }

    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Keep only publicly reachable responses that look like HLS/M3U.
    with open(M3U_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        added = 0
        for row in results:
            status = row["http_status"]
            ctype = row["content_type"].lower()
            url = row["url"]
            looks_playlist = (
                ".m3u8" in url.lower() or ".m3u" in url.lower()
                or "mpegurl" in ctype
            )
            if status in (200, 206) and looks_playlist:
                name = (row["channel"] or "Detected channel").replace("\n", " ")
                f.write(f'#EXTINF:-1,{name}\n{url}\n')
                added += 1

    print("Finished.")
    print("Watch pages scanned:", len(channel_pages))
    print("Playlist candidates:", len(results))
    print("M3U entries written:", added)
    print("See Khusbu.json for diagnostics.")


if __name__ == "__main__":
    main()
