from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig
from .models import Article, DigestResult

HOST_A = "HOST A"
HOST_B = "HOST B"
DIALOGUE_LINE_RE = re.compile(r"^\s*(HOST\s*[AB])\s*:\s*(.+)$", re.IGNORECASE)
TRAILING_SOURCE_RE = re.compile(r"\s+[-\u2013\u2014|]\s+[^-\u2013\u2014|]{2,40}$")

DEFAULT_VOICE_A = "en-US-AndrewMultilingualNeural"
DEFAULT_VOICE_B = "en-US-EmmaMultilingualNeural"
LOGGER = logging.getLogger(__name__)

_TRANSITIONS_LEAD = [
    "First up",
    "Next on the list",
    "Here's one that caught my eye",
    "Moving on",
    "This one's interesting",
    "And then there's this",
    "Another big one",
    "Also worth a mention",
]

_SECTION_HANDOFFS = [
    "Alright, let's switch gears to {label}.",
    "Okay, moving over to {label}.",
    "Now, on the {label} front.",
    "Let's talk {label} for a minute.",
]


@dataclass(slots=True)
class DialogueTurn:
    speaker: str  # HOST_A or HOST_B
    text: str


def clean_title_for_audio(title: str, source: str | None = None) -> str:
    """Strip the trailing ' - Publisher' suffix Google News appends to titles."""
    cleaned = title.strip()
    if source:
        for sep in (" - ", " \u2013 ", " \u2014 ", " | "):
            suffix = f"{sep}{source}"
            if cleaned.lower().endswith(suffix.lower()):
                return cleaned[: -len(suffix)].strip()
    match = TRAILING_SOURCE_RE.search(cleaned)
    if match and len(cleaned) - len(match.group(0)) >= 25:
        return cleaned[: match.start()].strip()
    return cleaned


def build_dialogue(digest: DigestResult, config: AppConfig) -> list[DialogueTurn]:
    """Build a template-based two-host conversation from the digest."""
    weekly_articles = digest.weekly_articles[:8]
    weekly_ids = {article.title_fingerprint for article in weekly_articles}
    top_articles = [a for a in digest.top_articles if a.title_fingerprint not in weekly_ids][:6]
    top_ids = {article.title_fingerprint for article in top_articles}

    is_weekly = bool(weekly_articles)
    edition = "weekly" if is_weekly else "daily"
    seed = digest.generated_at.toordinal()

    turns: list[DialogueTurn] = [
        DialogueTurn(
            HOST_A,
            f"Hey everyone, welcome back to your {edition} GenAI brief. "
            f"We've got {digest.total_articles} fresh signals to walk through today.",
        ),
        DialogueTurn(
            HOST_B,
            "And a good mix as always, from product launches to research and security. "
            "Let's get into it.",
        ),
    ]

    highlight_articles = [] if is_weekly else digest.highlight_articles[:3]
    if highlight_articles:
        highlight_titles = [
            clean_title_for_audio(article.title, article.source) for article in highlight_articles
        ]
        if len(highlight_titles) == 1:
            teaser = highlight_titles[0]
        else:
            teaser = ", ".join(highlight_titles[:-1]) + ", and " + highlight_titles[-1]
        turns.append(
            DialogueTurn(
                HOST_A,
                f"Before we start, a quick look at the week so far. The biggest stories: {teaser}.",
            )
        )
        turns.append(
            DialogueTurn(
                HOST_B,
                "Those are pinned at the top of the email if you want the links. "
                "Okay, on to today's stories.",
            )
        )

    story_index = 0

    def add_story(article: Article, lead: str, follow: str) -> None:
        nonlocal story_index
        title = clean_title_for_audio(article.title, article.source)
        transition = _TRANSITIONS_LEAD[(seed + story_index) % len(_TRANSITIONS_LEAD)]
        lead_text = f"{transition}: {title}."
        if article.source:
            lead_text += f" That's from {article.source}."
        turns.append(DialogueTurn(lead, lead_text))
        summary = _compact_for_audio(article.summary) if article.summary else ""
        if summary and clean_title_for_audio(summary, article.source).rstrip(".").casefold() != title.rstrip(".").casefold():
            turns.append(DialogueTurn(follow, summary))
        story_index += 1

    def speakers_for(index: int) -> tuple[str, str]:
        return (HOST_A, HOST_B) if index % 2 == 0 else (HOST_B, HOST_A)

    if weekly_articles:
        turns.append(
            DialogueTurn(HOST_A, "Since it's Sunday, let's start with the big stories of the week.")
        )
        for article in weekly_articles:
            lead, follow = speakers_for(story_index)
            add_story(article, lead, follow)

    if top_articles:
        opener = (
            "Okay, now on to today's top signals."
            if weekly_articles
            else "Let's start with the top stories."
        )
        turns.append(DialogueTurn(HOST_B if weekly_articles else HOST_A, opener))
        for article in top_articles:
            lead, follow = speakers_for(story_index)
            add_story(article, lead, follow)

    for category_key, label in config.category_labels.items():
        articles = [
            a
            for a in digest.grouped_articles.get(category_key, [])
            if a.title_fingerprint not in top_ids and a.title_fingerprint not in weekly_ids
        ][:3]
        if not articles:
            continue
        handoff = _SECTION_HANDOFFS[(seed + story_index) % len(_SECTION_HANDOFFS)]
        lead, follow = speakers_for(story_index)
        turns.append(DialogueTurn(lead, handoff.format(label=label)))
        for article in articles:
            lead, follow = speakers_for(story_index)
            add_story(article, lead, follow)

    turns.append(
        DialogueTurn(
            HOST_A,
            "And that's the brief. All the source links are in the email if you want to go deeper on anything.",
        )
    )
    turns.append(DialogueTurn(HOST_B, "Thanks for listening. Catch you in the next one."))
    return turns


