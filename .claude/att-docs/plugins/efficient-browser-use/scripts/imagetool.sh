#!/bin/sh
# Shrinks a picture, reads its size, or draws a thumbnail of it, with ImageMagick. The
# picture comes in on stdin as base64.
#
#   imagetool.sh shrink [<percent> <min-long-side>]
#     IN <w> <h>
#     then SKIP, when the long side is <min-long-side> px or less,
#     or   OUT <w> <h> and a line with the base64 of the smaller picture.
#     The long side becomes <percent>% of what it was, never under <min-long-side>.
#     Left out, they are 75 and 768.
#     PNG and JPEG keep their format; any other format (GIF, WebP) comes out PNG.
#
#   imagetool.sh size
#     IN <w> <h> and nothing else.
#
#   imagetool.sh thumb
#     THUMB <w> <h> and a line with the base64 of a PNG at most 160 px on its long side.
#
# Exit 3 with NOIM on stdout: neither ImageMagick 7 (magick) nor 6 (identify and
# convert) is installed; the apt package is imagemagick.
# Exit 4: the input is not a picture ImageMagick can read.
set -eu

mode=${1:-}
pct=${2:-75}
min=${3:-768}

if command -v magick >/dev/null 2>&1; then
  id="magick identify"
  cv="magick"
elif command -v identify >/dev/null 2>&1 && command -v convert >/dev/null 2>&1; then
  id="identify"
  cv="convert"
else
  echo NOIM
  exit 3
fi

tmp=$(mktemp -d "${TMPDIR:-/tmp}/imagetool.XXXXXX")
trap 'rm -rf "$tmp"' EXIT

base64 -d >"$tmp/in" 2>/dev/null || { echo "input is not base64" >&2; exit 4; }
# $id holds two words for ImageMagick 7, so it is not quoted. [0] reads the first
# frame of a GIF.
# shellcheck disable=SC2086
info=$($id -ping -format '%w %h %m' "$tmp/in[0]" 2>/dev/null) || { echo "input is not a picture" >&2; exit 4; }
w=${info%% *}
rest=${info#* }
h=${rest%% *}
fmt=${rest#* }

case $mode in
shrink)
  echo "IN $w $h"
  long=$((w > h ? w : h))
  if [ "$long" -le "$min" ]; then
    echo SKIP
    exit 0
  fi
  target=$(((long * pct + 99) / 100))
  target=$((target > min ? target : min))
  if [ "$target" -ge "$long" ]; then
    echo SKIP
    exit 0
  fi
  ow=$(((w * target + long / 2) / long))
  oh=$(((h * target + long / 2) / long))
  ow=$((ow > 0 ? ow : 1))
  oh=$((oh > 0 ? oh : 1))
  case $fmt in
  JPEG | JPG) out="jpeg:$tmp/out"; quality="-quality 85" ;;
  *) out="png:$tmp/out"; quality="" ;;
  esac
  # shellcheck disable=SC2086
  $cv "$tmp/in[0]" -strip -resize "${ow}x${oh}!" $quality "$out"
  echo "OUT $ow $oh"
  base64 -w0 "$tmp/out"
  echo
  ;;
size)
  echo "IN $w $h"
  ;;
thumb)
  # shellcheck disable=SC2086
  $cv "$tmp/in[0]" -strip -thumbnail 160x160 "png:$tmp/out"
  # shellcheck disable=SC2086
  size=$($id -format '%w %h' "$tmp/out")
  echo "THUMB $size"
  base64 -w0 "$tmp/out"
  echo
  ;;
*)
  echo "usage: imagetool.sh shrink [<percent> <min-long-side>] | size | thumb" >&2
  exit 2
  ;;
esac
