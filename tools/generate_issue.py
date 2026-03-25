#!/usr/bin/env python3
"""Generate a new digest issue HTML + update site/feed.json.

MVP v2 improvements:
- Fetch RSS/Atom
- Parse + normalize publish dates (best-effort)
- Enforce per-source cap (avoid OpenAI-only issues)
- Log per-source counts (for debugging)

Still token-free: no LLM summarization yet.
"""

import argparse, datetime as dt, json, sys, re
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'
DOCS = ROOT / 'docs'
ISSUES_DIR = SITE / 'issues'
DOCS_ISSUES_DIR = DOCS / 'issues'
FEED_PATH = SITE / 'feed.json'
SOURCES_PATH = ROOT / 'tools' / 'sources.json'


def fetch(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=25) as r:
        return r.read()


def is_xml_feed(data: bytes) -> bool:
    head = data.lstrip()[:200].lower()
    return head.startswith(b'<?xml') or head.startswith(b'<rss') or head.startswith(b'<feed')


def try_discover_feed_url(html: str, base_url: str) -> str:
    # crude <link rel="alternate" type="application/rss+xml" href="...">
    m = re.search(
        r'<link[^>]+rel=["\"]alternate["\"][^>]+type=["\"][^"\"]*(rss\+xml|atom\+xml)[^"\"]*["\"][^>]+href=["\"]([^"\"]+)["\"]',
        html,
        re.IGNORECASE,
    )
    if not m:
        return ''
    href = m.group(2)
    return urljoin(base_url, href)


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
        published = (
            text(e.findtext('a:published', default='', namespaces=ns))
            or text(e.findtext('a:updated', default='', namespaces=ns))
        )
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


def parse_date(s: str):
    s = (s or '').strip()
    if not s:
        return None

    # Common RSS format: "Wed, 18 Mar 2026 12:54:51 +0000"
    for fmt in (
        '%a, %d %b %Y %H:%M:%S %z',
        '%a, %d %b %Y %H:%M:%S %Z',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%S.%f%z',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%dT%H:%M:%S.%fZ',
    ):
        try:
            d = dt.datetime.strptime(s, fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=dt.timezone.utc)
            return d.astimezone(dt.timezone.utc)
        except Exception:
            pass

    # Last resort: try slicing ISO date
    try:
        if len(s) >= 10 and s[4] == '-' and s[7] == '-':
            d = dt.datetime.fromisoformat(s[:10])
            return d.replace(tzinfo=dt.timezone.utc)
    except Exception:
        pass

    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', default=dt.date.today().isoformat())
    ap.add_argument('--title', default='AI Tech Lead Digest')
    ap.add_argument('--days', type=int, default=4)
    ap.add_argument('--max-items', type=int, default=20)
    ap.add_argument('--per-source', type=int, default=4)
    ap.add_argument('--log', action='store_true')
    args = ap.parse_args()

    sources = json.loads(SOURCES_PATH.read_text('utf-8'))

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)

    items = []
    stats = []

    for src in sources.get('rss', []):
        name = src.get('name', 'unknown')
        url = src.get('url')
        if not url:
            continue
        try:
            data = fetch(url)
            feed_url = url

            if not is_xml_feed(data):
                # try discover RSS/Atom link from HTML
                html = data.decode('utf-8', errors='ignore')
                discovered = try_discover_feed_url(html, url)
                if discovered:
                    feed_url = discovered
                    data = fetch(feed_url)

            if not is_xml_feed(data):
                stats.append((name, 'err', 0, 0))
                continue

            parsed = parse_feed(data)
            kept = 0
            for it in parsed:
                link = it.get('link')
                if not link:
                    continue
                published = parse_date(it.get('published') or '')
                if published and published < cutoff:
                    continue
                items.append({**it, 'source': name, 'published_dt': published})
                kept += 1
            stats.append((name, 'ok', kept, len(parsed)))
        except Exception:
            stats.append((name, 'err', 0, 0))
            continue

    # dedupe by link
    seen = set()
    uniq = []
    for it in items:
        link = it['link']
        if link in seen:
            continue
        seen.add(link)
        uniq.append(it)

    # sort newest first (unknown dates last)
    def sort_key(it):
        d = it.get('published_dt')
        return d or dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)

    uniq.sort(key=sort_key, reverse=True)

    # enforce per-source cap
    per = {}
    selected = []
    for it in uniq:
        src = it.get('source', 'unknown')
        per[src] = per.get(src, 0)
        if per[src] >= args.per_source:
            continue
        selected.append(it)
        per[src] += 1
        if len(selected) >= args.max_items:
            break

    if args.log:
        sys.stderr.write('--- source stats ---\n')
        for name, st, kept, total in stats:
            sys.stderr.write(f'{name}: {st} kept={kept} total={total}\n')
        sys.stderr.write('--- selected per source ---\n')
        for k in sorted(per):
            sys.stderr.write(f'{k}: {per[k]}\n')

    date = args.date
    issue_path = f'issues/{date}.html'
    out_path = ISSUES_DIR / f'{date}.html'
    ISSUES_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_ISSUES_DIR.mkdir(parents=True, exist_ok=True)

    story_html = []
    for it in selected:
        title = (it.get('title') or '').strip() or it['link']
        link = it['link']
        src = it.get('source', '')
        story_html.append(f"""
          <div class=\"card story\">
            <div class=\"meta\"><span class=\"badge\">{src}</span></div>
            <h3><a href=\"{link}\" target=\"_blank\" rel=\"noopener\">{title}</a></h3>
            <div class=\"why\">Why it matters: (MVP v2 — TBD)</div>
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
    (DOCS_ISSUES_DIR / f'{date}.html').write_text(html, 'utf-8')

    feed = json.loads(FEED_PATH.read_text('utf-8'))
    feed.setdefault('issues', [])
    feed['issues'] = [
        {'date': date, 'title': args.title, 'path': issue_path, 'summary': f'{len(selected)} items'}
    ] + [x for x in feed['issues'] if x.get('date') != date]
    FEED_PATH.write_text(json.dumps(feed, ensure_ascii=False, indent=2), 'utf-8')

    print(issue_path)


if __name__ == '__main__':
    main()
