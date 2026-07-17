#!/usr/bin/env bash
# make_test_media.sh — Generate a synthetic test media set for sqc smoke testing.
#
# Usage:
#   bash scripts/make_test_media.sh [OUTPUT_DIR]
#
# OUTPUT_DIR defaults to ./test_media (created if it doesn't exist).
# All files use ffmpeg lavfi sources (color bars + 1 kHz sine tone) — no real content needed.
# Files are NOT committed to the repo; regenerate them here as needed.
#
# Dependencies: ffmpeg with v210 and prores_ks encoder support.
#   macOS:  brew install ffmpeg
#   Ubuntu: sudo apt install ffmpeg
#
# Approximate output size: ~800 MB (10 files × 3 seconds each at v210 bitrate).
#
# What each file exercises:
#
#   good_ntsc.mov          → PASS  (vendor-qc baseline: all checks green)
#   wrong_codec.mov        → FAIL  video_codec (ProRes, not v210)
#   wrong_resolution.mov   → WARN  video_resolution (720×480, not 720×486)
#   wrong_fps.mov          → WARN  video_fps + MediaConch NTSC rules (25fps, not 29.97)
#   wrong_field_order.mov  → WARN  video_field_order + MediaConch ScanOrder (TFF, not BFF)
#   timebase_rounding.mov  → WARN  video_timescale + frame_timing (timescale 90000, not 30000)
#   no_audio.mov           → WARN  audio_policy (no audio stream)
#   wrong_audio_depth.mov  → FAIL  audio[0]_bit_depth (16-bit PCM, not 24-bit)
#   truncated.mov          → FAIL  ffprobe_probe + MISSING_MOOV_ATOM (moov cut off)
#   extension_mismatch.avi → WARN  EXTENSION_FORMAT_MISMATCH (valid .mov renamed to .avi)
#
# After generating, run:
#   sqc vendor-qc --profile v210_quad_ntsc --full OUTPUT_DIR
#   sqc donor-triage --full OUTPUT_DIR
#
# NOTE: VFR tail (SPIN_DOWN) and genuine dropped frames (DROPPED_FRAMES) are best
# tested with a real vendor delivery file trimmed to a few seconds. Those cases require
# specific packet-duration patterns that are difficult to synthesize reliably with
# ffmpeg alone. See the commented section at the bottom for an approach.

set -euo pipefail

OUTDIR="${1:-./test_media}"
mkdir -p "$OUTDIR"

DUR=3  # seconds per clip

# Source definitions
BARS_NTSC="smptebars=size=720x486:rate=30000/1001"
BARS_480="smptebars=size=720x480:rate=30000/1001"
AUDIO="aevalsrc=sin(2*PI*1000*t)|sin(2*PI*1000*t):c=stereo:s=48000"

# Flags shared by conforming files
COLOR=(-color_primaries smpte170m -color_trc bt709 -colorspace smpte170m)
AUDIO_FLAGS=(-c:a pcm_s24le -ar 48000 -ac 2)
QT=(-movflags write_colr -video_track_timescale 30000)
VFILT_BFF="setfield=bff,setparams=colorspace=smpte170m:color_primaries=smpte170m:color_trc=bt709"
VFILT_TFF="setfield=tff,setparams=colorspace=smpte170m:color_primaries=smpte170m:color_trc=bt709"

echo "Writing test media to: $OUTDIR"
echo "(each clip: ${DUR}s — expect ~80 MB per v210 file)"
echo ""

# ---------------------------------------------------------------------------
# 1. PASS — fully conforming v210 NTSC QuickTime file
# ---------------------------------------------------------------------------
echo "[1/10] good_ntsc.mov"
ffmpeg -y -loglevel error \
  -f lavfi -i "$BARS_NTSC" \
  -f lavfi -i "$AUDIO" \
  -t $DUR \
  -c:v v210 -vf "$VFILT_BFF" \
  "${AUDIO_FLAGS[@]}" "${COLOR[@]}" "${QT[@]}" \
  "$OUTDIR/good_ntsc.mov"

