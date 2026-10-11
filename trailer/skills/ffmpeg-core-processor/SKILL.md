---
name: ffmpeg-core-processor
description: FFmpeg/ffprobe editing for the trailer — probe, conform clips to 1080p30, trim, freeze frames, mux picture and mix, final encode. Use for any cut/stitch/resize/overlay-audio task on the trailer media.
---

# FFmpeg core processor

Allowed binaries: `ffmpeg`, `ffprobe`. Helpers live in `tools/common.py` (`ffmpeg()`, `probe()`).

## Pipeline steps that use it
| step | command | what it does |
|---|---|---|
| conform | `python tools/prep_media.py` | every clip used by `timeline.json` -> `build/public/media/<id>.mp4`: 1920x1080 cover-crop, 30 fps CFR, H.264 CRF 16, GOP 1 s, no audio, trimmed to what the timeline uses; freeze-frame JPEGs for `"freeze"` shots |
| ingest | `python tools/prep_media.py --ingest file.mov c99_my_shot` | copy any clip (own footage, phone, drone) into `assets/b-roll/` as a clean MP4 |
| mux | `python tools/build.py mux` | Remotion picture + `build/audio/mix.wav` -> `output/<name>.mp4` (H.264 + AAC 320k, faststart) + `.en.srt` |

## Handy one-liners
- Probe: `ffprobe -v error -show_entries format=duration:stream=codec_name,width,height,r_frame_rate -of compact file.mp4`
- Frame grab for QC: `ffmpeg -ss 12.5 -i output/MDGB_trailer_PoC_v1.mp4 -frames:v 1 qc.jpg`
- Contact sheet: `ffmpeg -i in.mp4 -vf "fps=1/4,scale=480:-2,tile=5x6" -frames:v 1 sheet.jpg`
- Loudness check: `ffmpeg -i out.mp4 -af ebur128=peak=true -f null -`
- 9:16 social cut: `ffmpeg -i out.mp4 -vf "crop=ih*9/16:ih,scale=1080:1920" -c:a copy vertical.mp4`

## Rules
- Never edit files in `assets/` in place: conform into `build/`.
- Keep the master at 1920x1080 30 fps, H.264 high, yuv420p, -14 LUFS / -1 dBTP (projector-safe).
- To replace stock with the team's footage: change `file` in `media.json` (or `--ingest`), adjust `in` in
  `timeline.json`, then `python tools/build.py media detect data render mux`.
