import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from curl_cffi import requests

API_URL = "https://steamrip.com/wp-json/wp/v2/posts"
OUTPUT = "steamrip_data.json"
PER_PAGE = 100
# Real-Debrid only supports 1fichier among SteamRIP's hosts, so it goes first.
HOST_PRIORITY = ("1fichier.com",)

def fetch_page(session, page):
    for attempt in range(4):
        response = session.get(API_URL, params={
            "per_page": PER_PAGE,
            "page": page,
            "_fields": "title,content,modified_gmt",
        }, timeout=60)
        if response.status_code == 200:
            return response.json(), int(response.headers.get("x-wp-totalpages", page))
        print(f"page {page}: HTTP {response.status_code}, retrying", file=sys.stderr)
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"page {page} failed: HTTP {response.status_code}")

def normalize_url(href):
    return "https:" + href if href.startswith("//") else href

def parse_version(info_text, title):
    match = re.search(r"\nVersion\s*\n?:\s*([^\n]+)", info_text)
    if match:
        version = match.group(1).lstrip(": ").split("|")[0].strip()
        if re.search(r"\d", version) and len(version) < 60:
            return version
    match = re.search(r"\((v?[\d][^)]*|Build [^)]*)\)\s*$", title)
    return match.group(1) if match else "Unknown"

def parse_post(post):
    title = html.unescape(BeautifulSoup(post["title"]["rendered"], "html.parser").get_text()).strip()
    soup = BeautifulSoup(post["content"]["rendered"], "html.parser")

    uris = list(dict.fromkeys(
        normalize_url(a["href"]) for a in soup.select("a.shortc-button[href]")
        if a["href"].startswith(("http", "//"))
    ))
    if not uris:
        return None
    uris.sort(key=lambda u: 0 if any(h in u for h in HOST_PRIORITY) else 1)

    info_text = soup.get_text("\n", strip=True)
    size_match = re.search(r"Game Size:?\s*\n?\s*([\d.,]+\s*[KMGT]B)", info_text, re.I)

    return {
        "title": title,
        "size": size_match.group(1).replace(",", ".") if size_match else "Unknown",
        "uploadDate": post["modified_gmt"] + "+00:00",
        "url": uris[0],
        "uris": uris,
        "version": parse_version(info_text, title),
        "provider": "SteamRIP",
    }

def main():
    session = requests.Session(impersonate="chrome")
    games, page, total_pages = [], 1, 1
    while page <= total_pages:
        posts, total_pages = fetch_page(session, page)
        games.extend(g for g in map(parse_post, posts) if g)
        print(f"page {page}/{total_pages}: {len(games)} games", file=sys.stderr)
        page += 1
        time.sleep(2)

    if len(games) < 1000:
        raise RuntimeError(f"only {len(games)} games parsed, refusing to overwrite {OUTPUT}")

    try:
        with open(OUTPUT, encoding="utf-8") as f:
            if json.load(f).get("games") == games:
                print("no game changes, leaving file untouched", file=sys.stderr)
                return
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    data = {
        "name": "SteamRIP Index",
        "last_updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "games": games,
    }
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"wrote {len(games)} games to {OUTPUT}", file=sys.stderr)

if __name__ == "__main__":
    main()