def render_podcast_script(digest: DigestResult, config: AppConfig) -> str:
    """Render the dialogue as a labelled script.

    If LLM polishing is enabled and succeeds, the polished script is used;
    otherwise the deterministic template dialogue is rendered.
    """
    turns = build_dialogue(digest, config)
    template_script = "\n".join(f"{turn.speaker}: {turn.text}" for turn in turns) + "\n"

    try:
        from .llm_script import polish_dialogue

        polished = polish_dialogue(template_script, digest, config)
    except Exception:
        polished = None
    if polished and parse_dialogue(polished):
        return polished if polished.endswith("\n") else polished + "\n"
    return template_script


def parse_dialogue(script_text: str) -> list[DialogueTurn]:
    turns: list[DialogueTurn] = []
    for raw_line in script_text.splitlines():
        match = DIALOGUE_LINE_RE.match(raw_line)
        if not match:
            continue
        speaker = match.group(1).upper().replace("  ", " ")
        speaker = HOST_A if speaker.endswith("A") else HOST_B
        text = match.group(2).strip()
        if not text:
            continue
        if turns and turns[-1].speaker == speaker:
            turns[-1].text += " " + text
        else:
            turns.append(DialogueTurn(speaker, text))
    return turns


def script_to_plain_text(script_text: str) -> str:
    """Strip speaker labels for single-voice fallback engines."""
    turns = parse_dialogue(script_text)
    if not turns:
        return script_text
    return "\n".join(turn.text for turn in turns) + "\n"


def generate_mp3_from_script(
    script_path: Path,
    output_path: Path,
    voice: str = DEFAULT_VOICE_A,
    voice_b: str = DEFAULT_VOICE_B,
    rate: str = "+0%",
    speed: int = 160,
) -> str:
    text = script_path.read_text(encoding="utf-8")
    turns = parse_dialogue(text)
    try:
        if turns and shutil.which("ffmpeg"):
            _generate_dialogue_with_edge_tts(
                turns, output_path, voice_a=voice, voice_b=voice_b, rate=rate
            )
            return "edge-tts-dialogue"
        _generate_with_edge_tts(script_to_plain_text(text), output_path, voice=voice, rate=rate)
        return "edge-tts"
    except Exception as exc:
        # Exception messages may contain service URLs/tokens; log only the type.
        LOGGER.warning("Edge neural audio unavailable (%s); trying local Piper neural voices.", type(exc).__name__)
        output_path.unlink(missing_ok=True)
        try:
            _generate_with_piper(turns or [DialogueTurn(HOST_A, text)], output_path)
        except Exception as fallback_exc:
            output_path.unlink(missing_ok=True)
            raise RuntimeError(
                "Neural audio unavailable (Edge: " + type(exc).__name__
                + "; Piper: " + type(fallback_exc).__name__
                + "). PDF delivery can continue; no robotic MP3 was substituted."
            ) from None
        return "piper-dialogue"


