#!/usr/bin/env python3
"""Write the manifest of the reference streams: what each one is, and the
SHA-256 of its bytes, so a result can name exactly what was decoded.

    describe-media.py MEDIA_DIR > manifest.json
"""
import hashlib
import json
import os
import subprocess
import sys

VIDEO = {  # codec: (ffmpeg's name for it, marker colour at the top centre, the audio that goes with it)
    "mpeg2": ("mpeg2video", [255, 128, 0], "mp2"),
    "avc": ("h264", [0, 200, 255], "aac"),
    "hevc": ("hevc", [200, 0, 255], "ac3"),
}
TONE_HZ = {"mp2": 440, "ac3": 660, "aac": 880, "heaac": 1100}
AUDIO_ONLY = [("audio-mp2.ts", "mp2", "mp2ts"), ("audio-ac3.ts", "ac3", "mp2ts"), ("audio-aac.mp4", "aac", "mp4"),
              ("audio-heaac.mp4", "heaac", "mp4"), ("audio-heaac.ts", "heaac", "mp2ts")]


def digest(paths):
    found = hashlib.sha256()
    size = 0
    for path in paths:
        with open(path, "rb") as handle:
            data = handle.read()
        found.update(data)
        size += len(data)
    return found.hexdigest(), size


def probe(path):
    done = subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-show_entries",
                           "stream=codec_type,codec_name,profile,width,height,nb_read_packets,sample_rate,channels"
                           ":format=duration", "-of", "json", path], capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


def main():
    root = sys.argv[1]
    streams = []
    for codec, (name, marker, audio) in VIDEO.items():
        for container, source in (("mp2ts", codec + ".ts"), ("mp4", codec + ".mp4"),
                                  ("fragments", codec + "-fragments")):
            entry = {"id": "%s-%s" % (codec, container), "container": container}
            if container == "fragments":
                directory = os.path.join(root, source)
                parts = ["init.mp4"] + sorted(p for p in os.listdir(directory) if p.startswith("fragment-"))
                entry["fragments"] = {"directory": source, "init": parts[0], "media": parts[1:]}
                paths = [os.path.join(directory, part) for part in parts]
                # Probe the fragments as a player gets them: appended to one another.
                joined = os.path.join(root, ".joined.mp4")
                with open(joined, "wb") as handle:
                    for path in paths:
                        with open(path, "rb") as part:
                            handle.write(part.read())
                info = probe(joined)
                os.unlink(joined)
            else:
                entry["file"] = source
                paths = [os.path.join(root, source)]
                info = probe(paths[0])
            video = next(s for s in info["streams"] if s["codec_type"] == "video")
            sound = next(s for s in info["streams"] if s["codec_type"] == "audio")
            assert video["codec_name"] == name, (source, video["codec_name"])
            entry["video"] = {"codec": codec, "width": video["width"], "height": video["height"], "fps": 25,
                              "frames": int(video["nb_read_packets"]), "marker": marker}
            entry["audio"] = {"codec": audio, "hz": TONE_HZ[audio], "sample_rate": int(sound["sample_rate"]),
                              "channels": sound["channels"]}
            entry["seconds"] = entry["video"]["frames"] / 25
            entry["sha256"], entry["bytes"] = digest(paths)
            streams.append(entry)
    for source, audio, container in AUDIO_ONLY:
        path = os.path.join(root, source)
        info = probe(path)
        sound = next(s for s in info["streams"] if s["codec_type"] == "audio")
        entry = {"id": os.path.splitext(source)[0] + "-" + container, "container": container, "file": source,
                 "audio": {"codec": audio, "hz": TONE_HZ[audio], "sample_rate": int(sound["sample_rate"]),
                           "channels": sound["channels"], "profile": sound.get("profile")},
                 "seconds": round(float(info["format"]["duration"]), 2)}
        entry["sha256"], entry["bytes"] = digest([path])
        streams.append(entry)
    json.dump({"streams": streams}, sys.stdout, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
