#!/usr/bin/env python3
"""Generate a new digest issue HTML + update site/feed.json.

MVP v1:
- Fetch RSS/Atom
- Take recent items (last N days)
- Naive dedupe by link
- Build issue page with headline + source + link

No LLM summarization yet (token saver). We'll add optional LLM later.
"""

import argparse, datetime as dt, json, os, re, sys
from pathlib import Path
from urllib.request import urlopen, Request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'
ISSUES_DIR = SITE / 'issues'
FEED_PATH = SITE / 'feed.json'
SOURCES_PATH = ROOT / 'tools' / 'sources.json'


def fetch(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=25) as r:
        return r.read()


def text(x):
    return (x or '').strip()


def parse_atom(xml: bytes):
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    root = ET.fromstring(xml)
    out = []
    for e in root.findall('a:entry', ns):
        title = text(e.findtext('a:title', default='', namespaces=ns))
        link = None
        for l in e.findall('a:link', ns):
            if l.attrib.get('rel') in (None, '', 'alternate'):
                link = l.attrib.get('href')
                break
        if not link:
            link = e.find('a:link', ns).attrib.get('href') if e.find('a:link', ns) is not None else ''
        published = text(e.findtext('a:updated', default='', namespaces=ns)) or text(e.findtext('a:published', default='', namespaces=ns))
        out.append({'title': title, 'link': link, 'published': published})
    return out


def parse_rss(xml: bytes):
    root = ET.fromstring(xml)
    out = []
    for it in root.findall('./channel/item'):
        title = text(it.findtext('title', default=''))
        link = text(it.findtext('link', default=''))
        published = text(it.findtext('pubDate', default=''))
        out.append({'title': title, 'link': link, 'published': published})
    return out


def parse_feed(xml: bytes):
    # detect atom
    if b'<feed' in xml[:200] and b'http://www.w3.org/2005/Atom' in xml[:4000]:
        return parse_atom(xml)
    # try rss
    return parse_rss(xml)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', default=dt.date.today().isoformat())
    ap.add_argument('--title', default='AI Tech Lead Digest')
    ap.add_argument('--days', type=int, default=4)
    ap.add_argument('--max-items', type=int, default=20)
    args = ap.parse_args()

    sources = json.loads(SOURCES_PATH.read_text('utf-8'))

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)

    items = []
    for src in sources.get('rss', []):
        try:
            xml = fetch(src['url'])
            parsed = parse_feed(xml)
            for it in parsed:
                if not it.get('link'):
                    continue
                items.append({**it, 'source': src['name']})
        except Exception:
            continue

    # naive dedupe
    seen = set()
    deduped = []
    for it in items:
        link = it['link']
        if link in seen:
            continue
        seen.add(link)
        deduped.append(it)

    deduped = deduped[:args.max_items]

    date = args.date
    issue_path = f'issues/{date}.html'
    out_path = ISSUES_DIR / f'{date}.html'
    ISSUES_DIR.mkdir(parents=True, exist_ok=True)

    story_html = []
    for it in deduped:
        title = (it.get('title') or '').strip() or it['link']
        link = it['link']
        src = it.get('source','')
        story_html.append(f"""
          <div class=\"card story\">
            <div class=\"meta\"><span class=\"badge\">{src}</span></div>
            <h3><a href=\"{link}\" target=\"_blank\" rel=\"noopener\">{title}</a></h3>
            <div class=\"why\">Why it matters: (MVP v1 — TBD)</div>
          </div>
        """)

    html = f"""<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{args.title} — {date}</title>
  <link rel=\"stylesheet\" href=\"../assets/style.css\" />
</head>
<body>
  <div class=\"header\">
    <h1>{args.title}</h1>
    <div class=\"sub\">Issue date: {date}</div>
  </div>
  <div class=\"wrap\">
    <div class=\"card\">
      <h2>Headlines</h2>
      <div class=\"meta\"><span class=\"badge\">LLMs</span><span class=\"badge\">Agents</span><span class=\"badge\">New Features</span></div>
      <div class=\"grid\">
        {''.join(story_html)}
      </div>
    </div>
    <div class=\"footer\">Links go to original sources. This page contains summaries only.</div>
  </div>
</body>
</html>"""

    out_path.write_text(html, 'utf-8')

    feed = json.loads(FEED_PATH.read_text('utf-8'))
    feed.setdefault('issues', [])
    # prepend new
    feed['issues'] = [
        {'date': date, 'title': args.title, 'path': issue_path, 'summary': f'{len(deduped)} items'}
    ] + [x for x in feed['issues'] if x.get('date') != date]
    FEED_PATH.write_text(json.dumps(feed, ensure_ascii=False, indent=2), 'utf-8')

    print(issue_path)


if __name__ == '__main__':
    main()
