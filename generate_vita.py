#!/usr/bin/env python3
"""
PS Vita Homebrew Monthly Digest
Fetches posts from wololo.net (PS Vita homebrew hub) and outputs:
1. A formatted digest to stdout (for Telegram cron delivery)
2. An HTML magazine written to the repo (for the website front page)
Git push is done so the HTML shows up on GitHub Pages.
"""

import html
import os
import re
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

TELEGRAM_BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
GITHUB_TOKEN=os.getenv("GH_TOKEN", "")
GIT_REPO_DIR = os.path.dirname(os.path.abspath(__file__))
GH_PAGES_URL = "https://mimed95.github.io/morning-edition/magazines"
GIT_USER = "mimed95"
GIT_EMAIL = os.getenv("GIT_AUTHOR_EMAIL", "agent@morning-edition")

WOLOLO_RSS = "https://wololo.net/feed/"
MAX_ARTICLES = 10

# File storing URLs from the last edition — used to skip duplicates
PUBLISHED_URLS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "magazines", ".published_urls.txt")


def load_previously_published():
    """Return a set of URLs published in the previous edition."""
    if not os.path.exists(PUBLISHED_URLS_FILE):
        return set()
    with open(PUBLISHED_URLS_FILE, "r") as f:
        return {line.strip() for line in f if line.strip()}


def save_published_urls(urls):
    """Save the URLs from this edition for use as the baseline next time."""
    with open(PUBLISHED_URLS_FILE, "w") as f:
        for url in sorted(urls):
            f.write(url + "\n")

# Curated Vita homebrew feeds (from vault: Retro Gaming/Vita Homebrew Feeds.md)
# NOTE: Nitter feeds (nitter.net) are unreachable from server - skipped.
# GitHub releases.atom URLs need per-repo names (not github.com/owner/releases.atom) - skipped.
# Working feeds below.
FEEDS = {
    # Reddit
    "vitahacks_reddit": {"url": "https://www.reddit.com/r/vitahacks/.rss", "type": "rss", "source": "Reddit", "handle": "r/vitahacks"},
}


def fetch(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PSVitaDigest/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8")
    except Exception as e:
        print(f"[fetch error] {e}", file=os.sys.stderr)
        return None


def parse_rss(xml_text):
    try:
        root = ET.fromstring(xml_text)
        # Reddit .rss returns Atom with namespace; detect and handle both
        channel = root.find("channel")
        if channel is None:
            # No <channel> = Atom format, delegate to parse_atom
            return parse_atom(xml_text)
        items = []
        for item in channel.findall("item")[:MAX_ARTICLES]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            desc_raw = item.findtext("description") or ""
            desc = "".join(ET.fromstring(f"<r>{desc_raw}</r>").itertext()).strip()
            if title and link:
                items.append({"title": title, "link": link, "pubDate": pub, "description": desc[:200]})
        return items
    except Exception as e:
        print(f"[parse error] {e}", file=os.sys.stderr)
        return []


ATOM_NS = "http://www.w3.org/2005/Atom"


def parse_atom(xml_text):
    """Parse Atom feed (used by Nitter and GitHub releases.atom)."""
    try:
        root = ET.fromstring(xml_text)
        # Handle namespaced Atom (e.g. Reddit)
        ns = root.tag.split("}")[0].lstrip("{") if root.tag.startswith("{") else ATOM_NS
        ns_prefix = f"{{{ns}}}" if ns else ""
        items = []
        for entry in root.findall(f"{ns_prefix}entry")[:MAX_ARTICLES]:
            title = (entry.findtext(f"{ns_prefix}title") or "").strip()
            link_el = entry.find(f"{ns_prefix}link")
            link = link_el.get("href") if link_el is not None else ""
            pub = (entry.findtext(f"{ns_prefix}published") or entry.findtext(f"{ns_prefix}updated") or "").strip()
            content_el = entry.find(f"{ns_prefix}content")
            desc = content_el.text.strip() if content_el is not None and content_el.text else ""
            if title:
                items.append({"title": title, "link": link, "pubDate": pub, "description": desc[:200]})
        return items
    except Exception as e:
        print(f"[atom parse error] {e}", file=os.sys.stderr)
        return []


def fetch_curated_feeds():
    """Fetch all curated feeds in parallel and return a flat list of items with source metadata."""
    all_items = []

    def fetch_one(feed_key, meta):
        url = meta["url"]
        feed_type = meta.get("type", "rss")
        source = meta.get("source", "Unknown")
        handle = meta.get("handle", feed_key)
        xml = fetch(url)
        if not xml:
            print(f"[skip] {feed_key} ({url}) - no content", file=os.sys.stderr)
            return []
        if feed_type == "atom":
            items = parse_atom(xml)
        else:
            items = parse_rss(xml)
        for item in items:
            item["source"] = source
            item["feed_key"] = feed_key
            item["handle"] = handle
        return items

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch_one, k, v): k for k, v in FEEDS.items()}
        for future in as_completed(futures):
            feed_key = futures[future]
            try:
                items = future.result()
                print(f"[ok] {feed_key}: {len(items)} items", file=os.sys.stderr)
                all_items.extend(items)
            except Exception as e:
                print(f"[error] {feed_key}: {e}", file=os.sys.stderr)

    return all_items


