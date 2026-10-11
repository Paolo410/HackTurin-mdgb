---
name: audio-ducking-and-sync
description: Music edit, ducking and beat sync for the trailer — beat grid of the track, cuts snapped to beats, music lowered under the narrator, synthesized sound design, mastering to -14 LUFS. Use when the music, the cut points or the mix balance change.
---

# Audio ducking and sync

Tools: `tools/beats.py` (sync) and `tools/mix.py` (mix), plus the synth kit `tools/sfx.py`.

## Sync
- `python tools/beats.py` analyses the music (librosa) -> `build/beats.json` (tempo, beats, accents),
  places the beats on the video timeline through `music.segments` and snaps scene cuts in the
  `--from/--to` window to the nearest beat (max `--tol` s; the scene's last shot absorbs it)
  -> `build/timeline.synced.json`. Known tempo instead of analysis: `--bpm 120 --offset 0.0`.
- Music edit = `timeline.json` -> `music.segments`: `{src_in, src_out, at}`; the current one puts the
  track's drop (19.0 s) on the logo reveal at 0:30, its breakdown on the city scene at 1:42 and jumps to
  the closing hits for the title (60 ms crossfades).

## Mix
`python tools/mix.py` -> `build/audio/mix.wav` (+ stems `music_ducked.wav`, `voice_st.wav`, `sfx.wav`).
- Ducking: music down by `music.duck_db` (now -11 dB) wherever the narrator speaks: 120 ms look-ahead,
  60 ms attack, 450 ms release. Check: the voice should sit 7–15 dB above the ducked music.
- `music.gain_db`, `music.fade_out`, and `sfx` cues (`tick`, `drone`, `whoosh`, `boom`, `riser`, `blip`,
  `heartbeat`, `ping`; `"after": "L02"` pins a cue to the end of a line).
- Master: two-pass loudnorm to -14 LUFS integrated, -1 dBTP.

## Swapping the music
Add the file to `media.json` -> `audio`, set `music.media`, run `python tools/beats.py` and look at the
accents to re-place `segments` (drop on 30.0 s), then `python tools/build.py voice mix mux`.
Check the licence of every track (Pixabay Content License, YouTube Audio Library, etc.).
