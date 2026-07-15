# sqc Manual

## Directory structure

```
sqc/
├── bin/sqc                  # thin wrapper for running without install
├── sqc/
│   ├── cli.py                # argparse subcommands, dispatch
│   ├── config.py              # BatchConfig / VendorQCConfig / DonorTriageConfig
│   ├── intake.py               # file discovery
│   ├── batch.py                 # ProcessPoolExecutor orchestration, resume
│   ├── deps.py                   # external tool presence checks
│   ├── logs.py                    # stdlib logging setup
│   ├── policy.py                   # policy profile (TOML) loading
│   ├── util.py                      # small parsing helpers
│   ├── tools/                        # subprocess wrappers, one per external tool
│   ├── analysis/                      # crosscheck, frame timing, pattern registry
│   ├── modes/                          # vendor_qc.py, donor_triage.py orchestration
│   └── report/                          # schema, CSV, JSON writer
├── profiles/                # bundled policy profile TOML files
├── MediaConch/               # MediaConch policy XML files (referenced by profiles)
└── tests/
```

## CLI reference

### Shared flags (both modes)

| Flag | Default | Meaning |
|---|---|---|
| `input` | — | File or directory (scanned recursively) |
| `--extensions` | mode-dependent | Extensions to scan for |
| `--report-dir` | `./sqc_reports` | Per-file JSON report directory |
| `--csv` | `<report-dir>/summary.csv` | CSV summary path |
| `--log-file` | timestamped | Run log path |
| `--workers` | none (one per file) | Parallel worker processes — **never guess this from CPU count**; this workload is typically I/O-bound. Measure your machine's real ceiling with `iostat -x 1` / `iotop` while increasing concurrency, don't assume one from core count. |
| `--resume` / `--no-resume` | resume on | Skip files with an existing, non-`TOOL_FAILURE` JSON report |
| `--full` | off | Include frame-level packet timing analysis (needed for VFR classification; reads the container's packet index, no pixel decoding, but still adds time on very large files) |

> **`--extensions` ordering:** it takes one or more values, so it greedily
> consumes whatever follows it on the command line — `--extensions .mov
> input_dir` reads `input_dir` as a third extension instead of the input
> path. Put the positional `input` argument *before* `--extensions`:
> `sqc <mode> input_dir --extensions .mov .mp4`.

### `sqc vendor-qc`

```
sqc vendor-qc --profile NAME_OR_PATH [options] INPUT
```

| Flag | Default | Meaning |
|---|---|---|
| `--profile` | required | Bundled profile name (looked up in `--profiles-dir`) or a path to a standalone `.toml` file |
| `--profiles-dir` | `./profiles` | |
| `--mediaconch-dir` | `./MediaConch` | Used to resolve a profile's `mediaconch_policy` if given as a bare filename |
| `--strict-decode-check` | off | Also run the ffmpeg null-pass essence decode check. Off by default here — MediaConch + the crosscheck layer already carry most of the diagnostic weight, and a full decode of a large uncompressed master isn't free. |
| `--spin-down-zone` | from profile | Override the profile's VFR spin-down-zone threshold for this run |
| `--frame-anomaly-low-ratio` / `--frame-anomaly-high-ratio` | from profile | Override the profile's anomalous-frame-duration ratio thresholds |
| `--av-duration-threshold` | from profile | Override the profile's A/V duration-sync threshold (seconds) |

If `--extensions` isn't given, it's taken from the loaded profile's `container_extensions`.

### `sqc donor-triage`

```
sqc donor-triage [options] INPUT
```

| Flag | Default | Meaning |
|---|---|---|
| `--strict-decode-check` / `--no-strict-decode-check` | **on** | ffmpeg null-pass essence decode check. On by default here — it's this mode's main defense against essence-level corruption when there's no policy to check metadata against. |

Default `--extensions`: `.mov .mp4 .mkv .mxf .avi .wav .dv .m4v` (donor material is heterogeneous; vendor-qc's default comes from the profile instead).

## Check catalog

### Shared (both modes) — `analysis/crosscheck.py`

| Check | What it does |
|---|---|
| `probe_integrity` | Surfaces ffprobe structural warnings/errors, suppressing known-benign patterns (e.g. AJA's "Unsupported codec with id 0" metadata-track notice) to INFO |
| `extension_format_match` | File extension vs. MediaInfo/ffprobe's *detected* format — extension is never trusted for routing, only compared |
| `container_codec_validity` | Flags a video stream whose container-level codec tag didn't resolve to a known codec (Frankenstein-file proxy) |
| `stream_video_count` / `stream_audio_count` | Stream inventory; multiple video streams flagged as `MULTI_VIDEO_STREAM` |
| `av_duration_sync` | Audio/video stream duration delta vs. threshold |
| `frame_count_vs_duration` | Video stream's own `nb_frames` vs. `round(duration × fps)` — a non-zero delta is always WARN here; `--full`'s frame-timing classification is what determines if it's benign or a real problem |
| `moov_atom` | Cross-checks moov-atom presence against MediaTrace's binary anatomy, for QuickTime/MP4-family containers |
| `cross_tool_duration` | MediaInfo's reported duration vs. ffprobe's — a mismatch is a truncation/partial-write signal |

### `--full` frame timing — `analysis/frame_timing.py`

Extracts every video packet's duration via `ffprobe -show_packets` (reads the
container's packet-duration index, no pixel decode) and classifies into:

- `NONE` — all frames nominal
- `TIMEBASE_ROUNDING` — two duration values differing by a tiny amount, no
  large anomalies (benign QuickTime muxer artifact)
- `SPIN_DOWN` — anomalous frames confined to the tail (`spin_down_zone`
  fraction through the file or later) — VTR head spin-down
- `DROPPED_FRAMES` — anomalous frames distributed throughout — genuine
  capture failure

**vendor-qc** treats this as an actionable verdict (SPIN_DOWN/TIMEBASE_ROUNDING
→ WARN, DROPPED_FRAMES → FAIL, with a recommended remediation). **donor-triage**
only ever reports "VFR detected" generically — it never asserts spin-down vs.
drops, since donor material (raw camera cards, edited masters) may have
legitimately intentional VFR that tape-capture assumptions don't apply to.

### vendor-qc only

| Check | What it does |
|---|---|
| `video_codec` / `video_resolution` / `video_fps` / `video_timescale` / `video_bit_depth` / `video_field_order` | Direct ffprobe-based checks against the profile's `[video]` section |
| `audio[i]_codec` / `audio[i]_bit_depth` / `audio[i]_sample_rate` | Direct checks against the profile's `[audio]` section, per audio stream |
| `mediaconch_policy` | Runs the profile's referenced MediaConch policy XML |

### donor-triage only

| Check | What it does |
|---|---|
| `essence_null_pass_permissive` / `essence_null_pass_strict` | ffmpeg null-muxer decode, permissive (full warning log) then strict (`-xerror`, clean pass/fail). Catches bitrot/essence corruption that metadata checks miss — but **not** dropout-concealment or head-clog artifacts, which leave the file structurally decodable. |

(vendor-qc can also opt into the null-pass check via `--strict-decode-check`.)

## Policy profile format

TOML, loaded via stdlib `tomllib` (no extra dependency). A profile generalizes
what would otherwise be hardcoded per-format policy constants, so a new vendor
format is "add a `.toml` + `.xml`," not new Python code.

```toml
[profile]
name = "v210_quad_ntsc"
description = "..."
container_extensions = [".mov"]
mediaconch_policy = "v210_quad_ntsc.xml"   # resolved against --mediaconch-dir if not absolute

[video]
codec = "v210"
width = 720
height = 486
fps_num = 30000
fps_den = 1001
timescale_multiple = 30000
bit_depth = 10
scan_type = "interlaced"
field_order = ["bb", "bt"]

[audio]
codec_prefix = "pcm"
bit_depth = 24
sample_rate = 48000
min_streams = 1

[thresholds]
av_duration_threshold_s = 1.0
av_delay_threshold_s = 0.001
spin_down_zone = 0.97
frame_anomaly_low_ratio = 0.5
frame_anomaly_high_ratio = 1.5

[capture_quirks]
apply_cropping_zero = true   # pass -apply_cropping 0 on every ffmpeg read of this format
```

`[profile]`, `[video]`, `[audio]`, `[thresholds]` are required sections;
`name`/`description`/`container_extensions`/`mediaconch_policy` are required
keys in `[profile]`. Missing keys within `[video]`/`[audio]` simply skip that
one check rather than erroring — a profile doesn't have to specify every
possible attribute.

The bundled reference profile is `profiles/v210_quad_ntsc.toml`, seeded from
the 2" Quad vendor delivery investigation that motivated this tool. Its
MediaConch policy (`MediaConch/v210_quad_ntsc.xml`) is a **placeholder** —
see the warning comment in that file; it hasn't been confirmed against a
known-good delivery file.

## Known pattern library

`analysis/patterns.py` — a registry of recurring anomaly signatures, each
with a default (vendor-qc) severity, an optional donor-triage override, a
cause, and a remediation. Detectors set `CheckResult.pattern_id` when they
match one of these; severity is resolved per-mode at report-assembly time.

| Pattern ID | vendor-qc | donor-triage | Cause |
|---|---|---|---|
| `VFR_TAIL_ARTIFACT` | WARN | WARN | VTR head spin-down |
| `VFR_TIMEBASE_ROUNDING` | WARN | WARN | Non-multiple-of-30000 timescale |
| `VFR_GENUINE_DROPS` | FAIL | WARN | Dropped frames during capture |
| `FAKE_10BIT_LSHIFT` | FAIL | WARN | 8-bit source left-shifted to 10-bit (**detector deferred to v1.1**) |
| `EXTENSION_FORMAT_MISMATCH` | WARN | WARN | Renamed/mislabeled file |
| `CONTAINER_CODEC_MISMATCH` | FAIL | FAIL | Codec invalid for declared container |
| `MISSING_MOOV_ATOM` | FAIL | FAIL | Incomplete/aborted write |
| `STREAM_DURATION_MISMATCH` | WARN | WARN | Truncation, mux error |
| `MULTI_VIDEO_STREAM` | WARN | WARN | Accidental duplicate stream |

## Output schema

**Per-file JSON** (`<report-dir>/<stem>_qc.json`):
```json
{
  "tool": "sqc v0.1.0",
  "mode": "vendor_qc",
  "profile": "v210_quad_ntsc",
  "timestamp": "...",
  "file": "...",
  "file_size": 12345,
  "overall_status": "WARN",
  "checks": [{"name": "...", "status": "...", "detail": "...", "value": null, "pattern_id": "VFR_TAIL_ARTIFACT"}],
  "frame_stats": {"total_frames": 0, "classification": "SPIN_DOWN", "trim_duration_s": 12.34, "...": "..."},
  "matched_patterns": ["VFR_TAIL_ARTIFACT"],
  "error": null
}
```

Note: raw MediaInfo/ffprobe/MediaTrace/ExifTool dumps are **not** persisted
to the JSON report (kept in memory for the run that produced them only) —
this keeps report files small across a large batch; `checks` + `frame_stats`
capture what's needed for review.

`overall_status` is one of `PASS`, `WARN`, `FAIL`, or `TOOL_FAILURE` (a
worker crash — subprocess timeout, missing binary, unexpected exception —
isolated to that one file; never treated as a completed run for resume
purposes, unlike a genuine `FAIL`).

**CSV summary** — one row per file: `filename, mode, [profile,] overall_status,
file_size_bytes, video_codec, width, height, fps_rational, audio_codec,
audio_sample_rate, frame_analysis_done, anomalous_frame_count,
anomalous_frame_type, trim_duration_s, matched_patterns, error`.

## Key design decisions

- **Structured JSON + CSV + stdlib `logging`, not a hand-rolled text log.**
  `srw`/`vdg` use a hand-rolled `write_log()` because their resume systems
  depend on re-scanning log text for step-completion markers. `sqc` resumes
  by checking whether a file's JSON report already exists, so that
  constraint doesn't apply — stdlib logging levels map directly onto check
  severities (FAIL→ERROR, WARN→WARNING).
- **`ProcessPoolExecutor`, not `srw.batch`'s `ThreadPoolExecutor`.** `srw
  batch` parallelizes whole `srw run` subprocesses (already separate OS
  processes). `sqc` dispatches per-file tool calls from within one Python
  process, so real parallelism needs a process pool.
- **No hardcoded parallelism default.** `--workers` defaults to one slot per
  file, never a CPU-count-derived guess — this workload is typically
  I/O-bound and the real per-machine ceiling has to be measured, matching
  this lab's existing convention in `srw batch --max-parallel`.
- **The VFR taxonomy (`analysis/frame_timing.py`) is a fresh reimplementation**
  of the logic developed in `smpl_qc_v210.py` for the original 2" Quad
  vendor delivery investigation, not an import of that standalone script.
  This keeps `sqc` self-contained and leaves open whether `smpl_qc_v210.py`
  and its companion scripts (`smpl_transcode_ffv1.py`, `qt_timescale_fix.py`)
  get folded into `sqc` later or stay standalone — that decision hadn't been
  made as of v1.
- **donor-triage never asserts SPIN_DOWN-vs-DROPPED_FRAMES as a verdict.**
  That distinction is tape-digitization domain knowledge (a VTR transport
  decelerating vs. a capture system silently concealing a dropped frame);
  arbitrary donor material (raw camera cards, edited masters) may have
  genuinely intentional VFR that those assumptions don't fit, so donor-triage
  reports the detection generically and lets a human decide.
- **`mediaconch_policy` checks run one file per worker, not batched across
  the whole delivery** the way `srw`'s `validate_files_against_policy()`
  batches many files into one CLI call. `sqc`'s architecture parallelizes at
  the file level (one `ProcessPoolExecutor` worker handles one file
  end-to-end), which is a different shape than `srw run`'s single-threaded,
  batched-CLI-call optimization. For very large deliveries, a future
  pre-pass that batches MediaConch calls before per-file dispatch could be
  worth adding — not done for v1.

## Known issues

- `MediaConch/v210_quad_ntsc.xml` is an unverified placeholder — see the
  warning comment at the top of that file. No known-good v210 Quad delivery
  file has been run against it to confirm the MediaInfo field names/values
  it checks (`Format`, `Width`, `Height`, `BitDepth`, `ScanType`) actually
  match what MediaConch reports for this codec.
- Fake-bit-depth detection (`FAKE_10BIT_LSHIFT`) has no detector yet — the
  pattern is registered but nothing sets it. Deferred to v1.1 (needs numpy,
  the only dependency this would add).
- A resumed/skipped file's CSV row has blank codec/resolution columns, since
  those come from the in-memory probe data, which isn't persisted to the
  JSON report. That file's own JSON report has the full detail.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `FATAL ERROR: required tool(s) not found on PATH` | Install the listed tool(s) — see [INSTALL_MACOS.md](INSTALL_MACOS.md)/[INSTALL_UBUNTU.md](INSTALL_UBUNTU.md) |
| `Policy profile 'X' not found` | Check `--profiles-dir`, or pass a direct path to a `.toml` file |
| `mediaconch_policy: SKIP ... Policy file not found` | The profile's `mediaconch_policy` filename doesn't resolve against `--mediaconch-dir` — check the profile's `[profile] mediaconch_policy` value and that the XML exists in `MediaConch/` |
| A file's frame-timing check is `SKIP` | `--full` wasn't passed, or `ffprobe -show_packets` failed for that file (check the run log) |