def send_telegram(message):
    """Send via bot API if credentials are available (standalone run)."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    import json
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True}
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception as e:
        print(f"[telegram error] {e}", file=os.sys.stderr)
        return False


def git_commit_push(filename: str, month_str: str) -> bool:
    """Commit and push the HTML magazine to git."""
    try:
        env = os.environ.copy()
        if GITHUB_TOKEN:
            env["GIT_TOKEN"] = GITHUB_TOKEN
        # Detect current branch
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=GIT_REPO_DIR, check=True, capture_output=True, text=True
        ).stdout.strip()
        subprocess.run(
            ["git", "add", filename], cwd=GIT_REPO_DIR, check=True, env=env
        )
        subprocess.run(
            ["git", "-c", "user.name=" + GIT_USER, "-c", "user.email=" + GIT_EMAIL,
             "commit", "-m", f"PS Vita digest {month_str}"],
            cwd=GIT_REPO_DIR, check=True, env=env
        )
        subprocess.run(
            ["git", "push", "origin", branch],
            cwd=GIT_REPO_DIR, check=True, env=env
        )
        print(f"  [git] committed and pushed {filename}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  [git] commit/push failed: {e}")
        return False


# ─── HTML Magazine ───────────────────────────────────────────────────────────

LAYOUTS = [
    """<section class="spread hero">
  <div class="numeral">{num}</div>
  <div class="content">
    <span class="domain">wololo.net</span>
    <h1>{title}</h1>
    <p class="summary">{description}</p>
    <a href="{url}" class="read-link">Read more →</a>
  </div>
</section>""",

    """<section class="spread editorial">
  <div class="eyebrow"><span class="num">{num}</span> — wololo.net</div>
  <h1>{title}</h1>
  <blockquote>{description}</blockquote>
  <div class="meta">
    <a href="{url}">Read →</a>
  </div>
</section>""",

    """<section class="spread midnight">
  <div class="terminal-header">
    <span class="prompt">$</span> wololo.net
  </div>
  <h1 class="title">{title}</h1>
  <p class="summary">{description}</p>
  <a href="{url}" class="cmd">curl {url}</a>
</section>""",

    """<section class="spread rose">
  <div class="stamp">{num}</div>
  <div class="content">
    <span class="tag">wololo.net</span>
    <h1>{title}</h1>
    <p class="summary">{description}</p>
    <a href="{url}">Read more →</a>
  </div>
</section>""",

    """<section class="spread academic">
  <div class="footnote">[{num}]</div>
  <div class="content">
    <h1>{title}</h1>
    <span class="source">wololo.net</span>
    <p class="body">{description}</p>
    <div class="meta">
      <a href="{url}">Source →</a>
    </div>
  </div>
</section>""",

    """<section class="spread brutalist">
  <div class="num">{num}</div>
  <h1>{title}</h1>
  <p class="summary">{description}</p>
  <a href="{url}" class="link">READ MORE</a>
</section>""",

    """<section class="spread bigstat">
  <div class="giant-num">{num}</div>
  <div class="divider"></div>
  <h1>{title}</h1>
  <p class="summary">{description}</p>
  <a href="{url}">Open →</a>
</section>""",

    """<section class="spread magazine-opener">
  <div class="issue-num">No. {num}</div>
  <h1>{title}</h1>
  <p class="summary">{description}</p>
  <div class="meta">
    <span class="domain">wololo.net</span>
  </div>
  <a href="{url}" class="cta">Read the story</a>