# ---------------------------------------------------------------------------
# 2. FAIL: codec — ProRes HQ instead of v210
# ---------------------------------------------------------------------------
echo "[2/10] wrong_codec.mov"
ffmpeg -y -loglevel error \
  -f lavfi -i "$BARS_NTSC" \
  -f lavfi -i "$AUDIO" \
  -t $DUR \
  -c:v prores_ks -profile:v 3 -vf "$VFILT_BFF" \
  "${AUDIO_FLAGS[@]}" "${COLOR[@]}" -movflags write_colr \
  "$OUTDIR/wrong_codec.mov"

# ---------------------------------------------------------------------------
# 3. WARN: resolution — 720×480 instead of 720×486
# ---------------------------------------------------------------------------
echo "[3/10] wrong_resolution.mov"
ffmpeg -y -loglevel error \
  -f lavfi -i "$BARS_480" \
  -f lavfi -i "$AUDIO" \
  -t $DUR \
  -c:v v210 -vf "$VFILT_BFF" \
  "${AUDIO_FLAGS[@]}" "${COLOR[@]}" "${QT[@]}" \
  "$OUTDIR/wrong_resolution.mov"

# ---------------------------------------------------------------------------
# 4. WARN: frame rate — 720×486 v210 at 25fps instead of 29.97
# ---------------------------------------------------------------------------
echo "[4/10] wrong_fps.mov"
ffmpeg -y -loglevel error \
  -f lavfi -i "smptebars=size=720x486:rate=25" \
  -f lavfi -i "$AUDIO" \
  -t $DUR \
  -c:v v210 -vf "$VFILT_BFF" \
  "${AUDIO_FLAGS[@]}" "${COLOR[@]}" \
  -movflags write_colr -video_track_timescale 25 \
  "$OUTDIR/wrong_fps.mov"

# ---------------------------------------------------------------------------
# 5. WARN: field order — v210 TFF instead of BFF
# ---------------------------------------------------------------------------
echo "[5/10] wrong_field_order.mov"
ffmpeg -y -loglevel error \
  -f lavfi -i "$BARS_NTSC" \
  -f lavfi -i "$AUDIO" \
  -t $DUR \
  -c:v v210 -vf "$VFILT_TFF" \
  "${AUDIO_FLAGS[@]}" "${COLOR[@]}" "${QT[@]}" \
  "$OUTDIR/wrong_field_order.mov"

# ---------------------------------------------------------------------------
# 6. WARN: VFR timescale rounding — timescale 90000 instead of 30000
#    At 30000/1001 fps with timescale 90000, frames alternate between 3003
#    and 3004 ticks → MediaInfo reports VFR. Run with --full to see the
#    frame_timing WARN (VFR_TIMEBASE_ROUNDING). Cosmetic only, not a real error.
# ---------------------------------------------------------------------------
echo "[6/10] timebase_rounding.mov"
ffmpeg -y -loglevel error \
  -f lavfi -i "$BARS_NTSC" \
  -f lavfi -i "$AUDIO" \
  -t $DUR \
  -c:v v210 -vf "$VFILT_BFF" \
  "${AUDIO_FLAGS[@]}" "${COLOR[@]}" \
  -movflags write_colr -video_track_timescale 90000 \
  "$OUTDIR/timebase_rounding.mov"

# ---------------------------------------------------------------------------
# 7. WARN: no audio — video-only file, no audio stream at all
# ---------------------------------------------------------------------------
echo "[7/10] no_audio.mov"
ffmpeg -y -loglevel error \
  -f lavfi -i "$BARS_NTSC" \
  -t $DUR \
  -c:v v210 -vf "$VFILT_BFF" \
  -an "${COLOR[@]}" "${QT[@]}" \
  "$OUTDIR/no_audio.mov"

# ---------------------------------------------------------------------------
# 8. FAIL: audio bit depth — pcm_s16le (16-bit) instead of pcm_s24le (24-bit)
# ---------------------------------------------------------------------------
echo "[8/10] wrong_audio_depth.mov"
ffmpeg -y -loglevel error \
  -f lavfi -i "$BARS_NTSC" \
  -f lavfi -i "$AUDIO" \
  -t $DUR \
  -c:v v210 -vf "$VFILT_BFF" \
  -c:a pcm_s16le -ar 48000 -ac 2 \
  "${COLOR[@]}" "${QT[@]}" \
  "$OUTDIR/wrong_audio_depth.mov"

