---
name: tts-audio-synthesizer
description: Turn the narration lines of timeline.json (English adaptation of docs/Transcription.txt and the animatic voice-over) into a cinematic, deep English narrator track with Kokoro (offline), Edge-TTS, ElevenLabs or OpenAI, placed on the timeline with subtitles. Use when the narration text, voice or timing changes.
---

# TTS audio synthesizer

Tool: `tools/tts.py`. Text lives in `timeline.json` -> `scenes[].vo` (`text`, optional `at`, `speed`).

## Engines
| engine | needs | default voice |
|---|---|---|
| `kokoro` (default) | nothing online after setup (model in `trailer/models/`, downloaded by `setup.sh`) | blend `am_michael:0.65,am_onyx:0.35`, speed 0.9 |
| `edge` | internet | `en-US-ChristopherNeural` (try `en-US-GuyNeural`, `en-GB-RyanNeural`) |
| `elevenlabs` | `ELEVENLABS_API_KEY`, voice id | model `eleven_multilingual_v2` |
| `openai` | `OPENAI_API_KEY` | `gpt-4o-mini-tts`, voice `onyx`, narrator instructions built in |

## Workflow
1. Source text: `docs/Transcription.txt` is the GOMA brief read by the organisers (Italian). The narration
   is the English, cinematic adaptation in `timeline.json` (short sentences, numbers rounded in voice,
   exact on screen). Keep each line shorter than its scene (~2.3 words/s at speed 0.9).
2. `python tools/tts.py` (or `--engine edge --voice en-US-ChristopherNeural`). Only changed lines are re-synthesised.
3. Output: `build/audio/vo/<line>.wav`, `build/audio/voice.wav` (placed), `build/vo_timeline.json`, `build/subtitles_en.srt`.
   The log flags lines that spill into the next scene: shorten the text or set `"speed"` / `"at"`.
4. Chain applied to every line: trim, 48 kHz, +0.5 semitone of depth (`--deepen`), EQ (warmth 115 Hz, presence 3.3 kHz), de-esser, compressor, small dark room.

## Rules
- A synthetic voice must be declared in the credits ("synthetic voice"). A team member's recording can
  replace any line: drop `build/audio/vo/L05.wav` in with the same name (48 kHz mono) and re-run `mix`.
