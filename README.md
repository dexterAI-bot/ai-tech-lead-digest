# ai-tech-lead-digest
AI Tech Lead Digest: Tue/Fri newsletters + breaking alerts. Static HTML archive + Telegram headlines.

## Publishing workflow (prevention)
Run `tools/generate_issue.py` to produce the latest HTML issue under `site/issues/`. The script now mirrors the generated page into `docs/issues/`, so GitHub Pages stays in sync automatically. After running it, `git add site/issues/<date>.html docs/issues/<date>.html` before committing and pushing; otherwise the public archive will 404 for the new entry.
