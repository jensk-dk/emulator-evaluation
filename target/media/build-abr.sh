#!/bin/sh
# Builds the adaptive bitrate (ABR) title that the STB simulator's video on
# demand application has on the device itself. Used by target/Dockerfile, in
# the stage that builds the reference streams.
#   build-abr.sh OUTPUT_DIR
#
# An MPEG-DASH presentation: 20 seconds of a moving test pattern at 25
# frames/s, as AVC in three representations of rising size and bit rate, and
# one AAC audio track (a 523 Hz tone). Segments are two seconds long, each
# starting with a key frame, so the player can change representation at every
# segment.
#
#   representation   size       video bit rate   marker
#   0                426x240    250 kbit/s       yellow   (255, 224, 0)
#   1                854x480    800 kbit/s       green    (0, 224, 160)
#   2                1280x720   2000 kbit/s      pink     (255, 64, 160)
#
# Each has the marker blocks of the reference streams in its corners, and one
# at the top centre whose colour names the representation: a capture of the
# display tells which one the player shows.
set -eu
out=$1
mkdir -p "$out"
ff() { ffmpeg -nostdin -hide_banner -v error -y -fflags +bitexact "$@"; }

RATE=25 SECONDS=20
# rendition WIDTH HEIGHT BLOCK MARKER_COLOUR, from the input pad [vN] to [oN]
rendition() {
  printf '%s' "scale=$1:$2:flags=bicubic,"
  printf '%s' "drawbox=0:0:$3:$3:0xFF0000:fill,drawbox=iw-$3:0:$3:$3:0x00FF00:fill,"
  printf '%s' "drawbox=0:ih-$3:$3:$3:0x0000FF:fill,drawbox=iw-$3:ih-$3:$3:$3:0xFFFFFF:fill,"
  printf '%s' "drawbox=(iw-$3)/2:0:$3:$3:$4:fill,"
  printf '%s' "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"
}
COLOUR="-colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv"
X264="-c:v libx264 -preset medium -profile:v high -g 50 -keyint_min 50 -sc_threshold 0 -bf 2 -threads 1"

ff -f lavfi -i "testsrc2=size=1280x720:rate=$RATE" -f lavfi -i "sine=frequency=523:sample_rate=48000,volume=-6dB" \
   -t $SECONDS -filter_complex \
   "[0:v]split=3[v0][v1][v2];[v0]$(rendition 426 240 20 0xFFE000)[o0];[v1]$(rendition 854 480 40 0x00E0A0)[o1];[v2]$(rendition 1280 720 60 0xFF40A0)[o2]" \
   -map "[o0]" -map "[o1]" -map "[o2]" -map 1:a \
   $X264 $COLOUR \
   -b:v:0 250k -maxrate:v:0 300k -bufsize:v:0 500k \
   -b:v:1 800k -maxrate:v:1 960k -bufsize:v:1 1600k \
   -b:v:2 2000k -maxrate:v:2 2400k -bufsize:v:2 4000k \
   -ac 2 -c:a aac -b:a 96k \
   -f dash -seg_duration 2 -use_template 1 -use_timeline 0 \
   -init_seg_name 'init-$RepresentationID$.m4s' -media_seg_name 'seg-$RepresentationID$-$Number%05d$.m4s' \
   -adaptation_sets "id=0,streams=v id=1,streams=a" "$out/manifest.mpd"
ls -l "$out"
