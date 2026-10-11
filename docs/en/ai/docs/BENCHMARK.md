# How well the vision counts — benchmark of 11/10/2026

> English translation of [`ai/docs/BENCHMARK.md`](../../../../ai/docs/BENCHMARK.md) (11 October 2026, PR #22). The Italian original is the reference: if the two differ, the original wins.

Numbers of the UNO Q with the settings from the morning of 11/10 (`profiles.unoq` in `ai/config.yaml`), on real videos
shot from still cameras, compared with a reference checked by eye. To redo them: section "How to redo it".

## In short, for everybody

On 8 videos with a still camera (Turin by day and by night, a pedestrian area, a square, a road):

| | Real crossings | Counted by the board | In the right direction | Extra counts |
|---|---:|---:|---:|---:|
| **Pedestrians** | 23 | **13 (57%)** | 13 of 13 (100%) | 0 |
| **Cyclists** | 4 | **2 (50%)** | 2 of 2 (100%) | 0 |
| **Vehicles** | 77 | **47 (61%)** | 47 of 47 (100%) | 0 |

- **When the board counts a crossing, it is real and has the right direction**: 0 false or double counts and the
  right direction in 100% of cases, by day and by night.
- **Where the camera sees the line well** (Turin at night, pedestrian area, square, road): **17 crossings out of 17**.
- **Where the board misses some**: in the Turin videos shot from a balcony, where a street-light pole hides exactly
  the point where people cross and the people on the far crossing are 15 pixels tall. There it counts 45 crossings
  out of 87. With the camera mounted on the traffic light, above the crossing, neither happens.
- **Before today's fixes** the same videos gave: pedestrians 9 of 23 (39%), cyclists 0 of 4, vehicles 24 of 77
  (31%). **People counted: from 9 to 15 of 27; vehicles: from 24 to 47 of 77.**
- The board analyses **5.9 frames per second**, all with the detector (before 8.4, but only 4.2 analysed: the others
  repeated the previous positions). All local, no frame saved.

## How the comparison is made

1. **Reference**: the same program with a much larger detector (YOLOX-l at 960 px, about 500 times the computation of
   the board's one) on every frame at 15 FPS, on the Mac. A crossing counts only if the object stays 0.5 s past the
   line, as on the board (`benchmark.py run riferimento`, `reference`).
2. **Board**: the board's program on the Mac with the board's limits (`--emulate-unoq`: 320 px, 4 threads) and the
   **FPS measured on the real board** on 11/10: 8.4 FPS with the detector one frame out of two, 5.9 with the detector
   on every frame, 3.8 at 416 px.
3. **Pairing**: a crossing counted by the board and one of the reference are the same if they are on the same line,
   of the same kind, within 2 s and 120 px of the point where the object goes over the line
   (`smartcrossing/scoring.py`, tested in `tests/test_scoring.py`). A pedestrian and a cyclist can be paired: two
   models often disagree on who is riding.
4. **Review by eye**: for every disagreement a sheet with the object 1 s before, on the line and 1 s after
   (`benchmark.py review`). Where the board was right the reference is corrected and annotated (`benchmark.py judge`,
   field `review` of `benchmarks/reference/<video>.json`). All the disagreements on pedestrians and a sample of those
   on vehicles were checked: 2 real crossings had escaped the reference (added), no crossing of the reference was
   false.
5. **Still cameras only**: 5 of the 13 test videos (NYC ×2, Shibuya, Mixkit 4194 and 4335) are time-lapses or
   hand-held: the mean difference between a frame and the next is 15–18 out of 255, against 1–4 for still cameras. A
   line drawn on the image does not stay on the road there, so they do not count for the counting (`"fixed": false`
   in `benchmarks/videos.json`; with `score --moving` they are shown anyway: pedestrians from 9 to 22 of 48, vehicles
   from 24 to 48 of 87).

## What changed and how much it gave

Each row adds one change to the previous one (still cameras; pedestrians / vehicles counted):

| Change | Pedestrians | Vehicles |
|---|---:|---:|
| Before (8.4 FPS, detector one frame out of two, supervision's tracking) | 9 / 23 | 24 / 77 |
| Tracks returned with the right box + boxes enlarged by 30% + side of the line remembered | 10 / 23 | 32 / 77 |
| Detector on every frame (5.9 FPS, all analysed) | 13 / 23 | 44 / 77 |
| Boxes enlarged by 50% instead of 30% — **adopted configuration** | **13 / 23** | **47 / 77** |

The three tracking fixes (`smartcrossing/tracking.py`, `counting.py`):

- **Tracks lost at ByteTrack's output.** supervision returned a track only if its filtered (Kalman) position covered
  the detector's box by more than 50%. At 4–6 detections per second the filtered position of a car lags behind: the
  car was tracked but not returned, hence never counted (that is the "0 vehicles in the far direction" of point 42 of
  `DECISIONS.md`). Now every track comes out with the box it was matched with.
- **Enlarged boxes for the matching** (buffered IoU, from the C-BIoU tracker, Yang et al., WACV 2023): between two
  detections a car moves almost its length and two consecutive boxes no longer overlap. The tracker compares them
  enlarged by 50% per side and returns the real ones. Cost: a few multiplications per box.
- **Side of the line remembered.** `sv.LineZone` forgot which side an object was on after 4 detections without
  seeing it (a car behind a pole): now it remembers it for 30 detections, as long as ByteTrack keeps a lost track.

The benchmark itself was fixed: it compares the point and the moment the object goes over the line, not those of the
confirmation (which comes 3 detections later, at 4 per second 0.7 s and 150 px further: before, cars that were counted
looked missed); the reference confirms after 0.5 s like the board (at 30 FPS with 3 frames = 0.1 s it counted twice
whoever walks on the line); the videos are analysed at the exact FPS of the board (8.4 FPS of a 30 FPS video were 7.5).

## Tried and not adopted

| Technique | Result | Why not |
|---|---|---|
| Detector at 416 px (on every frame) | pedestrians 13/23, vehicles 40/77 | the board drops to 3.8 FPS: it sees small ones better but loses fast objects |
| New tracks from score 0.30 instead of 0.40 | pedestrians the same, vehicles 46/77 (−1) | 1 extra count; together with stitching 49/77 but more double counts in crowded videos |
| Confirmation after 2 detections instead of 3 | the same | no gain, more risk of double counts |
| Stitching tracks across the line (`counting.stitch_s`) | vehicles +1 | +1 extra count; in crowds it links different people. It stays in the code, switched off |
| 8-bit model (INT8) | same objects as the normal model | slower on the board (283 ms against 208–230): the Cortex-A53 has no int8 instructions (point 45) |
| PP-PicoDet-S (more recent detector) | +36% people found | 2.2 times slower on the board (point 46) |
| Gamma correction at night | — | not needed: the night video has the same mean brightness as the day ones (125 of 255) |

## Limits and next steps

- **Few crossings**: 27 people and 77 vehicles. The numbers give the order of magnitude, not the second digit.
  Torino_4 (220 s, many people on the crossing) and Torino_7 have framings different from Torino_3 and Torino_1:
  with one calibration each the sample doubles.
- **Small people**: under 20 px of height YOLOX-nano at 320 px misses them. Real remedy: camera closer to the crossing
  (on the traffic light), or restricting the analysed area (`roi` of the calibration) to the crossing and the waiting
  zone.
- **Real camera**: redo the benchmark with 2–3 minutes shot by the board's camera once it is mounted.
- The variants and all the numbers per video: `benchmarks/variants.json`, `benchmarks/results/<variant>.json`.

## How to redo it

```bash
cd ai
python scripts/benchmark.py run riferimento        # on the Mac, ~40 min (CoreML); then:
python scripts/benchmark.py reference              # reference crossings in benchmarks/reference/
python scripts/benchmark.py run scheda_nuova       # ~1 min per variant
python scripts/benchmark.py score scheda_prima scheda_nuova
python scripts/benchmark.py review scheda_nuova torino_1   # sheets of the disagreements in samples/report/review/
python scripts/benchmark.py judge scheda_nuova torino_1 --add g3 --note "..."   # after looking at them
```

One `judge` per video with all the decisions, then `review` again: after each `judge` the `r…`/`g…` numbers of the
sheets change. The videos are in `ai/samples/` (not in git). If macOS blocks reading them ("Operation not
permitted"), copy them from the board and give the folder with `MDGB_VIDEOS=<folder>`.
