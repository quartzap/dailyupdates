# GenAI Daily Report Utility

This utility gathers fresh GenAI updates from free web sources, groups them into the areas you asked for, builds a concise email digest, attaches a PDF copy, and emails it on a schedule.

## What it covers

- Product announcements
- Trade deals and partnerships
- Research papers
- Industry use cases
- Hardware developments
- Cybersecurity and GenAI risk
- Social signals from X-focused public search

## Free stack

- Runtime: Python 3.12
- News ingestion: Google News RSS search feeds
- Research ingestion: arXiv public API
- Social ingestion: X-focused public search through indexed web/news results
- Storage: JSON file committed back to the repo for dedupe state
- Scheduler and hosting: GitHub Actions scheduled workflow
- Email delivery: Gmail SMTP or any SMTP account you already own
- Audio brief: offline `espeak-ng` plus `ffmpeg` on the GitHub Actions runner
- PDF attachment: `reportlab`

## Why this stack

- No paid APIs are required.
- No always-on server is required.
- GitHub Actions can run this once every morning on a cron schedule.
- Only small pinned packages are installed during the workflow for audio and PDF generation.

## Project structure

- `main.py`: entry point
- `digest_config.json`: categories and source configuration
- `src/genai_digest/fetchers.py`: web fetching and XML parsing
- `src/genai_digest/pipeline.py`: filtering, categorization, scoring, dedupe
- `src/genai_digest/report.py`: HTML and text report rendering
- `src/genai_digest/pdf_report.py`: downloadable PDF report rendering
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
- Google News redirect links (`news.google.com/rss/articles/...`) are resolved to the original publisher URLs before rendering. Resolution tries a zero-cost base64 decode first, then an HTTP redirect follow, then Google's internal decode endpoint. Any failure keeps the original link and adds a warning. Control with `RESOLVE_LINKS` (default true) and `RESOLVE_LINKS_MAX` (default 50 per run).
- Daily editions pin a "Week Highlights" section at the top of the email, PDF, and text report: the top 5 highest-scoring stories from the last 7 days, drawn from the article archive. Highlighted stories are excluded from the sections below so nothing appears twice. Sunday weekly editions keep the fuller "Weekly Major Updates" section instead.
- X coverage uses a public indexed-search approximation for x.com/twitter.com results because X does not provide a reliable free global trending API.
- You can extend `digest_config.json` with curated RSS feeds later for company blogs or niche publications.
- The report is saved into `reports/` on every run.
- A PDF version of the report is generated and attached to every email.
- Every Sunday, the email becomes a weekly edition with major updates from the last 7 days based on the saved article archive.
- Scheduled workflows run in GitHub Actions using cron with timezone-aware scheduling. The current schedule is configured in `.github/workflows/daily_digest.yml` for 8:00 AM Asia/Kolkata.
- The default email is intentionally concise. Open a headline to read the full source item.
- Each item is assigned to one primary category so the same story does not repeat across sections.
- The dedupe state stores both link-based IDs, title fingerprints, and recent article metadata to reduce repeat stories across days and support the Sunday weekly summary.
- The scheduled workflow attaches an MP3 audio brief when `AUDIO_ENABLED=true`.
- The MP3 is a two-host, NotebookLM-style conversation. Each speaker turn is synthesized with `edge-tts` (defaults: `en-US-AndrewMultilingualNeural` and `en-US-EmmaMultilingualNeural`, override with `AUDIO_VOICE` / `AUDIO_VOICE_B`), then the turns are stitched with `ffmpeg` with short pauses and loudness normalization. If `edge-tts` is unavailable the audio falls back to a single-voice `espeak-ng` read of the script.
- Summaries that merely repeat the headline (a quirk of Google News RSS descriptions) are dropped at parse time, so headlines are no longer spoken twice.
- Optional: set `LLM_SCRIPT_ENABLED=true` to rewrite the template dialogue into a more natural conversation using GitHub Models (free, uses the built-in `GITHUB_TOKEN` with `models: read` permission — no paid API). On any failure the deterministic template script is used, so the pipeline never breaks.
- NotebookLM can create Audio Overviews from uploaded sources, but this project does not automate NotebookLM directly because there is no stable public NotebookLM API in use here. A practical manual workflow is to upload the generated podcast script or HTML report into NotebookLM and generate an Audio Overview there.
