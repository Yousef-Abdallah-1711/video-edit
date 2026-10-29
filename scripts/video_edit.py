#!/usr/bin/env python3
"""Prepare review artifacts and render a reviewed video edit plan with FFmpeg."""

from __future__ import annotations

import argparse
import math
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


SKILL_DIR = Path(__file__).resolve().parent.parent
INTRO_ASSET = SKILL_DIR / "assets" / "payment_gateway_intro.mp4"


def run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"Required executable was not found: {command[0]}. Install FFmpeg (ffmpeg and ffprobe) and retry.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise RuntimeError(f"Command failed ({exc.returncode}): {command[0]}\n{detail[-3000:]}") from exc


def probe(path: Path) -> dict[str, Any]:
    result = run(
        [
            "ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)
        ],
        capture=True,
    )
    return json.loads(result.stdout)


def media_duration(info: dict[str, Any]) -> float:
    return float(info.get("format", {}).get("duration", 0))


def detect_silence(source: Path, threshold: str, minimum: float) -> list[dict[str, float]]:
    result = run(
        [
            "ffmpeg", "-hide_banner", "-i", str(source), "-vn", "-af",
            f"silencedetect=noise={threshold}dB:d={minimum:.3f}", "-f", "null", "-",
        ],
        capture=True,
    )
    log = result.stderr or ""
    starts = [float(value) for value in re.findall(r"silence_start:\s*([0-9.]+)", log)]
    ends = [float(value) for value in re.findall(r"silence_end:\s*([0-9.]+)", log)]
    spans: list[dict[str, float]] = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else media_duration(probe(source))
        if end > start:
            spans.append({"start": round(start, 3), "end": round(end, 3), "duration": round(end - start, 3)})
    return spans


