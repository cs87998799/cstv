import urllib.request

URL = "https://iptv-org.github.io/iptv/countries/bd.m3u"

data = urllib.request.urlopen(URL, timeout=30).read().decode("utf-8")

with open("playlist.m3u", "w", encoding="utf-8") as f:
    f.write(data)
