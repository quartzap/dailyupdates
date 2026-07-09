from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .config import AppConfig
from .models import Article, DigestResult


def render_podcast_script(digest: DigestResult, config: AppConfig) -> str:
    lines = [
        "Daily GenAI intelligence brief.",
        f"Today there are {digest.total_articles} fresh signals across the tracked areas.",
        "",
    ]

    if digest.top_articles:
        lines.append("First, the top signals.")
        for index, article in enumerate(digest.top_articles[:6], start=1):
            lines.append(_article_audio_line(index, article))
        lines.append("")

    for category_key, label in config.category_labels.items():
        articles = digest.grouped_articles.get(category_key, [])[:3]
        if not articles:
            continue
        lines.append(f"In {label}:")
        for index, article in enumerate(articles, start=1):
            lines.append(_article_audio_line(index, article))
        lines.append("")

    lines.append("That is the brief for today. Open the email links for the full source stories.")
    return "\n".join(lines).strip() + "\n"


def generate_mp3_from_script(
    script_path: Path,
    output_path: Path,
    voice: str = "en-us",
    speed: int = 160,
) -> None:
    espeak_path = shutil.which("espeak-ng") or shutil.which("espeak")
    ffmpeg_path = shutil.which("ffmpeg")
    if not espeak_path:
        raise RuntimeError("espeak-ng or espeak is not installed.")
    if not ffmpeg_path:
        raise RuntimeError("ffmpeg is not installed.")

    wav_path = output_path.with_suffix(".wav")
    subprocess.run(
        [
            espeak_path,
            "-v",
            voice,
            "-s",
            str(speed),
            "-f",
            str(script_path),
            "-w",
            str(wav_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            ffmpeg_path,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(wav_path),
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "64k",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    wav_path.unlink(missing_ok=True)


def _article_audio_line(index: int, article: Article) -> str:
    summary = article.summary.strip() if article.summary else ""
    if summary:
        return f"{index}. {article.title}. {summary}"
    return f"{index}. {article.title}."
