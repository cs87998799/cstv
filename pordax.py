import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright

TARGET = "https://pordax.pages.dev/livetv"
STREAM_RE = re.compile(r"\.(m3u8?|ts)(?:[?#].*)?$", re.I)
URL_RE = re.compile(r'https?://[^\s"\'<>\\]+', re.I)

streams = {}
page_url = TARGET


def clean_url(value):
    return value.strip().rstrip("),;]}")


def absolute(value):
    if not value:
        return ""
    return urljoin(page_url, value.strip())


def add_stream(url, name="", logo="", group="", source=""):
    url = clean_url(url)
    if not url.startswith(("http://", "https://")) or not STREAM_RE.search(url):
        return
    key = url
    old = streams.get(key, {})
    streams[key] = {
        "name": name.strip() or old.get("name") or f"Channel {len(streams)+1}",
        "logo": logo.strip() or old.get("logo", ""),
        "url": url,
        "format": urlparse(url).path.rsplit(".", 1)[-1].lower(),
        "group": group.strip() or old.get("group", "PordaX"),
        "source": source or old.get("source", "")
    }


def scan_text(text, source="response"):
    if not isinstance(text, str):
        return
    # Look for direct stream URLs in JSON, scripts, and text responses.
    for match in URL_RE.findall(text):
        candidate = clean_url(match)
        if STREAM_RE.search(candidate):
            add_stream(candidate, source=source)


async def main():
    global page_url
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox"]
        )
        context = await browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1440, "height": 1000}
        )
        page = await context.new_page()
        page.set_default_timeout(12000)

        async def handle_response(response):
            try:
                url = response.url
                ctype = (response.headers.get("content-type") or "").lower()
                if STREAM_RE.search(url):
                    add_stream(url, source="network")
                if any(x in ctype for x in ("json", "text", "javascript", "mpegurl")):
                    body = await response.text()
                    scan_text(body, source=url)
                    # Try extracting common channel object fields from JSON.
                    try:
                        data = json.loads(body)
                        walk_json(data, url)
                    except Exception:
                        pass
            except Exception:
                pass

        page.on("response", lambda response: asyncio.create_task(handle_response(response)))

        print("Opening:", TARGET)
        try:
            await page.goto(TARGET, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(12000)

            # Trigger lazy-loaded lists.
            for _ in range(7):
                await page.mouse.wheel(0, 1100)
                await page.wait_for_timeout(1200)

            # Read rendered channel cards and media/source attributes.
            cards = await page.locator(
                "a, article, li, [class*='channel'], [class*='Channel'], "
                "[class*='card'], [class*='Card'], [data-testid]"
            ).evaluate_all("""els => els.map(el => {
                const img = el.querySelector('img');
                const video = el.querySelector('video');
                const source = el.querySelector('source');
                const text = (el.innerText || el.getAttribute('aria-label') || '').trim();
                const urls = [];
                if (video && video.src) urls.push(video.src);
                if (source && source.src) urls.push(source.src);
                for (const a of el.querySelectorAll('a[href]')) urls.push(a.href);
                for (const v of el.querySelectorAll('[src], [href], [data-src], [data-url]')) {
                    for (const k of ['src','href','data-src','data-url']) {
                        const x = v.getAttribute(k);
                        if (x) urls.push(x);
                    }
                }
                return {
                    text: text.slice(0,180),
                    logo: img ? (img.currentSrc || img.src || img.getAttribute('data-src') || '') : '',
                    urls
                };
            })""")

            for card in cards:
                name = (card.get("text") or "").splitlines()[0].strip()
                logo = absolute(card.get("logo", ""))
                for raw in card.get("urls", []):
                    u = absolute(raw)
                    if STREAM_RE.search(u):
                        add_stream(u, name=name, logo=logo, source="rendered card")

            # Inspect page HTML and scripts for embedded stream URLs.
            html = await page.content()
            scan_text(html, "page HTML")
            await page.wait_for_timeout(5000)

        except Exception as exc:
            print("Page/browser error:", repr(exc))

        await browser.close()

    results = list(streams.values())
    # Give stable IDs and ensure names/logos are preserved where found.
    for index, item in enumerate(results, 1):
        if item["name"].startswith("Channel ") and item["logo"]:
            item["name"] = f"Channel {index}"

    report = {
        "website": TARGET,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "total_streams": len(results),
        "streams": results
    }
    Path("pordax.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    lines = ["#EXTM3U"]
    for item in results:
        name = item["name"].replace('"', "'")
        logo = item["logo"].replace('"', "'")
        group = item["group"].replace('"', "'")
        tvg_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        lines.append(
            f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{name}" '
            f'tvg-logo="{logo}" group-title="{group}",{name}'
        )
        lines.append(item["url"])

    Path("pordax.m3u").write_text("\n".join(lines) + "\n", encoding="utf-8")

    report_lines = [
        "PORDAX LIVE TV DETECTION REPORT",
        f"Checked: {report['checked_at']}",
        f"Total stream URLs: {len(results)}",
        "",
        "CHANNELS:"
    ]
    if results:
        for item in results:
            report_lines.append(
                f"{item['name']} | {item['format'].upper()} | "
                f"Logo: {item['logo'] or 'NOT FOUND'} | {item['url']}"
            )
    else:
        report_lines.append("No direct .m3u, .m3u8, or .ts URLs detected.")
        report_lines.append(
            "The site may load streams only after user interaction, "
            "or may use protected/unsupported playback."
        )
    Path("pordax_report.txt").write_text(
        "\n".join(report_lines) + "\n", encoding="utf-8"
    )

    print("\n========== PORDAX REPORT ==========")
    print("Total streams:", len(results))
    for item in results:
        print(item["name"], "|", item["format"], "|", item["url"])
    if not results:
        print("No direct stream URLs detected.")


def walk_json(data, source, inherited_name="", inherited_logo=""):
    """Extract common channel fields from nested JSON structures."""
    if isinstance(data, dict):
        name = (
            data.get("name") or data.get("title") or data.get("channel_name")
            or data.get("channelName") or data.get("label") or inherited_name
        )
        logo = (
            data.get("logo") or data.get("image") or data.get("thumbnail")
            or data.get("poster") or data.get("icon") or inherited_logo
        )
        for key, value in data.items():
            if isinstance(value, str):
                candidate = absolute(value)
                if STREAM_RE.search(candidate):
                    add_stream(
                        candidate, name=str(name or ""),
                        logo=absolute(str(logo or "")), source=source
                    )
            elif isinstance(value, (dict, list)):
                walk_json(value, source, str(name or ""), absolute(str(logo or "")))
    elif isinstance(data, list):
        for item in data:
            walk_json(item, source, inherited_name, inherited_logo)


if __name__ == "__main__":
    asyncio.run(main())
