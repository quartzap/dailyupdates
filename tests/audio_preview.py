"""Generate a short, synthetic-content preview without email or news requests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from genai_digest.audio import DialogueTurn, HOST_A, HOST_B, _generate_with_piper


if __name__ == "__main__":
    output = Path("reports/podcast-voice-preview.mp3")
    output.parent.mkdir(exist_ok=True)
    _generate_with_piper([
        DialogueTurn(HOST_A, "Good morning. Welcome to your daily A I briefing. Today, we're testing a clearer, more conversational way to bring you the news."),
        DialogueTurn(HOST_B, "So, what has changed? We now have two neural voices, and a little breathing room between stories. You can follow along without having to look at a screen."),
        DialogueTurn(HOST_A, "Exactly. The full report still has the links and details. This short preview is just a voice test, not today's news."),
        DialogueTurn(HOST_B, "Thanks for listening. Have a good journey, and we'll catch you in the next briefing."),
    ], output)
    print(output.resolve())