# ---------------------------------------------------------------------------
# 9. FAIL: truncated file — good v210 .mov cut to 10% of its size
#    By default ffmpeg writes moov at the end of the file, so cutting to 10%
#    removes the moov atom. ffprobe returns non-zero; MediaTrace finds no moov.
#    Expected: ffprobe_probe FAIL and/or MISSING_MOOV_ATOM FAIL.
# ---------------------------------------------------------------------------
echo "[9/10] truncated.mov"
ffmpeg -y -loglevel error \
  -f lavfi -i "$BARS_NTSC" \
  -f lavfi -i "$AUDIO" \
  -t $DUR \
  -c:v v210 -vf "$VFILT_BFF" \
  "${AUDIO_FLAGS[@]}" "${COLOR[@]}" "${QT[@]}" \
  "$OUTDIR/_truncated_src.mov"
FULL_SIZE=$(wc -c < "$OUTDIR/_truncated_src.mov" | tr -d ' ')
TRUNC_SIZE=$(( FULL_SIZE / 10 ))
python3 -c "
import sys
src, dst, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
open(dst, 'wb').write(open(src, 'rb').read(n))
" "$OUTDIR/_truncated_src.mov" "$OUTDIR/truncated.mov" "$TRUNC_SIZE"
rm "$OUTDIR/_truncated_src.mov"

# ---------------------------------------------------------------------------
# 10. WARN: extension mismatch — valid v210 .mov file with a .avi extension
#     Expected: EXTENSION_FORMAT_MISMATCH WARN (detected format is MPEG-4/QuickTime,
#     not AVI — binary headers don't match the .avi file extension).
# ---------------------------------------------------------------------------
echo "[10/10] extension_mismatch.avi"
cp "$OUTDIR/good_ntsc.mov" "$OUTDIR/extension_mismatch.avi"

# ---------------------------------------------------------------------------
echo ""
echo "Done. Sizes:"
du -sh "$OUTDIR"/* 2>/dev/null
echo ""
echo "Run vendor-qc:"
echo "  sqc vendor-qc --profile v210_quad_ntsc --full $OUTDIR"
echo ""
echo "Run donor-triage:"
echo "  sqc donor-triage --full $OUTDIR"

# ---------------------------------------------------------------------------
# VFR TAIL / DROPPED FRAMES (advanced — see notes below)
#
# SPIN_DOWN (VFR_TAIL_ARTIFACT): A few doubled-duration packets at the end of
# the file — consistent with VTR head spin-down on tape stop. Hard to synthesize
# cleanly. Best approach: trim 5-10 seconds from the end of a real 2" Quad
# delivery file that exhibited this behavior, then run through sqc --full.
#
# If you want to attempt synthesis, the following uses a concat of a normal-rate
# body and a half-rate tail, with -fps_mode vfr to preserve the variable PTS:
#
#   ffmpeg -y \
#     -f lavfi -i "$BARS_NTSC,trim=duration=2.9" \
#     -f lavfi -i "smptebars=size=720x486:rate=15000/1001,trim=duration=0.134" \
#     -f lavfi -i "$AUDIO" \
#     -filter_complex "[0:v][1:v]concat=n=2:v=1[v]" \
#     -map "[v]" -map "2:a" \
#     -c:v v210 -fps_mode vfr \
#     "${AUDIO_FLAGS[@]}" "${COLOR[@]}" "${QT[@]}" \
#     "$OUTDIR/vfr_tail.mov"
#
# DROPPED_FRAMES (VFR_GENUINE_DROPS): Anomalous-duration packets distributed
# across the file, not clustered at the tail. This pattern is not reliably
# reproducible with synthetic sources and is best tested with a real file
# that had genuine capture drops.
# ---------------------------------------------------------------------------
