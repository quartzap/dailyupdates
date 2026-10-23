# Free podcast audio

The podcast uses two Edge neural voices (Andrew and Emma). Transient requests
are retried per turn. If that service fails, Piper generates the entire episode
locally on the runner using the Ryan and Lessac medium neural voice models.
Both hosts remain distinct, with short pauses and normalized volume.
No paid speech API or API key is needed. Piper runs on CPU.

Install and prepare locally:

```sh
python -m pip install edge-tts==7.2.8 piper-tts==1.8.0
python -m piper.download_voices --data-dir models/piper en_US-ryan-medium en_US-lessac-medium
```

Install ffmpeg too. The GitHub workflow prepares these dependencies automatically.
Voice downloads require internet access; synthesis with downloaded Piper models
does not. Models are ignored by Git. PIPER_MODEL_DIR overrides the model folder.

The workflow logs the selected engine: edge-tts-dialogue or piper-dialogue.
Service failure diagnostics log exception types, never service URLs or tokens.
If both neural engines fail, the email and PDF still go out without an MP3.
The old robotic eSpeak audio fallback has been removed.

Piper is GPL-3.0; individual voice datasets have their own terms. See the voice
model cards in https://huggingface.co/rhasspy/piper-voices and the upstream project:
https://github.com/OHF-Voice/piper1-gpl

The optional GitHub Models script polishing remains separate from speech.
When it is unavailable, the factual template script still provides two hosts,
without canned reactions or repeated introductory phrases for every summary.

Run regression tests: `python -m unittest discover -s tests`.
