#!/usr/bin/env bash
# Tests imagetool.sh on real pictures that ImageMagick draws here.
#
#   bash plugins/efficient-browser-use/scripts/imagetool_test.sh
#
# The missing-ImageMagick case always runs. The picture cases need the imagemagick apt
# package: without it they are skipped with the install command, unless
# EBU_REQUIRE_IM=1 asks for a failure instead.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tool="$here/imagetool.sh"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fails=0
pass() { echo "ok    $1"; }
fail() { echo "FAIL  $1"; fails=$((fails + 1)); }
check() { # name, expected, actual
  if [ "$2" = "$3" ]; then pass "$1"; else fail "$1: expected [$2], got [$3]"; fi
}

# ---- No ImageMagick on PATH: NOIM and exit 3, whatever the picture ----
mkdir -p "$work/bare"
for cmd in sh base64 mktemp rm cat; do
  ln -s "$(command -v "$cmd")" "$work/bare/$cmd"
done
status=0
out="$(printf 'aGVsbG8=' | PATH="$work/bare" "$work/bare/sh" "$tool" shrink 50 512)" || status=$?
check "no ImageMagick prints NOIM" "NOIM" "$out"
check "no ImageMagick exits 3" "3" "$status"
status=0
out="$(printf 'aGVsbG8=' | PATH="$work/bare" "$work/bare/sh" "$tool" size)" || status=$?
check "size with no ImageMagick prints NOIM" "NOIM" "$out"
check "size with no ImageMagick exits 3" "3" "$status"

if command -v magick >/dev/null 2>&1; then
  id() { magick identify "$@"; }
  draw() { magick "$@"; }
elif command -v identify >/dev/null 2>&1 && command -v convert >/dev/null 2>&1; then
  id() { identify "$@"; }
  draw() { convert "$@"; }
else
  if [ "${EBU_REQUIRE_IM:-}" = 1 ]; then
    fail "ImageMagick is not installed: sudo apt install imagemagick"
    exit 1
  fi
  echo "SKIP  picture cases: ImageMagick is not installed (sudo apt install imagemagick)"
  [ "$fails" -eq 0 ] && echo "All passed" && exit 0
  exit 1
fi

# Draws a picture: size, file name (the extension picks the format).
make() { draw -size "$1" gradient:navy-orange "$work/$2"; }

# Runs the tool on a file; prints its stdout. Line 1 IN, line 2 SKIP or OUT, line 3 base64.
run() { base64 -w0 "$work/$1" | sh "$tool" "${2:-shrink}" 50 512; }

# Decodes line 3 of a shrink run and prints "<format> <w> <h>".
decoded() {
  printf '%s\n' "$1" | sed -n 3p | base64 -d >"$work/decoded"
  id -format '%m %w %h' "$work/decoded"
}

make 1600x900 wide.png
out="$(run wide.png)"
check "1600x900 PNG: IN line" "IN 1600 900" "$(printf '%s\n' "$out" | sed -n 1p)"
check "1600x900 PNG: half size" "OUT 800 450" "$(printf '%s\n' "$out" | sed -n 2p)"
check "1600x900 PNG: output decodes as an 800x450 PNG" "PNG 800 450" "$(decoded "$out")"

make 900x1600 tall.png
out="$(run tall.png)"
check "900x1600 PNG: half size" "OUT 450 800" "$(printf '%s\n' "$out" | sed -n 2p)"

make 1000x700 photo.jpg
out="$(run photo.jpg)"
check "1000x700 JPEG: IN line" "IN 1000 700" "$(printf '%s\n' "$out" | sed -n 1p)"
check "1000x700 JPEG: held at 512 on the long side" "OUT 512 358" "$(printf '%s\n' "$out" | sed -n 2p)"
check "1000x700 JPEG: output decodes as a JPEG" "JPEG 512 358" "$(decoded "$out")"

make 400x300 small.png
out="$(run small.png)"
check "400x300 PNG: IN line" "IN 400 300" "$(printf '%s\n' "$out" | sed -n 1p)"
check "400x300 PNG: skipped" "SKIP" "$(printf '%s\n' "$out" | sed -n 2p)"

make 512x512 edge.png
out="$(run edge.png)"
check "512x512 PNG: skipped" "SKIP" "$(printf '%s\n' "$out" | sed -n 2p)"

make 1200x800 anim.gif
out="$(run anim.gif)"
check "1200x800 GIF: half size" "OUT 600 400" "$(printf '%s\n' "$out" | sed -n 2p)"
check "1200x800 GIF: comes out PNG" "PNG 600 400" "$(decoded "$out")"

if id -list format 2>/dev/null | grep -q '^ *WEBP'; then
  make 1400x1000 page.webp
  out="$(run page.webp)"
  check "1400x1000 WebP: comes out PNG" "PNG 700 500" "$(decoded "$out")"
fi

# With no percent and no floor the tool uses its defaults: 75%, never under 768 px.
defaults() { base64 -w0 "$work/$1" | sh "$tool" shrink; }

out="$(defaults wide.png)"
check "defaults 1600x900 PNG: IN line" "IN 1600 900" "$(printf '%s\n' "$out" | sed -n 1p)"
check "defaults 1600x900 PNG: 75%" "OUT 1200 675" "$(printf '%s\n' "$out" | sed -n 2p)"
check "defaults 1600x900 PNG: output decodes as a 1200x675 PNG" "PNG 1200 675" "$(decoded "$out")"

out="$(defaults photo.jpg)"
check "defaults 1000x700 JPEG: held at 768 on the long side" "OUT 768 538" "$(printf '%s\n' "$out" | sed -n 2p)"
check "defaults 1000x700 JPEG: output decodes as a JPEG" "JPEG 768 538" "$(decoded "$out")"

make 700x500 mid.png
out="$(defaults mid.png)"
check "defaults 700x500 PNG: IN line" "IN 700 500" "$(printf '%s\n' "$out" | sed -n 1p)"
check "defaults 700x500 PNG: skipped" "SKIP" "$(printf '%s\n' "$out" | sed -n 2p)"

make 768x400 floor.png
out="$(defaults floor.png)"
check "defaults 768x400 PNG: skipped at the floor" "SKIP" "$(printf '%s\n' "$out" | sed -n 2p)"

make 769x400 above.png
out="$(defaults above.png)"
check "defaults 769x400 PNG: brought to the floor" "OUT 768 399" "$(printf '%s\n' "$out" | sed -n 2p)"

out="$(base64 -w0 "$work/wide.png" | sh "$tool" size)"
check "size: prints only the IN line" "IN 1600 900" "$out"
out="$(base64 -w0 "$work/anim.gif" | sh "$tool" size)"
check "size: a GIF's first frame" "IN 1200 800" "$out"
status=0
printf 'not base64 at all!' | sh "$tool" size >/dev/null 2>&1 || status=$?
check "size: input that is not a picture exits 4" "4" "$status"

out="$(run wide.png thumb)"
check "thumb: 160 px on the long side" "THUMB 160 90" "$(printf '%s\n' "$out" | sed -n 1p)"
printf '%s\n' "$out" | sed -n 2p | base64 -d >"$work/thumb"
check "thumb: decodes as a PNG" "PNG 160 90" "$(id -format '%m %w %h' "$work/thumb")"

status=0
printf 'not base64 at all!' | sh "$tool" shrink 50 512 >/dev/null 2>&1 || status=$?
check "input that is not a picture exits 4" "4" "$status"

if [ "$fails" -eq 0 ]; then
  echo "All passed"
else
  echo "$fails failed"
  exit 1
fi
