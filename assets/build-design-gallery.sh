#!/usr/bin/env bash
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
output="${1:-$root/assets/reactor-design-gallery.jpg}"
regular="${GALLERY_FONT_REGULAR:-/System/Library/Fonts/Supplemental/Arial.ttf}"
bold="${GALLERY_FONT_BOLD:-/System/Library/Fonts/Supplemental/Arial Bold.ttf}"
[[ -r "$regular" ]] || regular=DejaVu-Sans
[[ -r "$bold" ]] || bold=DejaVu-Sans-Bold
tmp="$(mktemp -d "${TMPDIR:-/tmp}/reactor-gallery.XXXXXX")"
trap 'rm -f -- "$tmp/donald.png" "$tmp/mickey.png" "$tmp/dolphin.png" "$tmp/xpen.png"; rmdir -- "$tmp"' EXIT

panel() {
  local source="$1" destination="$2" background="$3" name="$4" detail="$5"
  magick -size 710x530 xc:'#ffffff' \
    \( "$source" -auto-orient -background "$background" -alpha remove -alpha off \
       -resize '670x410' -gravity center -extent 670x410 \) \
    -gravity northwest -geometry +20+20 -composite \
    -font "$bold" -pointsize 34 -fill '#172536' -annotate +20+458 "$name" \
    -font "$regular" -pointsize 23 -fill '#46596c' -annotate +20+499 "$detail" \
    "$destination"
}

panel "$root/donald-microduck/mechanical/preview.png" "$tmp/donald.png" '#191a1c' \
  'Donald Microduck' 'Four-microphone robot adapted from Microduck'
panel "$root/mickeyhub/media/mickeyhub-preview.png" "$tmp/mickey.png" '#d7dbdf' \
  'Mickey Hub' 'Multimodal sensing terminal'
panel "$root/dolphin/previews/complete_enclosure.png" "$tmp/dolphin.png" '#c2c4c6' \
  'Dolphin' 'Two-microphone pan-and-tilt concept'
panel "$root/xpen/media/xpen-v49-assembly.png" "$tmp/xpen.png" '#76797d' \
  'XPen' 'Handheld sensing enclosure | V49 exterior'

magick -size 1540x1310 xc:'#edf1f4' -gravity northwest \
  -font "$bold" -pointsize 59 -fill '#172536' -annotate +40+32 'Reactor' \
  -font "$regular" -pointsize 28 -fill '#46596c' -annotate +42+101 'Robots and compact sensing devices' \
  "$tmp/donald.png" -geometry +40+147 -composite \
  "$tmp/mickey.png" -geometry +790+147 -composite \
  "$tmp/dolphin.png" -geometry +40+701 -composite \
  "$tmp/xpen.png" -geometry +790+701 -composite \
  -font "$regular" -pointsize 20 -fill '#46596c' -annotate +42+1275 'Design renders | Images not to a common scale' \
  -strip -sampling-factor 4:4:4 -quality 92 "$output"
