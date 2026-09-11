#!/usr/bin/env bash
# Transcode recorded walkthrough webms to mp4.
#
# `tour.finalize_video` does this itself when a SYSTEM ffmpeg is on PATH.
# Playwright ships its own build, but it is compiled down to what recording
# needs (vp8/webm, no libx264, no mp4 muxer), so it cannot be used. On a machine
# without ffmpeg the webm is still written and still plays; this script fills in
# the mp4s afterwards rather than re-recording.
#
# Usage:  bash scripts/transcode_walkthroughs.sh [FFMPEG_BIN]
set -uo pipefail

FFMPEG="${1:-ffmpeg}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.curio/walkthroughs"

command -v "$FFMPEG" >/dev/null 2>&1 || [ -x "$FFMPEG" ] || {
  echo "no ffmpeg at '$FFMPEG'" >&2
  exit 1
}

made=0
for webm in "$DIR"/*.webm; do
  [ -e "$webm" ] || continue
  mp4="${webm%.webm}.mp4"
  if [ -f "$mp4" ] && [ "$mp4" -nt "$webm" ]; then
    continue
  fi
  # Same encode tour.py asks for: H.264 + yuv420p so it plays everywhere,
  # +faststart so it streams rather than waiting for the whole file.
  if "$FFMPEG" -y -loglevel error -i "$webm" \
      -c:v libx264 -preset veryfast -crf 23 -pix_fmt yuv420p \
      -movflags +faststart "$mp4" </dev/null; then
    echo "wrote $(basename "$mp4")"
    made=$((made + 1))
  else
    echo "FAILED $(basename "$webm")" >&2
  fi
done
echo "$made mp4(s) written to $DIR"
