# sqc — Claude Code Context

Context for continuing development on this project. For usage/install docs
see [README.md](README.md), [MANUAL.md](MANUAL.md), [INSTALL_MACOS.md](INSTALL_MACOS.md),
[INSTALL_UBUNTU.md](INSTALL_UBUNTU.md).

## What this is

`sqc` (package `sqc`) is a batch quality-control CLI for the Stanford Media
Preservation Lab (SMPL), covering three real-world intake scenarios: (1)
outsourced vendor tape digitization (2" Quad, 1" Type C, sometimes 1/2" EIAJ)
that must conform to a written spec — **`sqc vendor-qc`**; (2) donor
collections and institutional-partner collection addenda (including raw
camera cards), which have no spec but must be well-formed before
accessioning — **`sqc donor-triage`**. Per an explicit user decision, donor
and partner-addendum material share one mode rather than three, since the
distinction was judged too subtle to warrant a separate mode.

Cross-platform (macOS + Ubuntu), like `vdg` — unlike `srw`, which is
Ubuntu-only because RAWcooked/mkvtoolnix have no macOS path.

## Origin

Two prior threads fed into this tool's design:

1. **`video_diagnostic_tool_design.md`** (referred to below as "Doc A") — an
   earlier design conversation for a similarly-scoped tool (there called
   "videodx"): a 5-layer analysis stack (MediaInfo/ffprobe/MediaTrace/ExifTool
   cross-check → MediaConch policy → ffmpeg null-pass → fake-bit-depth
   detection), a known-pattern library, and JSON-first per-file reporting.
2. **`SMPL_VendorQC_ClaudeCode_Context.md`** (referred to below as "Doc B")
   plus three working reference scripts (`smpl_qc_v210.py` v1.0.2,
   `smpl_transcode_ffv1.py` v2.0.9, `qt_timescale_fix.py` v1.0.0) built to
   handle one specific vendor delivery problem: ~110 v210 QuickTime files
   from 2" Quad digitization, half flagged VFR by MediaInfo. That
   investigation is the intellectual core this tool generalizes from — see
   "The VFR three-way taxonomy" below.

`sqc` unifies these into one installable tool, sibling to this lab's other
3-letter pipx tools ([cta](https://github.com/michaelangeletti/cta),
[srw](https://github.com/michaelangeletti/srw), [vdg](https://github.com/michaelangeletti/vdg)).

## Current state

At **v0.2.0**. Both modes are implemented end-to-end and verified against
real local files (see "Verification done so far" below).

- **v0.2.0: VFR taxonomy de-emphasis + a real gap fix, both from user
  feedback after using v0.1.0 for a day.**
  - **VFR taxonomy de-emphasis.** Michael flagged that `--spin-down-zone`/
    `--frame-anomaly-low-ratio`/`--frame-anomaly-high-ratio` as top-level
    `vendor-qc` CLI flags overstated how general-purpose that tuning is —
    the specific "tail-only anomaly" behavior came from one vendor's
    isolated 2" Quad/VTR/TBC signal chain, not something every run needs a
    knob for. He was explicit that sqc's job is *diagnosis* (is this file
    valid, what's wrong, does it need a FAILED log + vendor/donor
    notification), not remediation — the fix scripts
    (`smpl_transcode_ffv1.py`/`qt_timescale_fix.py`) are a separate concern,
    and the detection/reporting side of that work (which he does want to
    keep) shouldn't have dragged this much CLI surface along with it.
    - Removed the three flags from `add_vendor_qc_arguments()` (`cli.py`)
      and the matching fields from `VendorQCConfig` (`config.py`). Those
      thresholds are now profile-only — `modes/vendor_qc.py::process_file()`
      reads them straight from `profile.thresholds`, no CLI override layer
      for them anymore (only `--av-duration-threshold` still overrides,
      since A/V sync tolerance isn't VFR-taxonomy-specific).
    - Kept `classify_frame_timing()` and all three classification buckets
      exactly as they were — the *positional heuristic* (tail-only vs.
      distributed anomalies) is generically useful and not really tape/VTR-
      specific; only the CLI-level prominence and the "VTR head spin-down"
      framing needed adjusting, not the underlying detection. Reworded
      MANUAL.md's `SPIN_DOWN` description to make that distinction explicit
      (name/defaults come from one cause; the classification logic is
      broader than that one cause).
    - `--full` (frame-level packet timing analysis) is unchanged and still
      recommended generally — Michael specifically said he likes that part.
  - **Real gap found from Michael's own QC checklist:** a file with no
    extension at all (`ext == ""`) was silently `SKIP`ped by
    `check_extension_format_match()` instead of being flagged — it fell into
    the same "extension or format_name unavailable" branch as a genuine
    probe gap. A missing extension is itself worth a WARN
    (`EXTENSION_FORMAT_MISMATCH`), distinct from "we don't know the detected
    format" (still SKIP). Fixed and added test coverage
    (`test_missing_extension_warns_with_pattern`).
  - See "Planned future work" below for the rest of Michael's lunchtime
    checklist (general + QuickTime/MP4-specific checks) — sorted there by
    how much new design/implementation each actually needs, not yet built.

- **v0.1.0:** Initial implementation.
  - Shared engine (`analysis/crosscheck.py`): cross-tool comparison
    (MediaInfo/ffprobe/MediaTrace/ExifTool), container/essence integrity
    (moov atom presence via MediaTrace, extension/format mismatch,
    container/codec validity, stream inventory, A/V duration sync,
    frame-count-vs-duration sanity, cross-tool duration comparison).
    Adapted from `smpl_qc_v210.py`'s `check_integrity()`/`check_container()`/
    `check_timecode_track()`, generalized to not assume a specific
    codec/resolution/fps policy or a `tmcd` timecode track's presence.
  - VFR three-way taxonomy (`analysis/frame_timing.py`): a **fresh
    reimplementation** of `smpl_qc_v210.py`'s `analyze_frame_durations()`
    (same algorithm/thresholds), not an import of that script — see "Key
    design decisions" for why. `classify_frame_timing()` is a pure function
    shared by both modes; each mode's orchestrator interprets the resulting
    classification with different severity (see below).
  - Known pattern library (`analysis/patterns.py`): a plain registry of 9
    `Pattern` entries from Doc A's table, each with a default (vendor-qc)
    severity and an optional donor-triage override.
  - `vendor_qc` mode: direct ffprobe-based technical-attribute checks
    against a loaded `PolicyProfile`'s `[video]`/`[audio]` sections
    (generalized from `smpl_qc_v210.py`'s `check_video_stream()`/
    `check_audio_streams()`), a MediaConch policy check (`tools/mediaconch.py`
    ported from `srw`'s proven `run_mediaconch()`/
    `validate_files_against_policy()`), and full-severity VFR taxonomy
    interpretation.
  - `donor_triage` mode: shared engine + reduced-severity VFR interpretation
    (never asserts SPIN_DOWN-vs-DROPPED_FRAMES) + an ffmpeg null-pass essence
    check, on by default (this mode's main defense against corruption with
    no policy to check metadata against).
  - Policy profiles are TOML (`policy.py`, stdlib `tomllib`), generalizing
    `smpl_qc_v210.py`'s hardcoded `POLICY_DEFAULTS` dict so a new vendor
    format is "add a `.toml` + `.xml`," not new Python code. Bundled
    reference profile: `profiles/v210_quad_ntsc.toml`.
  - Batch orchestration (`batch.py`): `ProcessPoolExecutor`, resume-by-
    existing-JSON-report (not log-text parsing), per-file `TOOL_FAILURE`
    isolation so one bad file never halts a batch. `--workers` has no
    hardcoded default (see [[no-hardcoded-parallelism-limits]] / this lab's
    standing rule) — `None` means one worker slot per file.
  - Logging uses stdlib `logging`, not the hand-rolled `write_log()`
    convention `srw`/`vdg` use — see "Key design decisions."
  - `MediaConch/v210_quad_ntsc.xml` is a **placeholder**, not a verified lab
    policy — no MediaConch XML for the 2" Quad delivery spec existed among
    the source documents (Doc B describes the policy as a Python dict, not
    a MediaConch policy file). Flag to the user whether a real one exists
    elsewhere before relying on it for an actual accept/reject decision.
  - Fake-bit-depth detection (`FAKE_10BIT_LSHIFT`) is registered in the
    pattern library but has no detector yet — deferred to v1.1 (needs
    numpy, the only dependency this would add; none of this lab's other
    pipx tools currently carry it).

## Verification done so far

Smoke-tested end-to-end via the actual installed CLI (not just unit tests)
against a real local `.mov` file (`/System/Library/Photos/Resources/
PXFooterAnimation.bundle/.../PXFooterAnimationLightWithAlpha.mov` — an HEVC
QuickTime file, useful precisely because it's *not* v210, so it exercises
the FAIL paths):
- `sqc donor-triage --full` produced a correct JSON report, CSV row, and log;
  correctly caught a real HEVC parameter-set decode failure via the strict
  null-pass check (`essence_null_pass_strict` → FAIL) — the file has genuine
  VPS/SPS/PPS issues, not a synthetic test case.
- `sqc vendor-qc --profile v210_quad_ntsc --full` correctly rejected the same
  file against every video/audio policy check (wrong codec, resolution, fps,
  bit depth, field order) and the MediaConch policy XML parsed and ran
  without error.
- Resume-by-JSON-existence confirmed: a second run against the same input
  skipped the already-processed file.
- An initial version of `check_probe_integrity()` (ported near-verbatim from
  `smpl_qc_v210.py`) produced a false-positive FAIL against this file — 612
  ffprobe warning-level lines (HEVC decoder chatter: "Unexpected extra rep
  formats") didn't contain the literal substrings "warning"/"deprecated"
  that the original script's severity heuristic checked for. Fixed by
  defaulting to WARN instead of text-sniffing, since `check_probe_integrity`
  is only ever called with stderr from a probe that already returned exit 0
  — see the docstring in `analysis/crosscheck.py`.
- Not yet tested: an actual v210 file from a real 2" Quad delivery (none
  were available in this session) — the bundled profile/policy and the VFR
  taxonomy logic should be re-verified against one when available, per the
  approved plan's verification section.

## Key design decisions

- **Structured JSON + CSV + stdlib `logging`, not `srw`/`vdg`'s hand-rolled
  `write_log()`.** Those tools' resume systems depend on re-scanning log
  text for step-completion markers; `sqc` resumes by checking whether a
  file's JSON report already exists, so that constraint doesn't apply, and
  `smpl_qc_v210.py` already proved stdlib logging + JSON + CSV works well
  for this exact problem shape.
- **`ProcessPoolExecutor`, not `srw.batch`'s `ThreadPoolExecutor`.** `srw
  batch` parallelizes whole `srw run` subprocesses (already separate OS
  processes, so threads suffice). `sqc` dispatches per-file tool calls from
  within one Python process, so real parallelism needs a process pool.
- **No hardcoded parallelism default** — `--workers` defaults to one slot
  per file, mirroring `srw.batch`'s own `max_workers = args.max_parallel or
  len(jobs)` pattern. This lab's standing rule: measure the real per-machine
  I/O ceiling with `iostat`/`iotop`, don't guess from CPU count.
- **VFR taxonomy is a fresh reimplementation, not an import of
  `smpl_qc_v210.py`.** The user hadn't decided whether those three scripts
  get folded into `sqc` or stay standalone; a fresh, independently-testable
  `classify_frame_timing()` function keeps that decision open — either a
  later import of `smpl_qc_v210.analyze_frame_durations` or the reverse
  (that script importing from `sqc`) is a drop-in swap, not a rewrite.
- **donor-triage never asserts SPIN_DOWN-vs-DROPPED_FRAMES.** That
  distinction is tape-digitization domain knowledge; arbitrary donor
  material may have genuinely intentional VFR the taxonomy's tape-capture
  assumptions don't fit, so donor-triage reports detection generically and
  defers the call to a human.
- **MediaConch checks run one file per worker**, not batched across a whole
  delivery the way `srw`'s `validate_files_against_policy()` batches many
  files into one CLI call — a consequence of parallelizing at the file
  level rather than `srw run`'s single-threaded-but-batched-CLI-call shape.
  Worth revisiting with a pre-pass batching step for very large deliveries;
  not done for v1.
- **`analysis/crosscheck.py`'s `check_probe_integrity()` defaults unclassified
  ffprobe stderr to WARN, not FAIL** (see "Verification done so far" above)
  — a deliberate improvement over the pattern it was adapted from, since
  `donor-triage`'s whole point is handling heterogeneous, unpredictable
  files where format-specific decoder chatter shouldn't be mistaken for
  structural failure.

## Known issues and investigations

- **`MediaConch/v210_quad_ntsc.xml` is unverified** — translated from
  `smpl_qc_v210.py`'s `POLICY_DEFAULTS` dict into MediaConch rule syntax
  (mirroring `srw/MediaConch/WAV_policy.xml`'s structure), but never run
  against a known-good v210 Quad delivery file. Confirm the MediaInfo field
  names/values it checks are correct before relying on it for a real
  accept/reject decision.
- **No real v210 test file was available during initial development** — all
  smoke testing used a non-v210 (HEVC) `.mov` to exercise the FAIL paths.
  The VFR taxonomy's SPIN_DOWN/DROPPED_FRAMES/TIMEBASE_ROUNDING
  classification logic is a faithful port of `smpl_qc_v210.py`'s proven
  algorithm, but hasn't been re-verified end-to-end against real tape
  digitization output through `sqc` itself.

## Development approach

- Iterative, incremental — this is a from-scratch build; features were
  built in dependency order (shared engine → donor-triage → policy/vendor-qc
  → pattern library → docs → tests) and smoke-tested against real local
  files at each stage rather than only unit-tested.
- Preserve all existing logic when adding features — changes should be
  surgical, matching `vdg`/`srw`'s stated convention.
- Only pure functions and parsing/classification logic get unit tests;
  anything that shells out to a real external tool is tested with
  `subprocess.run` mocked, not invoked for real — matching `srw`/`vdg`'s
  explicit, deliberate testing convention. Validate real-tool integration
  manually against real or synthetic files.
- Source and output directories should stay separate, matching the other
  lab tools' hard-learned convention (not directly applicable to `sqc`
  since it doesn't write derivative media, but `--report-dir` should still
  not be pointed at the input directory).

## Planned future work

### Michael's 2026-07-15 checklist (general + QuickTime/MP4 checks)

Not yet built — captured here so it isn't lost, sorted by how much new
design/implementation each needs rather than in the order given. "Other
container/codec types" was left as an open "???" in the original list —
still needs a first pass at what's worth checking for MXF, MKV, WAV, etc.

**Quick wins (mostly new logic over data sqc already probes, no new tooling):**
- File-size-vs-declared-stream sanity — compute an expected minimum size
  from `bit_rate` × duration (per stream or format-level) and flag when
  actual file size is far below that. This is also the practical detector
  for a QuickTime **reference movie** (an alias/pointer `.mov` with no real
  media data, just resource references to external files) — those files
  are typically tiny relative to their claimed duration, so this one check
  covers both the general "does file size make sense" question and the
  QuickTime-specific reference-movie case, without needing separate logic.
- DAR/SAR/PAR/coded-vs-display-dimension consistency — ffprobe already
  reports `width`/`height`, `sample_aspect_ratio`, `display_aspect_ratio`,
  and clean-aperture `Frame Cropping` side data (see `vdg`'s CLAUDE.md,
  which hit exactly this) in the probe data `sqc` already has; just needs
  a new check comparing them for internal conflicts.
- Per-stream (not just whole-file) decodability — right now the null-pass
  (`tools/ffmpeg_null.py`) decodes everything together; running it once per
  stream (`-map 0:v:0` / `-map 0:a:N`) would identify *which* stream fails
  rather than just "something in this file didn't decode."
- Obsolete/at-risk codec flagging (e.g. Sorenson, Cinepak, Indeo — decode
  fine today, real long-term support risk) — this is a `analysis/patterns.py`
  registry addition (a maintained codec-name lookup list + a new pattern
  entry), not new tooling; fits the existing architecture directly.
- `EXTENSION_FORMAT_MISMATCH`'s missing-extension case was an existing gap,
  already fixed in v0.2.0 (see "Current state" above) — worth noting here
  since it came from this same checklist.

**Needs real design work before implementing:**
- **A/V interleaving order** (all video chunks dumped first, then all audio
  at the end, instead of properly interleaved for streaming/scrubbing) —
  requires parsing per-track chunk offsets (`stco`/`co64`) out of the moov
  atom and checking whether video/audio chunk byte-offsets actually
  alternate through the file or sit in two segregated blocks. MediaTrace's
  XML output exposes box/atom structure but not obviously in a
  ready-to-diff per-track-offset-sequence form — needs investigation into
  whether MediaTrace surfaces this at a usable level of detail, or whether
  a lightweight direct box parser is needed.
- **Broken chunk-offset tables** (`stco`/`co64` entries pointing past EOF or
  into garbage, from bad sectors or a truncated transfer) — same
  investigation as above: need to confirm whether MediaTrace exposes raw
  `stco`/`co64` values, or whether validating "every chunk offset is within
  the actual file's byte length" needs a small dedicated MP4 box-walker
  module. If MediaTrace doesn't expose this cleanly, this is the one item
  on the whole list that might justify a new dependency or a hand-rolled
  binary parser.

**Open question, not yet decided:** the general checklist puts "is the
container/codec decodable" as a baseline check, which is currently the
`ffmpeg_null` essence check — opt-in for `vendor-qc` (`--strict-decode-check`,
default off) because a full decode of a large uncompressed master isn't
free. Worth revisiting whether `vendor-qc` should default this on too, or
whether MediaConch + the crosscheck layer are judged sufficient there and
the full decode stays donor-triage's job. Not changed yet — flag to Michael
next time this comes up.

### Everything else

- Verify `MediaConch/v210_quad_ntsc.xml` against a real 2" Quad delivery
  file, or confirm whether a real, already-in-use lab policy exists
  elsewhere that should replace this placeholder.
- Fake-bit-depth detection (`FAKE_10BIT_LSHIFT`) — numpy-based LSB sampling
  for lossless/uncompressed 10-bit codecs (v210, FFV1 10-bit, uncompressed
  10-bit MXF). Deferred because it's vendor-qc-only, narrow in applicable
  codecs, and would be this tool's first non-`tqdm` dependency.
  ExifTool-driven encoder-provenance pattern matching beyond raw metadata
  capture (e.g. known-bad Handbrake version fingerprints) — also deferred
  until real report data shows what's worth automating.
- Additional policy profiles for 1" Type C and outsourced 1/2" EIAJ — the
  schema supports them today; they need this lab's own written vendor
  specs first, which didn't exist in hand during initial development.
- A possible pre-pass MediaConch batching step ahead of per-file dispatch,
  for very large vendor deliveries (see "MediaConch checks run one file per
  worker" above).
- A decision on whether `smpl_qc_v210.py`/`smpl_transcode_ffv1.py`/
  `qt_timescale_fix.py` get folded into `sqc` or stay standalone — left
  open by design (see "Key design decisions").

## Tools & ecosystem

- **ffprobe/ffmpeg** — container/stream metadata, packet-duration index
  reads (no decode), and the null-muxer essence-corruption check.
- **MediaInfo** — "reported metadata" lens; JSON output mode.
- **MediaConch** — policy conformance checks (`vendor-qc` only) and
  MediaTrace ("binary anatomy" lens) via `--Mediatrace`/`-mt` — confirmed
  locally there's no separate MediaTrace binary.
- **ExifTool** — embedded metadata/encoder-provenance lens; currently
  surfaced raw, no pattern-matching built on it yet.
- **tomllib** (stdlib, 3.11+) — parses policy profiles; no third-party
  dependency added for this, matching `srw`'s same justification for its
  batch TOML config.
- **tqdm** — batch progress reporting; matches `vdg`'s existing dependency,
  no new one added.
- **[cta](https://github.com/michaelangeletti/cta)**,
  **[srw](https://github.com/michaelangeletti/srw)**,
  **[vdg](https://github.com/michaelangeletti/vdg)** — sibling SMPL pipx
  tools; `sqc` was packaged to match their structure (pyproject.toml +
  console-script entry point, `bin/` thin wrapper, README/MANUAL/INSTALL
  doc split, CLAUDE.md context file).
