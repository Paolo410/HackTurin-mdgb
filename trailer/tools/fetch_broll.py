#!/usr/bin/env python3
"""video-scraper-and-downloader: search and download royalty-free b-roll into assets/b-roll/.

Sources
  pexels     needs PEXELS_API_KEY   (free: https://www.pexels.com/api/)
  pixabay    needs PIXABAY_API_KEY  (free: https://pixabay.com/api/docs/)
  wikimedia  no key (Wikimedia Commons; licence varies per file: CC0 / CC BY / CC BY-SA — check it)

Every download is registered in media.json (author, page, licence), so the credits stay correct.

Usage
  python tools/fetch_broll.py search "zebra crossing night" --source pexels --n 8
  python tools/fetch_broll.py get pexels:37247586 --as c01_crosswalk_aerial_a
  python tools/fetch_broll.py get pixabay:12345 --as c99_my_clip
  python tools/fetch_broll.py get wikimedia:"File:Pedestrian crossing.webm" --as c98_commons
  python tools/fetch_broll.py plan shots.json        # [{"as": "c40_tram", "query": "tram night", "source": "pexels", "pick": 0}]
  python tools/fetch_broll.py refetch                # re-download full-length originals of every clip in media.json
Keys can live in trailer/.env (see .env.example).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, load_json, save_json  # noqa: E402

BROLL = ROOT / "assets" / "b-roll"
UA = {"User-Agent": "MDGB-trailer/1.0 (HackTurin 2026; contact via GitHub Paolo410/HackTurin-mdgb)"}


def env(name: str) -> str:
    v = os.environ.get(name)
    if not v and (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text().splitlines():
            if line.strip().startswith(name + "="):
                v = line.split("=", 1)[1].strip().strip('"')
    if not v:
        sys.exit(f"{name} is not set (put it in trailer/.env)")
    return v


# ----------------------------------------------------------------------------- sources
def pexels_search(q: str, n: int, min_h: int, orientation: str) -> list[dict]:
    r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": env("PEXELS_API_KEY"), **UA},
                     params={"query": q, "per_page": max(n, 5), "orientation": orientation}, timeout=30)
    r.raise_for_status()
    return [pexels_item(v, min_h) for v in r.json().get("videos", [])][:n]


def pexels_item(v: dict, min_h: int = 1080) -> dict:
    files = sorted((f for f in v["video_files"] if f.get("file_type") == "video/mp4" and f.get("height")),
                   key=lambda f: (abs(min(f["height"], f["width"]) - min_h), f.get("fps") or 99))
    best = files[0] if files else None
    return {"source": "pexels", "id": v["id"], "title": v.get("url", "").rstrip("/").split("/")[-1],
            "author": v["user"]["name"], "page": v["url"], "duration": v["duration"],
            "w": best and best["width"], "h": best and best["height"], "fps": best and best.get("fps"),
            "url": best and best["link"], "license": "Pexels License (free to use, attribution appreciated)"}


def pexels_get(vid: str) -> dict:
    r = requests.get(f"https://api.pexels.com/videos/videos/{vid}", headers={"Authorization": env("PEXELS_API_KEY"), **UA}, timeout=30)
    r.raise_for_status()
    return pexels_item(r.json())


def pixabay_search(q: str, n: int, min_h: int, orientation: str) -> list[dict]:
    r = requests.get("https://pixabay.com/api/videos/", headers=UA,
                     params={"key": env("PIXABAY_API_KEY"), "q": q, "per_page": max(n, 3), "video_type": "film"}, timeout=30)
    r.raise_for_status()
    return [pixabay_item(h, min_h) for h in r.json().get("hits", [])][:n]


def pixabay_item(h: dict, min_h: int = 1080) -> dict:
    sizes = [s for s in h["videos"].values() if s.get("url")]
    best = sorted(sizes, key=lambda s: abs(min(s["height"], s["width"]) - min_h))[0]
    return {"source": "pixabay", "id": h["id"], "title": h.get("tags", ""), "author": h.get("user", ""),
            "page": h["pageURL"], "duration": h["duration"], "w": best["width"], "h": best["height"], "fps": None,
            "url": best["url"], "license": "Pixabay Content License"}


def pixabay_get(vid: str) -> dict:
    r = requests.get("https://pixabay.com/api/videos/", headers=UA, params={"key": env("PIXABAY_API_KEY"), "id": vid}, timeout=30)
    r.raise_for_status()
    return pixabay_item(r.json()["hits"][0])


def wikimedia_search(q: str, n: int, min_h: int, orientation: str) -> list[dict]:
    r = requests.get("https://commons.wikimedia.org/w/api.php", headers=UA, timeout=30, params={
        "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": max(n, 5),
        "gsrsearch": f"filetype:video {q}", "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata"})
    r.raise_for_status()
    out = []
    for p in (r.json().get("query", {}).get("pages", {}) or {}).values():
        ii = (p.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata", {})
        out.append({"source": "wikimedia", "id": p["title"], "title": p["title"],
                    "author": (meta.get("Artist", {}).get("value", "") or "").split(">")[-2].split("<")[0] if "<" in meta.get("Artist", {}).get("value", "") else meta.get("Artist", {}).get("value", ""),
                    "page": ii.get("descriptionurl"), "duration": ii.get("duration"), "w": ii.get("width"), "h": ii.get("height"),
                    "fps": None, "url": ii.get("url"), "license": meta.get("LicenseShortName", {}).get("value", "see page")})
    return out[:n]


def wikimedia_get(title: str) -> dict:
    hits = wikimedia_search(title.replace("File:", ""), 5, 1080, "landscape")
    for h in hits:
        if h["id"] == title:
            return h
    sys.exit(f"not found on Commons: {title}")


SEARCH = {"pexels": pexels_search, "pixabay": pixabay_search, "wikimedia": wikimedia_search}
GET = {"pexels": pexels_get, "pixabay": pixabay_get, "wikimedia": wikimedia_get}


# ----------------------------------------------------------------------------- download + register
def download(item: dict, as_id: str) -> Path:
    BROLL.mkdir(parents=True, exist_ok=True)
    ext = Path(item["url"].split("?")[0]).suffix or ".mp4"
    dst = BROLL / f"{as_id}{ext}"
    with requests.get(item["url"], headers=UA, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dst, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    md_path = ROOT / "media.json"
    md = load_json(md_path) if md_path.exists() else {"clips": {}, "audio": {}}
    md["clips"][as_id] = {"file": str(dst.relative_to(ROOT)), "source": item["source"], "source_id": item["id"],
                          "author": item["author"], "title": item["title"], "page": item["page"], "download": item["url"],
                          "license": item["license"], "original_duration": item["duration"]}
    save_json(md, md_path)
    print(f"✓ {as_id}  {dst.stat().st_size / 1e6:.1f} MB  ← {item['source']}:{item['id']} by {item['author']}")
    return dst


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--source", default="pexels", choices=[*SEARCH, "all"])
    s.add_argument("--n", type=int, default=8); s.add_argument("--min-height", type=int, default=1080)
    s.add_argument("--orientation", default="landscape")
    g = sub.add_parser("get"); g.add_argument("ref", help="pexels:<id> | pixabay:<id> | wikimedia:<File:title>"); g.add_argument("--as", dest="as_id", required=True)
    p = sub.add_parser("plan"); p.add_argument("file")
    sub.add_parser("refetch")
    a = ap.parse_args()

    if a.cmd == "search":
        sources = list(SEARCH) if a.source == "all" else [a.source]
        for src in sources:
            for i, it in enumerate(SEARCH[src](a.query, a.n, a.min_height, a.orientation)):
                print(f"{src}:{it['id']}  #{i}  {it['duration']}s  {it['w']}x{it['h']}  {it['author']}  {it['page']}")
    elif a.cmd == "get":
        src, _, ref = a.ref.partition(":")
        download(GET[src](ref), a.as_id)
    elif a.cmd == "plan":
        for row in json.loads(Path(a.file).read_text()):
            hits = SEARCH[row.get("source", "pexels")](row["query"], max(row.get("pick", 0) + 1, 5), row.get("min_height", 1080), "landscape")
            download(hits[row.get("pick", 0)], row["as"])
    elif a.cmd == "refetch":
        md = load_json(ROOT / "media.json")
        for cid, c in md["clips"].items():
            if c.get("source") in GET:
                download(GET[c["source"]](str(c["source_id"])), cid)


if __name__ == "__main__":
    main()
