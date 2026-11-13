#!/bin/sh
# Builds the reference streams of the media-decode workload. Used by
# target/Dockerfile, in a stage that runs on the building machine: the
# streams are data, the same for every target architecture.
#   build-media.sh SOURCE_DIR OUTPUT_DIR
#
# Video streams: 1280x720, 25 frames/s, 5 seconds, a moving test pattern with
# the marker blocks the launcher looks for in a capture of the display (the
# four corners as in target/src/emugfx.c, and one at the top centre whose
# colour names the video codec). Each video codec is encoded once and then
# packed, unchanged, into each container.
#
# Audio: a sine tone whose pitch names the audio codec, so that a recording
# on the host tells which stream it came from. The HE-AAC tone is a file in
# the repository (heaac-1100hz.aac): no encoder in Debian produces HE-AAC.
# It was made with the Fraunhofer FDK AAC encoder 2.0.3 (fdkaac 1.0.6):
#   ffmpeg -f lavfi -i sine=frequency=1100:sample_rate=48000:duration=30 -af volume=-6dB -ac 2 tone.wav
#   fdkaac -p 5 -b 48000 -f 2 -o heaac-1100hz.aac tone.wav
#
# The streams are part of the workload's method: change them, and the
# workload's version (target/rootfs/opt/emu/workloads/media-decode) changes.
set -eu
src=$1 out=$2
work=$(mktemp -d)
mkdir -p "$out"
ff() { ffmpeg -nostdin -hide_banner -v error -y -fflags +bitexact "$@"; }

SIZE=1280x720 RATE=25 SECONDS=5 BLOCK=60
pattern() {     # pattern MARKER_COLOUR
  printf '%s' "testsrc2=size=$SIZE:rate=$RATE,"
  printf '%s' "drawbox=0:0:$BLOCK:$BLOCK:0xFF0000:fill,drawbox=iw-$BLOCK:0:$BLOCK:$BLOCK:0x00FF00:fill,"
  printf '%s' "drawbox=0:ih-$BLOCK:$BLOCK:$BLOCK:0x0000FF:fill,drawbox=iw-$BLOCK:ih-$BLOCK:$BLOCK:$BLOCK:0xFFFFFF:fill,"
  printf '%s' "drawbox=(iw-$BLOCK)/2:0:$BLOCK:$BLOCK:$1:fill,"
  printf '%s' "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"
}
tone() { printf 'sine=frequency=%s:sample_rate=48000,volume=-6dB' "$1"; }
COLOUR="-colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv"

# One encode per video codec, with its audio, into a holding file.
ff -f lavfi -i "$(pattern 0xFF8000)" -f lavfi -i "$(tone 440)" -t $SECONDS \
   -c:v mpeg2video -b:v 5M -maxrate 8M -bufsize 4M -g 12 -bf 2 $COLOUR -ac 2 -c:a mp2 -b:a 192k "$work/mpeg2.mkv"
ff -f lavfi -i "$(pattern 0x00C8FF)" -f lavfi -i "$(tone 880)" -t $SECONDS \
   -c:v libx264 -preset medium -profile:v high -b:v 2500k -g 25 -bf 2 -threads 1 $COLOUR -ac 2 -c:a aac -b:a 128k "$work/avc.mkv"
ff -f lavfi -i "$(pattern 0xC800FF)" -f lavfi -i "$(tone 660)" -t $SECONDS \
   -c:v libx265 -preset medium -b:v 1500k -g 25 -x265-params "log-level=none:pools=none:frame-threads=1" \
   $COLOUR -ac 2 -c:a ac3 -b:a 192k "$work/hevc.mkv"

# The same streams in each container.
for codec in mpeg2 avc hevc; do
  tag=""
  [ "$codec" = hevc ] && tag="-tag:v hvc1"
  ff -i "$work/$codec.mkv" -c copy -f mpegts "$out/$codec.ts"
  ff -i "$work/$codec.mkv" -c copy $tag -movflags +faststart "$out/$codec.mp4"
  # Fragmented MP4: an initialisation segment and one media fragment per
  # second, split into separate files for MSE-style injection.
  ff -i "$work/$codec.mkv" -c copy $tag -movflags +frag_keyframe+delay_moov+default_base_moof -f mp4 "$work/$codec.fmp4"
  python3 "$src/split-fragments.py" "$work/$codec.fmp4" "$out/$codec-fragments"
done

# Audio-only streams, 30 seconds each.
ff -f lavfi -i "$(tone 440)" -t 30 -ac 2 -c:a mp2 -b:a 192k -f mpegts "$out/audio-mp2.ts"
ff -f lavfi -i "$(tone 660)" -t 30 -ac 2 -c:a ac3 -b:a 192k -f mpegts "$out/audio-ac3.ts"
ff -f lavfi -i "$(tone 880)" -t 30 -ac 2 -c:a aac -b:a 128k "$out/audio-aac.mp4"
ff -i "$src/heaac-1100hz.aac" -c copy -bsf:a aac_adtstoasc "$out/audio-heaac.mp4"
ff -i "$src/heaac-1100hz.aac" -c copy -f mpegts "$out/audio-heaac.ts"

python3 "$src/describe-media.py" "$out" > "$out/manifest.json"
rm -rf "$work"
ls -l "$out"