def _generate_dialogue_with_edge_tts(
    turns: list[DialogueTurn],
    output_path: Path,
    voice_a: str,
    voice_b: str,
    rate: str,
) -> None:
    """Synthesize each turn with the speaker's voice and stitch with ffmpeg."""
    voices = {HOST_A: voice_a, HOST_B: voice_b}

    async def synthesize_all(segment_dir: Path) -> list[Path]:
        paths: list[Path] = []
        for index, turn in enumerate(turns):
            segment_path = segment_dir / f"seg_{index:03d}.mp3"
            await _save_edge_segment(turn.text, segment_path, voices[turn.speaker], rate)
            paths.append(segment_path)
        return paths

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise RuntimeError("ffmpeg is required for dialogue stitching.")

    with tempfile.TemporaryDirectory(prefix="genai-audio-") as tmp:
        segment_dir = Path(tmp)
        segment_paths = asyncio.run(synthesize_all(segment_dir))

        # Short pause between speaker turns, matching edge-tts output params
        # (24 kHz mono mp3) so the concat demuxer accepts it.
        silence_path = segment_dir / "silence.mp3"
        subprocess.run(
            [
                ffmpeg_path, "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                "-t", "0.35", "-codec:a", "libmp3lame", "-b:a", "48k",
                str(silence_path),
            ],
            check=True, capture_output=True, text=True,
        )

        concat_list = segment_dir / "list.txt"
        lines = []
        for index, segment in enumerate(segment_paths):
            lines.append(f"file '{segment.name}'")
            if index < len(segment_paths) - 1:
                lines.append(f"file '{silence_path.name}'")
        concat_list.write_text("\n".join(lines) + "\n", encoding="utf-8")

        subprocess.run(
            [
                ffmpeg_path, "-y", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", str(concat_list),
                "-codec:a", "libmp3lame", "-b:a", "64k", "-ar", "24000", "-ac", "1",
                "-af", "loudnorm=I=-18:TP=-2:LRA=11",
                str(output_path),
            ],
            check=True, capture_output=True, text=True,
        )


def _generate_with_edge_tts(text: str, output_path: Path, voice: str, rate: str) -> str:
    asyncio.run(_save_edge_segment(text, output_path, voice, rate))
    return "edge-tts"


async def _save_edge_segment(text: str, path: Path, voice: str, rate: str) -> None:
    import edge_tts

    for attempt in range(3):
        try:
            await asyncio.wait_for(
                edge_tts.Communicate(text, voice=voice, rate=rate).save(str(path)),
                timeout=45,
            )
            if not path.exists() or path.stat().st_size == 0:
                raise RuntimeError("Empty neural audio segment")
            return
        except Exception as exc:
            path.unlink(missing_ok=True)
            # Authentication/protocol failures do not improve with retries.
            if getattr(exc, "status", None) in {401, 403} or attempt == 2:
                raise
            await asyncio.sleep(2 ** attempt)


def _generate_with_piper(turns: list[DialogueTurn], output_path: Path) -> None:
    """CPU-only neural speech, independent of the Edge online service."""
    from piper import PiperVoice

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required for neural podcast encoding")
    model_dir = Path(os.environ.get("PIPER_MODEL_DIR", "models/piper"))
    voices = {
        HOST_A: PiperVoice.load(str(model_dir / "en_US-ryan-medium.onnx")),
        HOST_B: PiperVoice.load(str(model_dir / "en_US-lessac-medium.onnx")),
    }
    with tempfile.TemporaryDirectory(prefix="genai-piper-") as tmp:
        folder = Path(tmp)
        combined = folder / "dialogue.wav"
        expected_format = None
        with wave.open(str(combined), "wb") as target:
            for index, turn in enumerate(turns):
                segment = folder / "turn.wav"
                with wave.open(str(segment), "wb") as wav:
                    voices[turn.speaker].synthesize_wav(turn.text, wav)
                with wave.open(str(segment), "rb") as wav:
                    audio_format = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate())
                    if expected_format is None:
                        expected_format = audio_format
                        target.setnchannels(audio_format[0])
                        target.setsampwidth(audio_format[1])
                        target.setframerate(audio_format[2])
                    elif audio_format != expected_format:
                        raise RuntimeError("Piper voices must use matching audio formats")
                    target.writeframes(wav.readframes(wav.getnframes()))
                if index < len(turns) - 1:
                    pause = 0.24 if turn.text.endswith("?") else 0.38
                    target.writeframes(b"\x00" * int(audio_format[2] * pause) * audio_format[0] * audio_format[1])
        subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(combined),
             "-af", "loudnorm=I=-18:TP=-2:LRA=11", "-codec:a", "libmp3lame",
             "-b:a", "96k", "-ar", "24000", "-ac", "1", str(output_path)],
            check=True, capture_output=True, timeout=120,
        )


def _compact_for_audio(text: str, max_chars: int = 220) -> str:
    compacted = " ".join(text.split())
    if len(compacted) <= max_chars:
        return compacted
    sentence_end = compacted.rfind(".", 0, max_chars)
    if sentence_end >= 80:
        return compacted[: sentence_end + 1]
    return compacted[:max_chars].rsplit(" ", 1)[0] + "."