</section>""",

    """<section class="spread noir">
  <div class="numeral">{num}</div>
  <div class="content">
    <h1>{title}</h1>
    <span class="domain">wololo.net</span>
    <p class="summary">{description}</p>
    <a href="{url}">Read →</a>
  </div>
</section>""",

    """<section class="spread index-card">
  <div class="card-num">{num}</div>
  <h1>{title}</h1>
  <p class="summary">{description}</p>
  <div class="meta">
    <span class="domain">wololo.net</span>
    <a href="{url}">→</a>
  </div>
</section>""",
]

LAYOUT_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300..900;1,9..144,300..900&family=Inter:wght@300;400;500;600&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --cream: #FAF7F2;
  --dark: #0D0D0D;
  --midnight: #0A0F1E;
  --rose: #F4E4E4;
  --slate: #2A2D3A;
  --terminal: #00FF88;
  --gold: #C9A84C;
  --charcoal: #1A1A1A;
  --offwhite: #F5F5F0;
}

body {
  font-family: 'Inter', system-ui, sans-serif;
  background: var(--cream);
  color: #1A1A1A;
  font-size: 18px;
  line-height: 1.6;
}

h1, h2, .display { font-family: 'Fraunces', Georgia, serif; }

.masthead {
  background: #2A0040;
  color: white;
  padding: 80px 60px;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
}
.masthead .edition {
  font-family: 'Inter', sans-serif;
  font-size: 13px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: #a855f7;
  margin-bottom: 12px;
}
.masthead h1 {
  font-size: clamp(48px, 8vw, 96px);
  font-weight: 900;
  color: white;
  line-height: 0.95;
}
.masthead h1 em {
  color: #a855f7;
  font-style: italic;
}
.masthead .tagline {
  font-size: 16px;
  color: #c4a0e8;
  max-width: 300px;
  text-align: right;
  line-height: 1.5;
}

.stories { display: grid; grid-template-columns: 1fr 1fr; gap: 0; }

.spread.hero {
  background: var(--dark);
  color: white;
  padding: 100px 60px;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 40px;
  align-items: start;
  min-height: 600px;
}
.spread.hero .numeral {
  font-family: 'Fraunces', serif;
  font-size: clamp(120px, 18vw, 240px);
  font-weight: 900;
  color: rgba(255,255,255,0.08);
  line-height: 1;
  user-select: none;
}
.spread.hero .domain {
  font-size: 11px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: #a855f7;
  display: block;
  margin-bottom: 16px;
}
.spread.hero h1 {
  font-size: clamp(28px, 4vw, 52px);
  font-weight: 700;
  line-height: 1.15;
  margin-bottom: 24px;
  color: white;
}
.spread.hero .summary {
  font-size: 18px;
  line-height: 1.7;
  color: rgba(255,255,255,0.75);
  margin-bottom: 32px;
  max-width: 600px;
}
.spread.hero .read-link {
  display: inline-block;
  background: #a855f7;
  color: white;
  padding: 14px 28px;
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
  letter-spacing: 0.05em;
}
.spread.hero .read-link:hover { background: white; color: #2A0040; }

.spread.editorial {
  background: var(--cream);
  color: #1A1A1A;
  padding: 80px 60px;
  display: grid;
  grid-template-rows: auto auto auto auto;
  gap: 24px;
  min-height: 600px;
  justify-content: start;
}
.spread.editorial .eyebrow {
  font-size: 12px;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: #888;
}
.spread.editorial .eyebrow .num {
  font-family: 'Fraunces', serif;
  font-size: 48px;
  color: #a855f7;
  font-style: italic;
  margin-right: 8px;
}
.spread.editorial h1 {
  font-size: clamp(32px, 5vw, 64px);
  font-weight: 700;
  line-height: 1.1;
  max-width: 700px;
  color: #1A1A1A;
}
.spread.editorial blockquote {
  font-family: 'Fraunces', serif;
  font-size: clamp(20px, 3vw, 32px);
  font-style: italic;
  line-height: 1.5;
  color: #555;
  border-left: 4px solid #a855f7;
  padding-left: 24px;
  max-width: 600px;
}
.spread.editorial .meta {
  display: flex;
  gap: 24px;
  font-size: 14px;
  color: #888;
}
.spread.editorial .meta a {
  color: #a855f7;
  text-decoration: none;
  font-weight: 500;
}

.spread.midnight {
  background: var(--midnight);
  color: var(--terminal);
  padding: 80px 60px;
  min-height: 500px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.spread.midnight .terminal-header {
  font-family: 'Courier New', monospace;
  font-size: 14px;
  color: #555;
  margin-bottom: 24px;
}
.spread.midnight .prompt { color: var(--terminal); margin-right: 8px; }
.spread.midnight h1 {
  font-size: clamp(28px, 4vw, 52px);
  font-weight: 700;
  color: white;
  margin-bottom: 24px;
  font-family: 'Courier New', monospace;
}
.spread.midnight .summary {
  font-size: 16px;
  color: rgba(255,255,255,0.6);
  margin-bottom: 32px;
  max-width: 600px;
}
.spread.midnight .cmd {
  font-family: 'Courier New', monospace;
  font-size: 14px;
  color: var(--terminal);
  text-decoration: none;
  border: 1px solid var(--terminal);
  padding: 8px 16px;
  display: inline-block;
}
.spread.midnight .cmd:hover { background: var(--terminal); color: var(--midnight); }

.spread.rose {
  background: var(--rose);
  color: #1A1A1A;
  padding: 80px 60px;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 40px;
  align-items: start;
  min-height: 500px;
}
.spread.rose .stamp {
  font-family: 'Fraunces', serif;
  font-size: clamp(80px, 12vw, 160px);
  font-weight: 900;
  color: rgba(168,85,247,0.15);
  line-height: 1;
}
.spread.rose .tag {
  font-size: 11px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: #a855f7;
  display: block;
  margin-bottom: 16px;
}
.spread.rose h1 {
  font-size: clamp(28px, 4vw, 52px);
  font-weight: 700;
  color: #1A1A1A;
  margin-bottom: 24px;
}
.spread.rose .summary {
  font-size: 16px;
  color: #555;
  margin-bottom: 32px;
}
.spread.rose a {
  color: #a855f7;
  text-decoration: none;
  font-weight: 500;
  font-size: 14px;
}

.spread.academic {
  background: var(--offwhite);
  color: #1A1A1A;
  padding: 80px 60px;
  min-height: 500px;
}
.spread.academic .footnote {
  font-family: 'Georgia', serif;
  font-size: 48px;
  color: #a855f7;
  margin-bottom: 24px;
}
.spread.academic h1 {
  font-size: clamp(28px, 4vw, 48px);
  font-weight: 700;
  margin-bottom: 16px;
  color: #1A1A1A;
}
.spread.academic .source {
  font-size: 12px;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: #888;
  display: block;
  margin-bottom: 24px;
}
.spread.academic .body {
  font-size: 17px;
  color: #444;
  line-height: 1.7;
  max-width: 600px;
  margin-bottom: 32px;
}
.spread.academic .meta {
  display: flex;
  gap: 24px;
  font-size: 14px;
}
.spread.academic .meta a {
  color: #a855f7;
  text-decoration: none;
}

.spread.brutalist {
  background: #0D0D0D;
  color: white;
  padding: 80px 60px;
  min-height: 500px;
  display: grid;
  grid-template-rows: auto auto auto auto;
  gap: 24px;
}
.spread.brutalist .num {
  font-family: 'Arial Black', sans-serif;
  font-size: clamp(80px, 15vw, 200px);
  font-weight: 900;
  color: #a855f7;
  line-height: 0.9;
}
.spread.brutalist h1 {
  font-size: clamp(24px, 4vw, 48px);
  font-weight: 900;
  text-transform: uppercase;
  color: white;
  letter-spacing: -0.02em;
}
.spread.brutalist .summary {
  font-size: 16px;
  color: #888;
  max-width: 600px;
}
.spread.brutalist .link {
  display: inline-block;
  background: #a855f7;
  color: white;
  padding: 12px 24px;
  font-size: 14px;
  font-weight: 700;
  text-decoration: none;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.spread.bigstat {
  background: var(--cream);
  color: #1A1A1A;
  padding: 80px 60px;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 40px;
  align-items: center;
  min-height: 500px;
}
.spread.bigstat .giant-num {
  font-family: 'Fraunces', serif;
  font-size: clamp(100px, 18vw, 220px);
  font-weight: 900;
  color: rgba(168,85,247,0.12);
  line-height: 1;
}
.spread.bigstat .divider {
  width: 60px;
  height: 3px;
  background: #a855f7;
  margin-bottom: 24px;
}
.spread.bigstat h1 {
  font-size: clamp(24px, 4vw, 48px);
  font-weight: 700;
  margin-bottom: 24px;
}
.spread.bigstat .summary {
  font-size: 16px;
  color: #666;
  margin-bottom: 32px;
}
.spread.bigstat a {
  color: #a855f7;
  text-decoration: none;
  font-weight: 500;
}

.spread.magazine-opener {
  background: linear-gradient(135deg, #2A0040 0%, #0D0D0D 100%);
  color: white;
  padding: 100px 60px;
  min-height: 600px;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
}
.spread.magazine-opener .issue-num {
  font-family: 'Fraunces', serif;
  font-size: 14px;
  letter-spacing: 0.2em;
  color: #a855f7;
  margin-bottom: 24px;
}
.spread.magazine-opener h1 {
  font-size: clamp(36px, 6vw, 80px);
  font-weight: 900;
  color: white;
  margin-bottom: 24px;
  line-height: 1.05;
}
.spread.magazine-opener .summary {
  font-size: 18px;
  color: rgba(255,255,255,0.7);
  margin-bottom: 32px;
  max-width: 600px;
}
.spread.magazine-opener .meta {
  display: flex;
  gap: 24px;
  font-size: 13px;
  color: #888;
  margin-bottom: 32px;
}
.spread.magazine-opener .domain { color: #a855f7; text-transform: uppercase; letter-spacing: 0.1em; }
.spread.magazine-opener .cta {
  display: inline-block;
  background: #a855f7;
  color: white;
  padding: 16px 32px;
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
  letter-spacing: 0.05em;
}
.spread.magazine-opener .cta:hover { background: white; color: #2A0040; }

.spread.noir {
  background: var(--charcoal);
  color: white;
  padding: 80px 60px;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 40px;
  align-items: start;
  min-height: 500px;
}
.spread.noir .numeral {
  font-family: 'Fraunces', serif;
  font-size: clamp(80px, 12vw, 160px);
  font-weight: 900;
  color: rgba(168,85,247,0.2);
  line-height: 1;
}
.spread.noir h1 {
  font-size: clamp(24px, 4vw, 48px);
  font-weight: 700;
  margin-bottom: 16px;
}
.spread.noir .domain {
  font-size: 11px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: #a855f7;
  display: block;
  margin-bottom: 16px;
}
.spread.noir .summary {
  font-size: 16px;
  color: rgba(255,255,255,0.6);
  margin-bottom: 32px;
}
.spread.noir a {
  color: #a855f7;
  text-decoration: none;
  font-size: 14px;
}

.spread.index-card {
  background: white;
  color: #1A1A1A;
  padding: 60px;
  display: grid;
  grid-template-rows: auto auto auto auto;
  gap: 16px;
  min-height: 400px;
}
.spread.index-card .card-num {
  font-family: 'Fraunces', serif;
  font-size: 64px;
  font-weight: 900;
  color: #a855f7;
  line-height: 1;
}
.spread.index-card h1 {
  font-size: clamp(20px, 3vw, 36px);
  font-weight: 700;
  color: #1A1A1A;
}
.spread.index-card .summary {
  font-size: 15px;
  color: #666;
}
.spread.index-card .meta {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: #888;
  margin-top: auto;
}
.spread.index-card .domain { color: #a855f7; text-transform: uppercase; letter-spacing: 0.1em; }
.spread.index-card a { color: #a855f7; text-decoration: none; }

.footer {
  background: #0D0D0D;
  color: #444;
  text-align: center;
  padding: 40px;
  font-size: 13px;
}
.footer a { color: #666; text-decoration: none; }
.footer a:hover { color: white; }
"""


