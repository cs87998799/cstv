"""Build channels.json (Bangladesh + India live TV) from the iptv-org API."""
import json, urllib.request, datetime

API = "https://iptv-org.github.io/api"
COUNTRIES = {"BD", "IN"}
OUT = "channels.json"


def get(name):
    req = urllib.request.Request(f"{API}/{name}.json", headers={"User-Agent": "limon-iptv-pro"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


channels = [c for c in get("channels") if c.get("country") in COUNTRIES and not c.get("closed") and not c.get("is_nsfw")]
streams = get("streams")
logos = {}
for l in get("logos"):
    logos.setdefault(l["channel"], l["url"])

by_channel = {}
for s in streams:
    if s.get("channel") and s.get("url", "").endswith((".m3u8", ".m3u8?")) or ".m3u8" in s.get("url", ""):
        by_channel.setdefault(s["channel"], []).append(s["url"])

result = []
for c in channels:
    urls = by_channel.get(c["id"])
    if not urls:
        continue
    result.append({
        "id": c["id"],
        "name": c["name"],
        "country": c["country"],
        "categories": c.get("categories", []),
        "languages": c.get("languages", []),
        "logo": logos.get(c["id"], ""),
        "url": urls[0],
        "backups": urls[1:3],
    })

result.sort(key=lambda x: (x["country"], x["name"].lower()))

with open(OUT, "w", encoding="utf-8") as f:
    json.dump({
        "updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "count": len(result),
        "channels": result,
    }, f, ensure_ascii=False, indent=2)

print(f"Wrote {len(result)} channels to {OUT}")
