# sqc

**sqc** (Stanford Media Preservation Lab QC tool) is a batch quality-control
CLI for video/audio received from outside the lab: outsourced vendor tape
digitization, donor collections, and institutional-partner collection
addenda. It runs a shared cross-tool integrity engine (MediaInfo, ffprobe,
MediaTrace, ExifTool) plus mode-specific checks, and writes a structured
per-file JSON report, a CSV run summary, and a run log.

Sibling to this lab's other pipx tools — [cta](https://github.com/michaelangeletti/cta),
[srw](https://github.com/michaelangeletti/srw), [vdg](https://github.com/michaelangeletti/vdg).

## Two modes

- **`sqc vendor-qc`** — spec conformance against a pluggable policy profile.
  For outsourced tape digitization deliveries (2" Quad, 1" Type C, etc.)
  that must match a written technical spec. Checks a MediaConch policy, the
  profile's declared codec/resolution/fps/bit-depth/audio attributes, and
  classifies any VFR into the three-cause taxonomy (timescale rounding /
  VTR head spin-down / genuine dropped frames).
- **`sqc donor-triage`** — well-formedness only, no spec required. For donor
  collections and institutional-partner collection addenda (including raw
  camera cards) — just tells you which files are structurally broken or
  have essence-level corruption, without needing a written spec to check
  against.

## Quick start

```bash
# Vendor delivery against the bundled 2" Quad -> v210 profile
sqc vendor-qc --profile v210_quad_ntsc --full /Volumes/Vendor_Delivery

# Donor collection, no spec
sqc donor-triage --full /Volumes/Donor_Collection
```

Each run writes:
- `<report-dir>/<stem>_qc.json` — per-file structured report (checks, VFR
  frame stats, matched pattern IDs)
- `<report-dir>/summary.csv` — one row per file
- a run log (`--log-file`, or a timestamped default)

Reruns skip files that already have a completed report (`--no-resume` to
disable).

## Install

See [INSTALL_MACOS.md](INSTALL_MACOS.md) or [INSTALL_UBUNTU.md](INSTALL_UBUNTU.md).

## Required tools

`ffmpeg`/`ffprobe`, `mediainfo`, `mediaconch` (also provides MediaTrace via
`-mt`), `exiftool`. `sqc` checks for whichever of these a given run's checks
actually need and reports a platform-appropriate install hint if one's missing.

## Documentation

- [MANUAL.md](MANUAL.md) — full reference: flags, check catalog, policy
  profile format, known pattern library, output schemas.
- [CLAUDE.md](CLAUDE.md) — development context and changelog.

## License

MIT — see [LICENSE](LICENSE).
