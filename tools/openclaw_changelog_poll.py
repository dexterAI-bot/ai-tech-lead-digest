#!/usr/bin/env python3
"""OpenClaw changelog watcher (token-free).

- Scrapes https://www.getopenclaw.ai/en/changelog
- Detects newest version string like v2026.3.13
- Sends a Telegram message when a newer version appears.

State: docs/openclaw-changelog-state.json
"""

import json
import re
import subprocess
from pathlib import Path
from urllib.request import urlopen, Request

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'
STATE = DOCS / 'openclaw-changelog-state.json'
URL = 'https://www.getopenclaw.ai/en/changelog'
TARGET = '-5241424017'

VERSION_RE = re.compile(r'\bv(20\d{2}\.\d{1,2}\.\d{1,2}(?:-\d+)?)\b')


def fetch_html(url: str) -> str:
    data = urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=25).read()
    return data.decode('utf-8', errors='ignore')


def load_state():
    try:
        return json.loads(STATE.read_text('utf-8'))
    except Exception:
        return {}


def save_state(st):
    DOCS.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), 'utf-8')


def send(msg: str):
    subprocess.check_call([
        'openclaw','message','send','--channel','telegram','--target',TARGET,'--message',msg,'--json'
    ], stdout=subprocess.DEVNULL)


def main():
    html = fetch_html(URL)
    versions = VERSION_RE.findall(html)
    if not versions:
        return

    latest = versions[0]
    st = load_state()
    last = st.get('lastVersion')

    if last == latest:
        return

    st['lastVersion'] = latest
    save_state(st)

    send(f"AI news (OpenClaw)\nTL;DR: New changelog entry v{latest} is live.\n{URL}")


if __name__ == '__main__':
    main()