def strip_html(text):
    """Remove HTML tags and decode common HTML entities for clean text display."""
    if not text:
        return ""
    # Remove all HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Collapse multiple spaces
    text = re.sub(r' {2,}', ' ', text)
    # Decode common HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    return text.strip()


def build_magazine(articles, month_str):
    story_blocks = []
    for i, art in enumerate(articles, 1):
        layout = LAYOUTS[(i - 1) % len(LAYOUTS)]
        title = strip_html(art.get("title", ""))
        description = strip_html(art.get("description", "") or "")
        url = art.get("link", "#")
        block = layout.format(
            num=i,
            title=title,
            description=description,
            url=url,
        )
        story_blocks.append(block)

    stories_html = "\n\n".join(story_blocks)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PS Vita Homebrew — {month_str}</title>
  <style>
{layout_css}
  </style>
</head>
<body>
  <header class="masthead">
    <div>
      <div class="edition">Monthly Digest — Vita Homebrew Sources</div>
      <h1>PS Vita<br><em>Homebrew</em></h1>
    </div>
    <p class="tagline">{len(articles)} stories from the Vita homebrew scene. {month_str}.</p>
  </header>

  <div class="stories">
    {stories_html}
  </div>

  <footer class="footer">
    <a href="https://github.com/mimed95/morning-edition">mimed95/morning-edition</a>
  </footer>
