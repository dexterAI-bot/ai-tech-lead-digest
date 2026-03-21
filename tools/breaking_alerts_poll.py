#!/usr/bin/env python3
"""Breaking alerts poller (MVP).

Runs frequently (e.g., hourly). Checks the same RSS sources for very recent items
and sends a Telegram alert when a high-signal keyword match appears.

Zero-token: uses openclaw CLI for message sending.

State stored in docs/alert-state.json (ids/links already alerted).
"""

import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.request import urlopen, Request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'
STATE = DOCS / 'alert-state.json'
SOURCES = ROOT / 'tools' / 'sources.json'

KEYWORDS = [
  r'agent', r'agents', r'mcp', r'function calling', r'tool calling', r'chatgpt', r'gpt-5', r'gpt-4',
  r'claude', r'sonnet', r'opus', r'gemini', r'llama', r'bedrock', r'copilot', r'release', r'launch',
  r'new model', r'new feature', r'api', r'sdk'
]
PAT = re.compile('|'.join(KEYWORDS), re.IGNORECASE)


def fetch(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=25) as r:
        return r.read()


def parse_atom(xml: bytes):
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    root = ET.fromstring(xml)
    out = []
    for e in root.findall('a:entry', ns):
        title = (e.findtext('a:title', default='', namespaces=ns) or '').strip()
        link = None
        for l in e.findall('a:link', ns):
            if l.attrib.get('rel') in (None, '', 'alternate'):
                link = l.attrib.get('href')
                break
        if not link:
            link = e.find('a:link', ns).attrib.get('href') if e.find('a:link', ns) is not None else ''
        updated = (e.findtext('a:updated', default='', namespaces=ns) or '').strip()
        out.append({'title': title, 'link': link, 'updated': updated})
    return out


def parse_rss(xml: bytes):
    root = ET.fromstring(xml)
    out = []
    for it in root.findall('./channel/item'):
        title = (it.findtext('title', default='') or '').strip()
        link = (it.findtext('link', default='') or '').strip()
        pub = (it.findtext('pubDate', default='') or '').strip()
        out.append({'title': title, 'link': link, 'updated': pub})
    return out


def parse_feed(xml: bytes):
    if b'<feed' in xml[:200] and b'http://www.w3.org/2005/Atom' in xml[:4000]:
        return parse_atom(xml)
    return parse_rss(xml)


def load_state():
    try:
        return json.loads(STATE.read_text('utf-8'))
    except Exception:
        return {"seen": []}


def save_state(st):
    DOCS.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), 'utf-8')


def send(msg: str):
    subprocess.check_call([
        'openclaw','message','send','--channel','telegram','--target','8250193666','--message',msg,'--json'
    ], stdout=subprocess.DEVNULL)


def tldr_from_title(title: str) -> str:
    t = re.sub(r'\s+', ' ', (title or '').strip())
    # Very lightweight TL;DR: keep it short and focused.
    # If title contains a colon, prefer the part after it.
    if ':' in t and len(t.split(':', 1)[1].strip()) >= 12:
        t = t.split(':', 1)[1].strip()
    # Trim to ~140 chars.
    if len(t) > 140:
        t = t[:137].rstrip() + '...'
    return t


def main():
    st = load_state()
    seen = set(st.get('seen') or [])

    sources = json.loads(SOURCES.read_text('utf-8'))

    # Only look back a short window; RSS dates are inconsistent so we also rely on dedupe.
    hits = []
    for src in sources.get('rss', []):
        try:
            parsed = parse_feed(fetch(src['url']))
        except Exception:
            continue
        for it in parsed[:10]:
            link = it.get('link')
            title = it.get('title') or ''
            if not link or link in seen:
                continue
            if not PAT.search(title):
                continue
            hits.append((src['name'], title.strip(), link))

    if not hits:
        return

    # Alert only top 3 per run
    for src, title, link in hits[:3]:
        seen.add(link)
        tl = tldr_from_title(title)
        send(f"AI news ({src})\nTL;DR: {tl}\n{link}")

    st['seen'] = list(seen)[-500:]
    st['lastRun'] = dt.datetime.utcnow().isoformat() + 'Z'
    save_state(st)


if __name__ == '__main__':
    main()