def extract_audio(source: Path, target: Path) -> None:
    run(["ffmpeg", "-y", "-hide_banner", "-i", str(source), "-vn", "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(target)])


def create_title_card(args: argparse.Namespace) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
        import arabic_reshaper
        from bidi.algorithm import get_display
    except ImportError as exc:
        raise RuntimeError("Creating a shaped Arabic title card requires Pillow, arabic-reshaper, and python-bidi.") from exc
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    image_path = output.with_suffix(".png")
    image = Image.new("RGB", (2560, 1440), "#101923")
    draw = ImageDraw.Draw(image)
    draw.ellipse((1930, -420, 2860, 510), fill="#142D3C")
    draw.ellipse((-400, 1050, 400, 1850), fill="#142D3C")
    draw.rounded_rectangle((220, 355, 2340, 1090), radius=36, fill="#121F2B", outline="#263B4A", width=3)
    draw.rounded_rectangle((1160, 472, 1400, 484), radius=6, fill="#23C6B7")
    font_path = args.font or r"C:\Windows\Fonts\arial.ttf"
    if not Path(font_path).is_file():
        font_path = r"C:\Windows\Fonts\segoeui.ttf"
    def shaped(text: str) -> str:
        return get_display(arabic_reshaper.reshape(text))
    title_font = ImageFont.truetype(font_path, 88)
    subtitle_font = ImageFont.truetype(font_path, 48)
    kicker_font = ImageFont.truetype(font_path, 34)
    kicker = shaped("درس تطبيقي | SEO")
    title = shaped(args.title)
    subtitle = shaped(args.subtitle) if args.subtitle else ""
    draw.text((1280, 580), kicker, font=kicker_font, fill="#70D9D0", anchor="mm")
    draw.text((1280, 730), title, font=title_font, fill="#FFFFFF", anchor="mm")
    if subtitle:
        draw.text((1280, 865), subtitle, font=subtitle_font, fill="#CBD5DF", anchor="mm")
    image.save(image_path)
    source = Path(args.audio_from).expanduser().resolve() if args.audio_from else None
    if source is None:
        run(["ffmpeg", "-y", "-hide_banner", "-loop", "1", "-framerate", "30", "-i", str(image_path), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{args.duration:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-shortest", str(output)])
    else:
        run(["ffmpeg", "-y", "-hide_banner", "-loop", "1", "-framerate", "30", "-i", str(image_path), "-i", str(source), "-filter_complex", f"[1:a]atrim=start={args.audio_start:.3f}:duration={args.duration:.3f},asetpts=PTS-STARTPTS[a]", "-map", "0:v:0", "-map", "[a]", "-t", f"{args.duration:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-shortest", str(output)])
    print(json.dumps({"title_card": str(output), "still": str(image_path), "duration": args.duration, "audio_source": str(source) if source else None}, ensure_ascii=False, indent=2))


def make_samples(source: Path, directory: Path, duration: float, interval: float) -> list[str]:
    directory.mkdir(parents=True, exist_ok=True)
    times = sorted(set([0.5, max(0.5, duration - 0.5)] + [t for t in range(int(interval), int(duration), int(interval))]))
    outputs: list[str] = []
    for index, timestamp in enumerate(times):
        target = directory / f"frame_{index:04d}_{timestamp:09.2f}s.jpg"
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{timestamp:.3f}", "-i", str(source), "-frames:v", "1", "-q:v", "3", str(target)])
        outputs.append(str(target))
    return outputs


def prepare(args: argparse.Namespace) -> None:
    source = Path(args.source).expanduser().resolve()
    if not source.is_file():
        raise RuntimeError(f"Source video does not exist: {source}")
    info = probe(source)
    streams = info.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if video is None:
        raise RuntimeError("The supplied source has no video stream.")
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    duration = media_duration(info)
    workdir = source.parent / f"{source.stem}_edit"
    workdir.mkdir(parents=True, exist_ok=True)
    samples = make_samples(source, workdir / "review_frames", duration, args.sample_interval)
    extracted = None
    silences: list[dict[str, float]] = []
    if audio:
        extracted_path = workdir / f"{source.stem}_source_audio.mp3"
        extract_audio(source, extracted_path)
        extracted = str(extracted_path)
        silences = detect_silence(source, args.silence_threshold, args.silence_seconds)
    plan = {
        "source": str(source),
        "source_duration": round(duration, 6),
        "source_video": {key: video.get(key) for key in ("codec_name", "width", "height", "r_frame_rate")},
        "source_audio": {key: audio.get(key) for key in ("codec_name", "sample_rate", "channels")} if audio else None,
        "review_audio": extracted,
        "review_frames": samples,
        "silence_detector": {"threshold_db": args.silence_threshold, "minimum_seconds": args.silence_seconds, "retain_edge_seconds": 0.18},
        "detected_silences": silences,
        "cuts": [],
        "freezes": [],
        "crop": None,
        "mask_regions": [],
        "use_intro": False,
        "custom_intro": None,
        "chapters_srt": None,
        "notes": "AI/editor: review speech and images; classify live workshop logistics separately from technical sessions; add only justified source-time cuts/freezes. Silence detections are candidates, not automatic edit decisions.",
    }
    plan_path = workdir / f"{source.stem}_edit_plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"plan": str(plan_path), "review_audio": extracted, "review_frames": samples, "silence_candidates": len(silences), "duration_seconds": round(duration, 3)}, ensure_ascii=False, indent=2))


def merged_cuts(plan: dict[str, Any], duration: float) -> list[tuple[float, float]]:
    cuts: list[tuple[float, float]] = []
    for item in plan.get("cuts", []):
        start, end = float(item["start"]), float(item["end"])
        if start < 0 or end <= start or end > duration + 0.05:
            raise RuntimeError(f"Invalid source-time cut: {item}")
        cuts.append((max(0.0, start), min(duration, end)))
    cuts.sort()
    merged: list[list[float]] = []
    for start, end in cuts:
        if merged and start <= merged[-1][1] + 0.04:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def kept_ranges(duration: float, cuts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    kept: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in cuts:
        if start > cursor + 0.01:
            kept.append((cursor, start))
        cursor = max(cursor, end)
    if duration > cursor + 0.01:
        kept.append((cursor, duration))
    if not kept:
        raise RuntimeError("The edit plan removes the entire source.")
    return kept


def map_source_time(timestamp: float, kept: list[tuple[float, float]]) -> float:
    elapsed = 0.0
    for start, end in kept:
        if start <= timestamp <= end:
            return elapsed + max(0.0, timestamp - start)
        elapsed += end - start
    raise RuntimeError(f"A freeze span falls inside a removed section: source time {timestamp:.3f}s")


def video_shape_filter(crop: dict[str, int] | None, input_label: str, output_label: str) -> str:
    if crop:
        x, y, width, height = (int(crop[key]) for key in ("x", "y", "width", "height"))
        if min(x, y) < 0 or min(width, height) <= 0:
            raise RuntimeError(f"Invalid crop configuration: {crop}")
        base = f"crop={width}:{height}:{x}:{y},scale=2560:1440:flags=lanczos"
    else:
        base = "scale=2560:1440:force_original_aspect_ratio=decrease:flags=lanczos,pad=2560:1440:(ow-iw)/2:(oh-ih)/2:color=black"
    return f"[{input_label}]{base},fps=30,setsar=1[{output_label}]"


def timecode(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    remainder = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{remainder:06.3f}"


def write_kdenlive(source: Path, video_stream: dict[str, Any], kept: list[tuple[float, float]], body_duration: float, workdir: Path, intro: Path | None = None) -> Path | None:
    template = SKILL_DIR / "assets" / "payment_gateway_template.kdenlive"
    if not template.is_file():
        return None
    tree = ET.parse(template)
    root = tree.getroot()
    root.set("root", str(source.parent))
    width, height = 2560, 1440
    profile = root.find("profile")
    if profile is not None:
        profile.set("width", str(width))
        profile.set("height", str(height))
        profile.set("display_aspect_num", "16")
        profile.set("display_aspect_den", "9")
        profile.set("frame_rate_num", "30")
        profile.set("frame_rate_den", "1")
        profile.set("description", f"{source.stem} course edit {width}x{height} 30 fps")
    for chain in root.findall("chain"):
        for prop in chain.findall("property[@name='resource']"):
            prop.text = source.name
    intro_duration = media_duration(probe(intro)) if intro else 0.0
    for producer in root.findall("producer"):
        for prop in producer.findall("property[@name='length']"):
            prop.text = timecode(body_duration + intro_duration)
    for playlist_id in ("playlist0", "playlist2"):
        playlist = root.find(f"playlist[@id='{playlist_id}']")
        if playlist is None:
            continue
        for child in list(playlist):
            if child.tag in ("entry", "blank"):
                playlist.remove(child)
        if intro:
            intro_entry = ET.SubElement(playlist, "entry", {"producer": "chain2", "in": "00:00:00.000", "out": timecode(max(0.0, intro_duration - 1 / 30))})
            ET.SubElement(intro_entry, "property", {"name": "kdenlive:id"}).text = "5"
        chain_id = "chain0" if playlist_id == "playlist0" else "chain1"
        for start, end in kept:
            entry = ET.SubElement(playlist, "entry", {"producer": chain_id, "in": timecode(start), "out": timecode(max(start, end - 1 / 30))})
            ET.SubElement(entry, "property", {"name": "kdenlive:id"}).text = "4"
    for tractor in root.findall("tractor"):
        if tractor.get("out") is not None:
            tractor.set("out", timecode(max(0.0, body_duration + intro_duration - 1 / 30)))
    project_tractor = root.find("tractor[@id='tractor2']")
    if project_tractor is not None:
        track = project_tractor.find("track")
        if track is not None:
            track.set("out", timecode(max(0.0, body_duration + intro_duration - 1 / 30)))
    if intro:
        intro_chain = root.find("chain[@id='chain2']")
        if intro_chain is not None:
            resource = intro_chain.find("property[@name='resource']")
            if resource is not None:
                resource.text = str(intro)
    target = workdir / f"{source.stem}_edit.kdenlive"
    tree.write(target, encoding="utf-8", xml_declaration=True)
    return target


def render(args: argparse.Namespace) -> None:
    plan_path = Path(args.plan).expanduser().resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    source = Path(plan["source"]).expanduser().resolve()
    source_info = probe(source)
    source_duration = media_duration(source_info)
    has_source_audio = any(stream.get("codec_type") == "audio" for stream in source_info.get("streams", []))
    enhanced = Path(args.enhanced_audio).expanduser().resolve() if args.enhanced_audio else None
    if not has_source_audio and not enhanced:
        raise RuntimeError("The source has no audio stream to edit. Add a source audio track before rendering.")
    cuts = merged_cuts(plan, source_duration)
    kept = kept_ranges(source_duration, cuts)
    body_duration = sum(end - start for start, end in kept)
    workdir = plan_path.parent
    output = Path(args.output).expanduser().resolve() if args.output else workdir / f"{source.stem}_final.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    custom_intro = Path(args.intro_video).expanduser().resolve() if args.intro_video else (Path(plan["custom_intro"]).expanduser().resolve() if plan.get("custom_intro") else None)
    use_intro = not args.no_intro and (custom_intro is not None or bool(plan.get("use_intro", False)))
    intro = None if args.no_intro else (custom_intro if custom_intro is not None else (INTRO_ASSET if use_intro else None))
    if intro is not None and not intro.is_file():
        raise RuntimeError(f"Intro video does not exist: {intro}")
    intro_duration = media_duration(probe(intro)) if intro else 0.0
    expected_duration = intro_duration + body_duration
    if enhanced:
        audio_duration = media_duration(probe(enhanced))
        if abs(audio_duration - expected_duration) > args.audio_tolerance:
            raise RuntimeError(
                f"Enhanced audio duration ({audio_duration:.3f}s) differs from edited video timeline "
                f"({expected_duration:.3f}s) by more than {args.audio_tolerance:.2f}s. Align it first; no export was made."
            )

    filter_path = output.parent / f"{output.stem}_render_filter.txt"
    source_index = 1 if intro else 0
    command = ["ffmpeg", "-y", "-hide_banner"]
    if intro:
        command += ["-i", str(intro)]
    command += ["-i", str(source)]
    graph: list[str] = []
    for index, (start, end) in enumerate(kept):
        graph.append(f"[{source_index}:v]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS[v{index}]")
        current_video = f"v{index}"
        for mask_index, mask in enumerate(plan.get("mask_regions", [])):
            x, y, width, height = (int(mask[key]) for key in ("x", "y", "width", "height"))
            source_width = int(next(stream for stream in source_info["streams"] if stream.get("codec_type") == "video").get("width", 0))
            source_height = int(next(stream for stream in source_info["streams"] if stream.get("codec_type") == "video").get("height", 0))
            if min(x, y) < 0 or min(width, height) <= 0 or x + width > source_width or y + height > source_height:
                raise RuntimeError(f"Invalid mask region: {mask}")
            base_label, mask_source, blurred_label, masked_label = (f"v{index}_{mask_index}_{suffix}" for suffix in ("base", "src", "blur", "masked"))
            graph.append(f"[{current_video}]split[{base_label}][{mask_source}]")
            graph.append(f"[{mask_source}]crop={width}:{height}:{x}:{y},boxblur=6:2[{blurred_label}]")
            graph.append(f"[{base_label}][{blurred_label}]overlay={x}:{y}:shortest=1[{masked_label}]")
            current_video = masked_label
        graph.append(video_shape_filter(plan.get("crop"), current_video, f"vkeep{index}"))
        if not enhanced and has_source_audio:
            graph.append(f"[{source_index}:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS[a{index}]")
    if enhanced or not has_source_audio:
        video_inputs = "".join(f"[vkeep{i}]" for i in range(len(kept)))
        graph.append(f"{video_inputs}concat=n={len(kept)}:v=1:a=0[bodyv]")
    else:
        concat_inputs = "".join(f"[vkeep{i}][a{i}]" for i in range(len(kept)))
        graph.append(f"{concat_inputs}concat=n={len(kept)}:v=1:a=1[bodyv][bodya]")

    freeze_inputs: list[tuple[int, float, float]] = []
    for index, freeze in enumerate(plan.get("freezes", [])):
        start, end, frame_time = float(freeze["start"]), float(freeze["end"]), float(freeze["frame_time"])
        if end <= start or frame_time < 0 or frame_time >= source_duration:
            raise RuntimeError(f"Invalid freeze entry: {freeze}")
        edit_start, edit_end = map_source_time(start, kept), map_source_time(end, kept)
        image = workdir / f"freeze_{index:02d}.jpg"
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{frame_time:.3f}", "-i", str(source), "-frames:v", "1", "-q:v", "2", str(image)])
        input_index = source_index + 1 + index
        command += ["-loop", "1", "-framerate", "30", "-t", f"{body_duration:.6f}", "-i", str(image)]
        freeze_inputs.append((input_index, edit_start, edit_end))
    body_label = "bodyv"
    for index, (input_index, start, end) in enumerate(freeze_inputs):
        freeze_scaled = f"freeze_scaled{index}"
        graph.append(video_shape_filter(plan.get("crop"), f"{input_index}:v", freeze_scaled))
        next_label = f"bodyfreeze{index}"
        graph.append(f"[{body_label}][{freeze_scaled}]overlay=0:0:shortest=1:enable='between(t,{start:.6f},{end:.6f})'[{next_label}]")
        body_label = next_label

    chapters_srt = Path(args.chapters_srt).expanduser().resolve() if args.chapters_srt else (Path(plan["chapters_srt"]).expanduser().resolve() if plan.get("chapters_srt") else None)
    if chapters_srt is not None:
        if not chapters_srt.is_file():
            raise RuntimeError(f"Chapter subtitles file does not exist: {chapters_srt}")
        escaped_subtitles = str(chapters_srt).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        style = "FontName=Arial,FontSize=12,PrimaryColour=&H00FFFFFF,OutlineColour=&H00131B27,BorderStyle=3,BackColour=&HCC131B27,Outline=1,Shadow=0,Alignment=2,MarginV=74"
        graph.append(f"[{body_label}]subtitles=filename='{escaped_subtitles}':force_style='{style}'[bodytitled]")
        body_label = "bodytitled"

    if intro:
        graph.append(video_shape_filter(None, "0:v", "intro_v"))
        graph.append(f"[intro_v][{body_label}]concat=n=2:v=1:a=0[vfinal]")
    else:
        graph.append(f"[{body_label}]null[vfinal]")

    if enhanced:
        audio_input_index = source_index + 1 + len(freeze_inputs)
        command += ["-i", str(enhanced)]
        audio_map = f"{audio_input_index}:a:0"
    else:
        if intro:
            graph.append("[0:a][bodya]concat=n=2:v=0:a=1,aresample=48000,loudnorm=I=-16:TP=-1.5:LRA=11[afinal]")
        else:
            graph.append("[bodya]aresample=48000,loudnorm=I=-16:TP=-1.5:LRA=11[afinal]")
        audio_map = "[afinal]"
    filter_path.write_text(";\n".join(graph), encoding="utf-8")
    command += ["-filter_complex_script", str(filter_path), "-map", "[vfinal]", "-map", audio_map]
    command += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "256k" if enhanced else "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", "-shortest", str(output)]
    print(f"Source {source_duration:.2f}s; removed {len(cuts)} merged spans; body {body_duration:.2f}s; intro {intro_duration:.2f}s; rendering {output}", flush=True)
    run(command)
    audio_export = output.parent / f"{output.stem}_audio.mp3"
    extract_audio(output, audio_export)
    project = write_kdenlive(source, next(stream for stream in source_info["streams"] if stream.get("codec_type") == "video"), kept, body_duration, output.parent, intro)
    summary = {
        "source": str(source), "final_video": str(output), "final_audio_mp3": str(audio_export),
        "duration_source": source_duration, "duration_body": body_duration, "duration_intro": intro_duration,
        "duration_expected": expected_duration, "cuts": [{"start": a, "end": b} for a, b in cuts],
        "kept_ranges": [{"start": a, "end": b} for a, b in kept], "crop": plan.get("crop"),
        "custom_intro": str(intro) if intro else None, "chapters_srt": str(chapters_srt) if chapters_srt else None,
        "enhanced_audio": str(enhanced) if enhanced else None, "filter_graph": str(filter_path), "kdenlive_project": str(project) if project else None,
    }
    (output.parent / f"{output.stem}_render_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare review assets and render a reviewed edit plan.")
    subparsers = parser.add_subparsers(dest="action", required=True)
    prep = subparsers.add_parser("prepare", help="Probe a source, extract review audio, detect silences, and create frame samples.")
    prep.add_argument("source")
    prep.add_argument("--sample-interval", type=float, default=45.0)
    prep.add_argument("--silence-threshold", type=float, default=-34.0)
    prep.add_argument("--silence-seconds", type=float, default=3.0)
    prep.set_defaults(func=prepare)
    rend = subparsers.add_parser("render", help="Render an AI-reviewed JSON edit plan.")
    rend.add_argument("plan")
    rend.add_argument("--enhanced-audio")
    rend.add_argument("--no-intro", action="store_true")
    rend.add_argument("--intro-video", help="Override the bundled intro with a custom intro video (including any opening audio).")
    rend.add_argument("--chapters-srt", help="Burn timed chapter callouts from an SRT file onto the edited body.")
    rend.add_argument("--audio-tolerance", type=float, default=1.0)
    rend.add_argument("--output")
    rend.set_defaults(func=render)
    card = subparsers.add_parser("title-card", help="Create a clean Arabic course title card video; optionally carry source opening audio under it.")
    card.add_argument("--output", required=True)
    card.add_argument("--title", required=True)
    card.add_argument("--subtitle", default="")
    card.add_argument("--duration", type=float, default=6.0)
    card.add_argument("--audio-from", help="Source video whose audio will be kept beneath the card.")
    card.add_argument("--audio-start", type=float, default=0.0)
    card.add_argument("--font")
    card.set_defaults(func=create_title_card)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        args.func(args)
    except (RuntimeError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"video-edit: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