</body>
</html>"""
    return html


layout_css = LAYOUT_CSS.strip()


def main():
    now = datetime.now(timezone.utc)
    month_str = now.strftime("%B %Y")
    date_str = now.strftime("%Y-%m")

    # Load URLs from the previous edition to skip duplicates
    seen_urls = load_previously_published()
    print(f"Fetching PS Vita homebrew news (curated feeds + wololo.net)...", file=os.sys.stderr)
    if seen_urls:
        print(f"  Deduping against {len(seen_urls)} URLs from last edition", file=os.sys.stderr)

    all_articles = fetch_curated_feeds()

    # Add wololo as a separate feed
    xml = fetch(WOLOLO_RSS)
    if xml:
        wololo_articles = parse_rss(xml)
        for art in wololo_articles:
            art["source"] = "wololo.net"
            art["feed_key"] = "wololo"
            art["handle"] = "wololo.net"
        all_articles.extend(wololo_articles)
        print(f"[ok] wololo: {len(wololo_articles)} items", file=os.sys.stderr)

    # ── Deduplicate: only include items not in the previous edition ──
    new_articles = [a for a in all_articles if a.get("link") and a["link"] not in seen_urls]
    dropped = len(all_articles) - len(new_articles)
    print(f"Total: {len(all_articles)} articles, {dropped} duplicates dropped, {len(new_articles)} new", file=os.sys.stderr)

    # Save this edition's URLs for next time.
    # Always grow the set (never shrink) so the baseline only accumulates.
    # This means re-posts of old articles keep being suppressed even if
    # the previous edition had 0 new items.
    all_known_urls = seen_urls | {a["link"] for a in new_articles if a.get("link")}
    save_published_urls(all_known_urls)

    # ── Telegram digest (stdout for cron delivery) ──
    header = f"<b>PS Vita Homebrew Update — {month_str}</b>\n"
    header += f"<i>{len(new_articles)} new items</i>\n"
    header += "━" * 36 + "\n\n"

    if not new_articles:
        body = "No new articles found this month."
    else:
        lines = []
        for i, art in enumerate(new_articles[:20], 1):  # Cap at 20 for Telegram
            # Escape every feed-derived string: parse_mode=HTML rejects raw &/</<.
            # Truncate BEFORE escaping so a cut can't split an entity.
            handle = html.escape(art.get("handle", ""))
            source = html.escape(art.get("source", ""))
            title = html.escape(strip_html(art.get("title", "")))
            desc = html.escape(strip_html(art.get("description", "") or "")[:120])
            lines.append(f"<b>{i}. [{source}] {handle}</b>")
            lines.append(f"   {title}")
            if desc:
                lines.append(f"   {desc}...")
            lines.append(f"   🔗 {html.escape(art['link'])}\n")
        body = "\n".join(lines)

    digest = header + body

    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        send_telegram(digest)
    else:
        print(digest)

    # ── HTML magazine ──
    if new_articles:
        filename = f"magazines/{date_str}-vita.html"
        filepath = os.path.join(GIT_REPO_DIR, filename)
        page_url = f"{GH_PAGES_URL}/{date_str}-vita.html"

        print("Building HTML magazine...", file=os.sys.stderr)
        page_html = build_magazine(new_articles, month_str)

        with open(filepath, "w") as f:
            f.write(page_html)
        print(f"  Saved to {filepath}", file=os.sys.stderr)

        print("Committing to git...", file=os.sys.stderr)
        git_commit_push(filename, month_str)

        print(f"\nDone! → {page_url}", file=os.sys.stderr)


if __name__ == "__main__":
    main()
