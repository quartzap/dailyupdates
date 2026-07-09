# GenAI Daily Report Utility

This utility gathers fresh GenAI updates from free web sources, groups them into the areas you asked for, builds an HTML digest, and emails it on a schedule.

## What it covers

- Product announcements
- Trade deals and partnerships
- Research papers
- Industry use cases
- Hardware developments
- Cybersecurity and GenAI risk

## Free stack

- Runtime: Python 3.12
- News ingestion: Google News RSS search feeds
- Research ingestion: arXiv public API
- Storage: JSON file committed back to the repo for dedupe state
- Scheduler and hosting: GitHub Actions scheduled workflow
- Email delivery: Gmail SMTP or any SMTP account you already own
- Audio brief: offline `espeak-ng` plus `ffmpeg` on the GitHub Actions runner

## Why this stack

- No paid APIs are required.
- No always-on server is required.
- GitHub Actions can run this once every morning on a cron schedule.
- The code uses only the Python standard library, so there are no package installs to manage.

## Project structure

- `main.py`: entry point
- `digest_config.json`: categories and source configuration
- `src/genai_digest/fetchers.py`: web fetching and XML parsing
- `src/genai_digest/pipeline.py`: filtering, categorization, scoring, dedupe
- `src/genai_digest/report.py`: HTML and text report rendering
- `src/genai_digest/audio.py`: podcast script and MP3 generation
- `src/genai_digest/emailer.py`: SMTP email delivery
- `state/sent_items.json`: saved IDs of already-sent items
- `.github/workflows/daily_digest.yml`: scheduler for daily runs

## Local run

1. Create local config files:

```powershell
.\scripts\bootstrap.ps1
```

2. Fill in `.env` with your email settings.
3. Run a sample dry run:

```powershell
& 'C:\Users\quartzap\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' .\main.py --sample
```

4. Run a live fetch without sending email:

```powershell
& 'C:\Users\quartzap\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' .\main.py --no-email
```

5. Run the full live flow:

```powershell
& 'C:\Users\quartzap\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' .\main.py
```

6. Generate a local podcast script, and an MP3 if audio tools are installed:

```powershell
& 'C:\Users\quartzap\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' .\main.py --sample --with-audio
```

## GitHub setup

1. Create a GitHub repository and push this folder.
2. Add these repository secrets:
   - `GENAI_REPORT_FROM`
   - `GENAI_REPORT_TO`
   - `SMTP_HOST`
   - `SMTP_PORT`
   - `SMTP_USERNAME`
   - `SMTP_PASSWORD`
   - `SMTP_USE_TLS`
3. The fastest way to prepare the secrets file locally is to fill in `.github-secrets`.
4. Add the secrets either in the GitHub web UI or with GitHub CLI:

```powershell
gh secret set -f .github-secrets
```

5. Enable GitHub Actions for the repository.
6. Keep the repository public if you want the simplest zero-cost GitHub-hosted runner path.

## Gmail setup

If you use Gmail SMTP, enable 2-Step Verification and generate an App Password for the mailbox used to send the report. Put that 16-character app password into `SMTP_PASSWORD`.

## Notes

- The current default source mix is Google News RSS plus arXiv.
- You can extend `digest_config.json` with curated RSS feeds later for company blogs or niche publications.
- The report is saved into `reports/` on every run.
- Scheduled workflows run in GitHub Actions using cron with timezone-aware scheduling.
- The default email is intentionally concise. Open a headline to read the full source item.
- Each item is assigned to one primary category so the same story does not repeat across sections.
- The dedupe state stores both link-based IDs and title fingerprints to reduce repeat stories across days.
- The scheduled workflow attaches an MP3 audio brief when `AUDIO_ENABLED=true`.
- The MP3 uses `edge-tts` with the `en-IN-NeerjaNeural` voice by default, then falls back to `espeak-ng` if the neural TTS call is unavailable.
- NotebookLM can create Audio Overviews from uploaded sources, but this project does not automate NotebookLM directly because there is no stable public NotebookLM API in use here. A practical manual workflow is to upload the generated podcast script or HTML report into NotebookLM and generate an Audio Overview there.
