---
name: video-scraper-and-downloader
description: Search and download free, royalty-free stock footage (Pexels, Pixabay, Wikimedia Commons) into trailer/assets/b-roll and register author, page and licence in media.json. Use when a trailer scene needs real b-roll or a placeholder clip must be replaced.
---

# Video scraper and downloader

Tool: `tools/fetch_broll.py` (run from `trailer/`). Keys go in `trailer/.env` (copy `.env.example`):
`PEXELS_API_KEY`, `PIXABAY_API_KEY`. Wikimedia Commons needs no key.

## Workflow
1. Read the scene in `timeline.json` (what the narration says, what must be on screen).
2. Search, landscape, 1080p or better:
   `python tools/fetch_broll.py search "pedestrian crossing night" --source all --n 8`
3. Pick clips that match the scene and the night-blue look; prefer static or slow camera moves
   (overlays and detections are pinned to the image), no readable faces in close-up, no logos.
4. Download with a scene-coded id: `python tools/fetch_broll.py get pexels:37247586 --as c01_crosswalk_aerial_a`
   -> `assets/b-roll/c01_crosswalk_aerial_a.mp4` + an entry in `media.json` (author, page, licence).
5. Point the shot at it in `timeline.json` (`"media": "c01_crosswalk_aerial_a", "in": 0.0, "dur": 6`).
6. Batch: `python tools/fetch_broll.py plan shots.json`. Full-length re-download of every clip: `refetch`.

## Rules
- Licences: Pexels and Pixabay licences allow free use; Commons files vary (CC0 / CC BY / CC BY-SA):
  keep the licence string from media.json and credit CC BY authors in the end credits.
- Never use footage taken from social networks; never present stock footage as the team's own test.
- Assets are git-ignored (videos > 5 MB never go in the repo): media.json is what gets committed.
- If the APIs are unreachable (sandbox egress), use a browser to open the search page, read the
  clip id and the direct file URL, and save the file under `assets/b-roll/<id>.mp4`; then run
  `python tools/prep_media.py --ingest <file> <id>` and add the entry to media.json by hand.
