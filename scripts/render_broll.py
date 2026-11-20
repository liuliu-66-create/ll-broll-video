"""Render a validated four-by-four B-roll sheet or join rendered clips."""
import argparse
from fractions import Fraction
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from PIL import Image, ImageOps, UnidentifiedImageError


CANVASES = {"3:4": (1080, 1440), "4:3": (1440, 1080), "16:9": (1920, 1080)}
FRAME_COUNT = 16
TIMESCALE = 16000


def ffmpeg(*args, cwd=None):
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", *args],
        cwd=cwd,
        check=True,
    )


def verify_clip(path, size, frame_count):
    result = subprocess.check_output(
        ["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-of", "json", path],
        text=True,
    )
    streams = json.loads(result)["streams"]
    if len(streams) != 1 or streams[0]["codec_type"] != "video":
        raise ValueError(f"{path.name} must have exactly one video stream and no audio")
    video = streams[0]
    if (
        (video["width"], video["height"]) != size
        or video.get("sample_aspect_ratio") != "1:1"
        or int(video.get("nb_read_frames", 0)) != frame_count
    ):
        raise ValueError(f"Unexpected size, pixel aspect ratio, or frame count in {path.name}")
    return int(video["duration_ts"]) * Fraction(video["time_base"])


def split_sheet(path, directory, size):
    with Image.open(path) as image:
        if image.format != "PNG" or getattr(image, "n_frames", 1) != 1:
            raise ValueError("Use a single static PNG sheet")
        pixels = ImageOps.exif_transpose(image).convert("RGBA")

    width, height = pixels.size
    requested_ratio = size[0] / size[1]
    if min(width, height) < 4 or abs((width / height) / requested_ratio - 1) > 0.15:
        raise ValueError("Sheet dimensions are too far from the confirmed aspect ratio")

    directory.mkdir()
    for row in range(4):
        for column in range(4):
            cell = pixels.crop((
                round(column * width / 4),
                round(row * height / 4),
                round((column + 1) * width / 4),
                round((row + 1) * height / 4),
            ))
            background = Image.new("RGBA", cell.size, "white")
            background.alpha_composite(cell)
            frame = ImageOps.pad(
                background.convert("RGB"), size, Image.Resampling.LANCZOS, color="white"
            )
            frame.save(directory / f"{row * 4 + column + 1:02}.png")


def render(args):
    output = args.output_dir.resolve()
    if output.exists():
        raise ValueError(f"Choose a new output directory: {output}")
    if args.duration_ms < 320:
        raise ValueError("Duration must be at least 320 ms for a 16-frame GIF")
    size = CANVASES[args.ratio]
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".broll-") as temp:
        scene = Path(temp) / "scene"
        scene.mkdir()
        shutil.copyfile(args.sheet, scene / "sheet.png")
        split_sheet(scene / "sheet.png", scene / "frames", size)

        # The MP4 timescale gives each frame exactly duration_ms ticks.
        ffmpeg(
            "-framerate", f"{TIMESCALE}/{args.duration_ms}", "-start_number", "1",
            "-i", "frames/%02d.png", "-vf", "setsar=1", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "-bf", "0", "-crf", "17", "-an",
            "-video_track_timescale", str(TIMESCALE), "-movflags", "+faststart",
            "clip.mp4", cwd=scene,
        )
        duration = verify_clip(scene / "clip.mp4", size, FRAME_COUNT)
        if duration != Fraction(args.duration_ms, 1000):
            raise ValueError(f"Unexpected MP4 duration: {float(duration):.3f} s")

        # GIF delay is stored in hundredths of a second.
        delay = (args.duration_ms + 80) // 160
        preview_size = (size[0] // 3, size[1] // 3)
        ffmpeg(
            "-framerate", f"100/{delay}", "-start_number", "1", "-i", "frames/%02d.png",
            "-filter_complex_threads", "1", "-filter_complex",
            f"scale={preview_size[0]}:{preview_size[1]}:flags=lanczos,split[a][b];"
            "[a]palettegen[p];[b][p]paletteuse=dither=none",
            "-gifflags", "0", "-loop", "0", "-final_delay", str(delay),
            "preview.gif", cwd=scene,
        )
        with Image.open(scene / "preview.gif") as gif:
            if gif.size != preview_size:
                raise ValueError("GIF dimensions do not match the confirmed aspect ratio")
            if gif.n_frames != FRAME_COUNT or gif.info.get("loop") != 0:
                raise ValueError("GIF must loop and retain all 16 frames")
            for index in range(FRAME_COUNT):
                gif.seek(index)
                gif.load()
                if gif.info.get("duration") != delay * 10:
                    raise ValueError(f"Unexpected GIF delay at frame {index + 1}")

        scene.rename(output)

    print(f"{args.ratio} | 16 frames | MP4 {args.duration_ms} ms | GIF {delay * 160} ms")
    print(output)


def join(args):
    output = args.output.resolve()
    if output.suffix.lower() != ".mp4" or output.exists():
        raise ValueError("Choose a new .mp4 output path")
    size = CANVASES[args.ratio]
    if len(args.clips) < 2:
        raise ValueError("Supply at least two rendered clips")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".broll-") as temp:
        directory = Path(temp)
        lines = ["ffconcat version 1.0"]
        duration = Fraction(0)
        for index, clip in enumerate(args.clips, start=1):
            clip_duration = verify_clip(clip, size, FRAME_COUNT)
            duration += clip_duration
            name = f"clip-{index:03}.mp4"
            shutil.copyfile(clip, directory / name)
            lines += [f"file {name}", f"duration {float(clip_duration):.6f}"]

        (directory / "scenes.ffconcat").write_text("\n".join(lines) + "\n", encoding="ascii")
        ffmpeg(
            "-f", "concat", "-i", "scenes.ffconcat", "-c", "copy",
            "-video_track_timescale", str(TIMESCALE), "-movflags", "+faststart",
            "combined.mp4", cwd=directory,
        )
        combined = directory / "combined.mp4"
        frame_count = FRAME_COUNT * len(args.clips)
        if verify_clip(combined, size, frame_count) != duration:
            raise ValueError("Combined duration does not match the sum of the clips")
        combined.rename(output)

    print(f"{args.ratio} | {frame_count} frames | MP4 {float(duration):.3f} s")
    print(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    render_parser = commands.add_parser("render")
    render_parser.add_argument("--sheet", type=Path, required=True)
    render_parser.add_argument("--ratio", choices=CANVASES, required=True)
    render_parser.add_argument("--duration-ms", type=int, required=True)
    render_parser.add_argument("--output-dir", type=Path, required=True)
    render_parser.set_defaults(action=render)

    join_parser = commands.add_parser("join")
    join_parser.add_argument("--ratio", choices=CANVASES, required=True)
    join_parser.add_argument("--output", type=Path, required=True)
    join_parser.add_argument("clips", type=Path, nargs="+")
    join_parser.set_defaults(action=join)

    args = parser.parse_args()
    try:
        args.action(args)
    except (OSError, UnidentifiedImageError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()