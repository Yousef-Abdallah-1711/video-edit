---
name: video-edit
description: "Edit a supplied tutorial or screen recording end to end: review speech and picture, remove verified repeats and long silences, remove added frames, and export the final video and audio."
---

# Video Edit

Use this skill when the user gives a video path and wants the complete editing workflow used for the payment-gateway tutorial series. The single invocation is `$video-edit <video-path> [enhanced-audio-path]`. Treat the path as the source and complete the review, edit, export, and final checks in that turn. Do not alter the source file.

## Workflow

1. **Inspect the source.** Use `scripts/video_edit.py prepare <video-path>` to probe streams and duration, extract a review MP3, detect candidate silences, create visual samples, and write an edit plan JSON beside the source in a dedicated `<stem>_edit` directory. Review the sample frames and inspect the whole video, not just the beginning. Use an available Arabic/Egyptian Arabic speech transcription capability; preserve English technical terms and timestamps. If no speech transcription tool is available, inspect/listen in manageable chunks and do not pretend silence detection is a transcript.
2. **Build a source-time edit plan.** Update the generated JSON's `cuts` and `freezes` only after reviewing the corresponding speech/picture. Cut exact duplicate lines, abandoned sentence starts, obvious stutters, and filler that contributes nothing. Keep meaningful restatements, lists, examples, and nearby explanations that add new information. Each cut needs a source-time `start`, `end`, and short `reason`. Keep enough handles that the remaining words are natural.
3. **Review long pauses.** Candidate detection defaults to `silencedetect` at `-34 dB` for longer than 3 seconds. Check candidates against speech before cutting: remove long true silence while retaining a short natural pause (about 0.18 seconds at each speech edge). Do not cut quiet speech, breaths needed for cadence, or deliberate pauses. Merge overlapping cuts and verify the final kept intervals cover the whole source except intended removals.
4. **Remove the added frame without damaging the recording.** Do not recreate the cream/red border, header, footer, or chapter bar from the earlier framed version. Inspect the picture and crop only when it removes the added design while keeping important screen content. Browser tabs and the Windows taskbar baked into the source remain part of the screen recording. Leave `crop` null when the full screen matters; the renderer fits the whole source inside 16:9 and adds black bars when aspect ratios differ. Review edge content before accepting a crop.
5. **Repair picture dropouts when justified.** If a section is accidentally black while its narration continues, add a `freezes` entry with its source-time `start`, `end`, and a nearby clean `frame_time`. Do not cover intentional black, transitions, or content that should remain visible.
6. **Use the series intro when appropriate.** The bundled `assets/payment_gateway_intro.mp4` is the 2.5-second course intro. Use it for videos in this course/series. For unrelated content, pass `--no-intro` to render. Never add a decorative frame around the picture.
7. **Render and optional enhanced audio.** Run `scripts/video_edit.py render <edit-plan.json>`. If an enhanced audio file is supplied with the invocation, use `--enhanced-audio <path>`; it must cover the full edited timeline (including intro if present). Compare its duration with the target video before muxing. The renderer preserves the video stream quality by rendering the edit, uses H.264 MP4 at 30 fps / 2560x1440, and encodes audio as 48 kHz stereo AAC. It also exports a standalone 192 kb/s MP3 from the final render. Never silently truncate a mismatched audio track; report the mismatch and resolve alignment from the timeline first.
8. **Make the project reviewable.** Keep the JSON edit plan and generated filter graph next to the exports. If Kdenlive is available, also create an editable project with the same source in/out cuts and source path; the project must match the rendered cut list. Do not claim an editable Kdenlive project exists if it was not created.
9. **Check the exports.** Probe the final MP4 and MP3 with `ffprobe`; confirm video and audio streams, duration, resolution, and audio format. Inspect visual samples at the opening, middle, near the repaired dropout, around representative cuts, and near the end. Listen to the joins where possible. Correct black flashes, bad joins, accidental words lost at cuts, or crop damage, then export again. Report the exact final path and any remaining source-screen UI that is baked into the recording.

## Helper commands

```text
python <skill>/scripts/video_edit.py prepare "D:\path\to\source.mp4"
python <skill>/scripts/video_edit.py render "D:\path\to\source_edit\source_edit_plan.json" [--enhanced-audio "D:\path\to\enhanced.mp3"]
python <skill>/scripts/video_edit.py render "D:\path\to\source_edit\source_edit_plan.json" --no-intro
```

The final video, standalone MP3, review samples, JSON edit plan, and filter graph are written under the source's `<stem>_edit` directory. The original source remains untouched. Use the bundled intro only for this course series; it is not a general-purpose intro.
