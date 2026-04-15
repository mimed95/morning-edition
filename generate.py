#!/usr/bin/env python3
"""
Morning Edition — Daily Hacker News Magazine Generator
Fetches HN front page, curates top 10 stories by taste,
generates a beautiful editorial HTML magazine.
"""

import datetime
import json
import os
import random
import re
import subprocess
import urllib.request
from typing import Optional

# ─── Config ────────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GIT_REPO_DIR = os.path.dirname(os.path.abspath(__file__))  # repo root
GH_PAGES_URL = "https://mimed95.github.io/morning-edition/magazines"
GIT_USER = "mimed95"
GIT_EMAIL = os.getenv("GIT_AUTHOR_EMAIL", "agent@morning-edition")

# HN API
HN_TOP = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{}.json"

# ─── Fetch ─────────────────────────────────────────────────────────────────

def fetch_json(url: str) -> Optional[dict | list]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MorningEdition/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  [fetch] {url} — {e}")
        return None

def fetch_hn_top(n: int = 50) -> list[dict]:
    ids = fetch_json(HN_TOP)
    if not ids:
        return []
    # Fetch first n in batches of 5
    stories = []
    for bid in ids[:n]:
        item = fetch_json(HN_ITEM.format(bid))
        if not item:
            continue
        # Skip dead/deleted/empty
        if item.get("deleted") or item.get("dead") or not item.get("title"):
            continue
        stories.append(item)
        if len(stories) >= n:
            break
    return stories

# ─── Filter & Score ─────────────────────────────────────────────────────────

# Topics to LEAN INTO (score bonus)
PREFER = [
    "ai", "llm", "gpt", "claude", "gemini", "openai", "model",
    "machine learning", "neural", "deep learning",
    "gpu", "tpu", "nvidia", "amd", "cuda", "tensor",
    "python", "rust", "golang", "typescript", "javascript",
    "linux", "open source", "github", "terminal", "cli",
    "privacy", "encryption", "security", "vulnerability", "exploit",
    "hardware", "chip", "processor", "cpu", "gpu", "fpga", "asic",
    "robot", "drone", "autonomous", "robotics",
    "science", "research", "physics", "biology", "chemistry",
    "game", "gaming", "steam", "indie game",
    "creative", "tool", "app", "software",
    "webassembly", "wasm", "browser",
]

# Topics to SKIP (score penalty + block)
SKIP = [
    "crypto", "bitcoin", "ethereum", "nft", "blockchain", "web3",
    "politics", "government", "election", "trump", "biden",
    "career", "job", "salary", "interview", "resume", "hiring",
    "show hn", "ask hn", "launch hn",
    "apple", "google", "meta", "facebook", "amazon", "microsoft",
]

SCORES = {
    "news.ycombinator.com": -3,  # internal HN discussion links
    "github.com": 1,              # prefer actual code/projects
    "arxiv.org": 2,               # prefer research
    "huggingface.co": 3,
    "pytorch.org": 2,
    "github.io": 1,
}


def score_story(story: dict) -> float:
    title = story.get("title", "").lower()
    url = story.get("url", "").lower()
    by = story.get("by", "")
    score = story.get("score", 0)

    # Skip
    for kw in SKIP:
        if kw in title or kw in url:
            return -999

    # Prefer
    bonus = 0
    for kw in PREFER:
        if kw in title or kw in url:
            bonus += 3

    # Domain bonus
    for domain, pts in SCORES.items():
        if domain in url:
            bonus += pts

    # Score signal (normalize 0-500 -> 0-5)
    score_norm = min(score, 500) / 100

    return score_norm + bonus


def curate_top10(stories: list[dict]) -> list[dict]:
    scored = [(score_story(s), s) for s in stories]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:10]]


# ─── Summaries (curated — user should edit these periodically) ───────────────

# Per-story 1-2 sentence summaries. These are seeds — the generator picks
# one per story based on keywords. USER SHOULD EDIT THESE to match your taste.
STORY_SUMMARIES = [
    # AI/ML
    ("llm", "A new model drops benchmarks in a hurry — worth tracking even if the demo is cherry-picked."),
    ("gpt", "OpenAI ships again. The capability jump is real, but so is the API pricing."),
    ("claude", "Anthropic's latest model handles long contexts better than anything before it."),
    ("ai", "Another AI paper that will quietly change how products are built."),
    ("model", "The model itself isn't the story — the data and infrastructure underneath it are."),
    # Dev tools
    ("python", "Python just got faster in the places that matter most for real projects."),
    ("rust", "Memory safety without a garbage collector. Finally production-ready for serious backends."),
    ("terminal", "The terminal keeps getting better. This one might actually make you switch."),
    ("open source", "A project that should have been big by now finally gets the attention it deserves."),
    # Security
    ("vulnerability", "A critical bug in something you probably run. Patch today."),
    ("exploit", "The exploit is already in the wild. If you run this software, stop what you're doing."),
    ("privacy", "A tool that actually respects your privacy instead of just promising to."),
    # Hardware
    ("gpu", "NVIDIA's latest silicon reshapes what's possible at the edge. The data center implications follow."),
    ("chip", "A new chip that could finally break the dependence on a single supplier."),
    ("hardware", "Interesting silicon, even if the company behind it is still finding its footing."),
    # Gaming
    ("game", "An indie game that punches way above its budget. Worth keeping on your radar."),
    ("gaming", "The kind of game that makes you remember why you got into this hobby."),
    # Science
    ("science", "Peer-reviewed, open access, and actually changes something we thought we knew."),
    ("research", "Academic work with real-world implications. The gap between paper and product is shrinking."),
    # Creative
    ("tool", "A new tool that makes something hard feel effortless. Already replacing three things I used to use."),
    ("creative", "The intersection of code and art keeps producing unexpected things. This is one of them."),
    # Web
    ("browser", "A browser that finally takes performance seriously without sacrificing the extensions you need."),
    ("webassembly", "WebAssembly keeps creeping into places it has no business being. This time it's a good thing."),
]

CATCHALL_SUMMARIES = [
    "Solid piece of work from the HN crowd. Worth setting aside 10 minutes to read properly.",
    "A technical deep-dive that doesn't talk down to you. Exactly the kind of thing HN does best.",
    "One of those posts that makes you want to try something new this weekend.",
    "Good signal-to-noise ratio on this one. The discussion is worth scrolling if you have time.",
    "Not flashy, but the kind of thing that accumulates into something important.",
]


def make_summary(story: dict) -> str:
    title = story.get("title", "").lower()
    for keywords, summary in STORY_SUMMARIES:
        if any(kw.lower() in title for kw in keywords.split()):
            return summary
    return random.choice(CATCHALL_SUMMARIES)


# ─── HTML Magazine ───────────────────────────────────────────────────────────

LAYOUTS = [
    # 1. Hero — full-bleed dark, massive serif numeral
    """<section class="spread hero">
  <div class="numeral">{num}</div>
  <div class="content">
    <span class="domain">{domain}</span>
    <h1>{title}</h1>
    <p class="summary">{summary}</p>
    <div class="meta">
      <span class="score">{score} pts</span>
      <span class="comments">{comments} comments</span>
    </div>
    <a href="{url}" class="read-link">Read the story →</a>
  </div>
</section>""",

    # 2. Light editorial — cream bg, serif headline, pull quote
    """<section class="spread editorial">
  <div class="eyebrow"><span class="num">{num}</span> — {domain}</div>
  <h1>{title}</h1>
  <blockquote>{summary}</blockquote>
  <div class="meta">
    <span class="score">{score} pts</span>
    <span class="comments">{comments} comments</span>
    <a href="{url}">Read →</a>
  </div>
</section>""",

    # 3. Midnight — near-black bg, terminal green accents
    """<section class="spread midnight">
  <div class="terminal-header">
    <span class="prompt">$</span> {domain}
  </div>
  <h1 class="title">{title}</h1>
  <p class="summary">{summary}</p>
  <div class="meta">
    <span class="score">&gt; {score} pts</span>
    <span class="comments">// {comments} comments</span>
  </div>
  <a href="{url}" class="cmd">curl {url}</a>
</section>""",

    # 4. Rose alert — soft rose bg, bold stamp numeral
    """<section class="spread rose">
  <div class="stamp">{num}</div>
  <div class="content">
    <span class="tag">{domain}</span>
    <h1>{title}</h1>
    <p class="summary">{summary}</p>
    <a href="{url}">{score} pts — {comments} comments →</a>
  </div>
</section>""",

    # 5. Academic — off-white, Times-style serif, footnote numeral
    """<section class="spread academic">
  <div class="footnote">[{num}]</div>
  <div class="content">
    <h1>{title}</h1>
    <span class="source">{domain}</span>
    <p class="body">{summary}</p>
    <div class="meta">
      <span>{score} points</span>
      <span>{comments} comments</span>
      <a href="{url}">DOI link →</a>
    </div>
  </div>
</section>""",

    # 6. Brutalist — raw black/white, oversized condensed type
    """<section class="spread brutalist">
  <div class="num">{num}</div>
  <h1>{title}</h1>
  <div class="meta">
    <span>{domain}</span>
    <span>{score}pts</span>
    <span>{comments}c</span>
  </div>
  <p class="summary">{summary}</p>
  <a href="{url}" class="link">READ MORE</a>
</section>""",

    # 7. Big-stat finish — light bg, giant numeral, minimal
    """<section class="spread bigstat">
  <div class="giant-num">{num}</div>
  <div class="divider"></div>
  <h1>{title}</h1>
  <p class="summary">{summary}</p>
  <div class="meta">
    <span>{domain}</span>
    <span>{score} pts</span>
    <span>{comments} comments</span>
  </div>
  <a href="{url}">Open →</a>
</section>""",

    # 8. Magazine opener — full-bleed, large Fraunces headline
    """<section class="spread magazine-opener">
  <div class="issue-num">No. {num}</div>
  <h1>{title}</h1>
  <p class="summary">{summary}</p>
  <div class="meta">
    <span class="domain">{domain}</span>
    <span class="score">{score} pts</span>
    <span class="comments">{comments} comments</span>
  </div>
  <a href="{url}" class="cta">Read the story</a>
</section>""",

    # 9. Noir — dark charcoal, white serif, minimal
    """<section class="spread noir">
  <div class="numeral">{num}</div>
  <div class="content">
    <h1>{title}</h1>
    <span class="domain">{domain}</span>
    <p class="summary">{summary}</p>
    <div class="meta">
      <span>{score} pts</span>
      <span>{comments} comments</span>
    </div>
    <a href="{url}">Read →</a>
  </div>
</section>""",

    # 10. Index card — grid of mini-cards
    """<section class="spread index-card">
  <div class="card-num">{num}</div>
  <h1>{title}</h1>
  <p class="summary">{summary}</p>
  <div class="meta">
    <span class="domain">{domain}</span>
    <span class="score">{score} pts</span>
    <span class="comments">{comments} comments</span>
    <a href="{url}">→</a>
  </div>
</section>""",
]

LAYOUT_CSS = """
/* ─── Reset & Fonts ─── */
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

/* ─── Header ─── */
.masthead {
  background: var(--dark);
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
  color: #888;
  margin-bottom: 12px;
}
.masthead h1 {
  font-size: clamp(48px, 8vw, 96px);
  font-weight: 900;
  color: white;
  line-height: 0.95;
}
.masthead h1 em {
  color: var(--gold);
  font-style: italic;
}
.masthead .tagline {
  font-size: 16px;
  color: #888;
  max-width: 300px;
  text-align: right;
  line-height: 1.5;
}

/* ─── Stories Grid ─── */
.stories {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0;
}

/* ─── SPREAD 1: HERO ─── */
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
  color: var(--gold);
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
.spread.hero .meta {
  display: flex;
  gap: 24px;
  font-size: 13px;
  color: #888;
  margin-bottom: 32px;
}
.spread.hero .read-link {
  display: inline-block;
  background: var(--gold);
  color: var(--dark);
  padding: 14px 28px;
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
  letter-spacing: 0.05em;
}
.spread.hero .read-link:hover { background: white; }

/* ─── SPREAD 2: EDITORIAL ─── */
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
  color: var(--gold);
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
  border-left: 4px solid var(--gold);
  padding-left: 24px;
  max-width: 700px;
}
.spread.editorial .meta {
  display: flex;
  gap: 24px;
  font-size: 13px;
  color: #888;
  align-items: center;
}
.spread.editorial .meta a {
  color: var(--gold);
  text-decoration: none;
  font-weight: 600;
}

/* ─── SPREAD 3: MIDNIGHT ─── */
.spread.midnight {
  background: var(--midnight);
  color: white;
  padding: 80px 60px;
  font-family: 'Courier New', monospace;
}
.spread.midnight .terminal-header {
  font-size: 13px;
  color: var(--terminal);
  margin-bottom: 24px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.spread.midnight .prompt {
  background: var(--terminal);
  color: var(--midnight);
  padding: 2px 8px;
  font-weight: bold;
  border-radius: 3px;
}
.spread.midnight h1.title {
  font-size: clamp(22px, 3.5vw, 44px);
  font-weight: 700;
  line-height: 1.2;
  margin-bottom: 24px;
  color: white;
}
.spread.midnight .summary {
  font-size: 17px;
  color: rgba(255,255,255,0.65);
  line-height: 1.7;
  margin-bottom: 32px;
  max-width: 600px;
}
.spread.midnight .meta {
  display: flex;
  gap: 24px;
  font-size: 13px;
  color: rgba(255,255,255,0.4);
  margin-bottom: 32px;
}
.spread.midnight .cmd {
  font-size: 14px;
  color: var(--terminal);
  text-decoration: none;
  border: 1px solid var(--terminal);
  padding: 10px 20px;
  display: inline-block;
}
.spread.midnight .cmd:hover { background: var(--terminal); color: var(--midnight); }

/* ─── SPREAD 4: ROSE ─── */
.spread.rose {
  background: var(--rose);
  padding: 80px 60px;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 40px;
  align-items: start;
}
.spread.rose .stamp {
  font-family: 'Fraunces', serif;
  font-size: clamp(100px, 16vw, 200px);
  font-weight: 900;
  font-style: italic;
  color: rgba(180,60,60,0.18);
  line-height: 1;
  user-select: none;
}
.spread.rose .tag {
  font-size: 11px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: #8B4444;
  display: block;
  margin-bottom: 12px;
}
.spread.rose h1 {
  font-size: clamp(22px, 3.5vw, 42px);
  font-weight: 700;
  line-height: 1.2;
  margin-bottom: 20px;
  color: #1A1A1A;
}
.spread.rose .summary {
  font-size: 17px;
  color: #555;
  line-height: 1.7;
  margin-bottom: 24px;
}
.spread.rose a {
  font-size: 13px;
  font-weight: 600;
  color: #8B4444;
  text-decoration: none;
  letter-spacing: 0.05em;
}
.spread.rose a:hover { text-decoration: underline; }

/* ─── SPREAD 5: ACADEMIC ─── */
.spread.academic {
  background: var(--offwhite);
  padding: 80px 60px;
  display: grid;
  grid-template-columns: 80px 1fr;
  gap: 40px;
  align-items: start;
}
.spread.academic .footnote {
  font-family: 'Fraunces', serif;
  font-size: 14px;
  color: #999;
  padding-top: 8px;
}
.spread.academic h1 {
  font-size: clamp(20px, 3vw, 38px);
  font-weight: 700;
  line-height: 1.25;
  margin-bottom: 12px;
  color: #1A1A1A;
}
.spread.academic .source {
  font-size: 11px;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: #888;
  display: block;
  margin-bottom: 20px;
}
.spread.academic .body {
  font-size: 17px;
  color: #555;
  line-height: 1.75;
  margin-bottom: 24px;
  font-family: 'Fraunces', serif;
  font-style: italic;
}
.spread.academic .meta {
  display: flex;
  gap: 20px;
  font-size: 12px;
  color: #999;
  align-items: center;
}
.spread.academic .meta a {
  color: #888;
  text-decoration: none;
  font-weight: 500;
}
.spread.academic .meta a:hover { color: #1A1A1A; }

/* ─── SPREAD 6: BRUTALIST ─── */
.spread.brutalist {
  background: #000;
  color: white;
  padding: 80px 60px;
  border-right: 4px solid var(--gold);
}
.spread.brutalist .num {
  font-family: 'Inter', sans-serif;
  font-size: clamp(80px, 14vw, 180px);
  font-weight: 900;
  color: white;
  line-height: 1;
  margin-bottom: 24px;
  letter-spacing: -0.05em;
}
.spread.brutalist h1 {
  font-family: 'Inter', sans-serif;
  font-size: clamp(24px, 4vw, 56px);
  font-weight: 900;
  text-transform: uppercase;
  letter-spacing: -0.02em;
  line-height: 1.05;
  margin-bottom: 24px;
  color: white;
}
.spread.brutalist .meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #666;
  margin-bottom: 24px;
}
.spread.brutalist .summary {
  font-size: 16px;
  color: rgba(255,255,255,0.6);
  line-height: 1.6;
  margin-bottom: 32px;
  max-width: 560px;
}
.spread.brutalist .link {
  display: inline-block;
  background: white;
  color: black;
  padding: 14px 28px;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  text-decoration: none;
}
.spread.brutalist .link:hover { background: var(--gold); }

/* ─── SPREAD 7: BIG-STAT ─── */
.spread.bigstat {
  background: white;
  padding: 80px 60px;
  display: grid;
  grid-template-columns: auto 1fr;
  grid-template-rows: auto auto auto auto;
  gap: 0 40px;
  align-items: start;
}
.spread.bigstat .giant-num {
  font-family: 'Fraunces', serif;
  font-size: clamp(100px, 18vw, 220px);
  font-weight: 900;
  font-style: italic;
  color: #1A1A1A;
  line-height: 1;
  grid-row: 1 / 5;
}
.spread.bigstat .divider {
  height: 3px;
  background: var(--gold);
  width: 80px;
  margin-bottom: 24px;
  grid-column: 2;
}
.spread.bigstat h1 {
  font-size: clamp(20px, 3vw, 40px);
  font-weight: 700;
  line-height: 1.2;
  color: #1A1A1A;
  grid-column: 2;
  margin-bottom: 16px;
}
.spread.bigstat .summary {
  font-size: 16px;
  color: #666;
  line-height: 1.7;
  grid-column: 2;
  margin-bottom: 24px;
}
.spread.bigstat .meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: #999;
  grid-column: 2;
  margin-bottom: 24px;
}
.spread.bigstat a {
  font-size: 14px;
  font-weight: 600;
  color: #1A1A1A;
  text-decoration: none;
  grid-column: 2;
  border-bottom: 2px solid var(--gold);
  padding-bottom: 2px;
  display: inline-block;
}

/* ─── SPREAD 8: MAGAZINE OPENER ─── */
.spread.magazine-opener {
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
  color: white;
  padding: 100px 60px;
  display: grid;
  grid-template-rows: auto auto auto auto auto;
  gap: 20px;
  min-height: 600px;
  justify-content: start;
}
.spread.magazine-opener .issue-num {
  font-family: 'Inter', sans-serif;
  font-size: 11px;
  letter-spacing: 0.3em;
  text-transform: uppercase;
  color: rgba(255,255,255,0.4);
}
.spread.magazine-opener h1 {
  font-family: 'Fraunces', serif;
  font-size: clamp(36px, 6vw, 80px);
  font-weight: 800;
  line-height: 1.05;
  color: white;
  max-width: 800px;
}
.spread.magazine-opener .summary {
  font-size: 18px;
  color: rgba(255,255,255,0.65);
  line-height: 1.7;
  max-width: 600px;
}
.spread.magazine-opener .meta {
  display: flex;
  gap: 20px;
  font-size: 13px;
  color: rgba(255,255,255,0.4);
}
.spread.magazine-opener .meta .domain { color: var(--gold); }
.spread.magazine-opener .cta {
  display: inline-block;
  background: white;
  color: #1a1a2e;
  padding: 14px 28px;
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
  align-self: start;
  width: fit-content;
}
.spread.magazine-opener .cta:hover { background: var(--gold); }

/* ─── SPREAD 9: NOIR ─── */
.spread.noir {
  background: var(--charcoal);
  color: white;
  padding: 80px 60px;
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 40px;
  align-items: start;
}
.spread.noir .numeral {
  font-family: 'Fraunces', serif;
  font-size: clamp(100px, 16vw, 200px);
  font-weight: 900;
  color: rgba(255,255,255,0.05);
  line-height: 1;
  user-select: none;
}
.spread.noir h1 {
  font-family: 'Fraunces', serif;
  font-size: clamp(22px, 3.5vw, 44px);
  font-weight: 700;
  line-height: 1.2;
  color: white;
  margin-bottom: 12px;
}
.spread.noir .domain {
  font-size: 11px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: rgba(255,255,255,0.35);
  display: block;
  margin-bottom: 20px;
}
.spread.noir .summary {
  font-size: 17px;
  color: rgba(255,255,255,0.55);
  line-height: 1.7;
  margin-bottom: 28px;
}
.spread.noir .meta {
  display: flex;
  gap: 20px;
  font-size: 12px;
  color: rgba(255,255,255,0.3);
  margin-bottom: 28px;
}
.spread.noir a {
  font-size: 13px;
  font-weight: 500;
  color: white;
  text-decoration: none;
  border-bottom: 1px solid rgba(255,255,255,0.3);
  padding-bottom: 2px;
}
.spread.noir a:hover { border-color: white; }

/* ─── SPREAD 10: INDEX CARD ─── */
.spread.index-card {
  background: #FAFAFA;
  padding: 60px;
  display: grid;
  grid-template-columns: auto 1fr;
  grid-template-rows: auto auto auto;
  gap: 16px 32px;
  align-items: start;
  border: 1px solid #E0E0E0;
}
.spread.index-card .card-num {
  font-family: 'Inter', sans-serif;
  font-size: 11px;
  font-weight: 700;
  color: white;
  background: #1A1A1A;
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  grid-row: 1;
}
.spread.index-card h1 {
  font-family: 'Fraunces', serif;
  font-size: clamp(18px, 2.5vw, 28px);
  font-weight: 700;
  line-height: 1.25;
  color: #1A1A1A;
  grid-column: 2;
  grid-row: 1;
}
.spread.index-card .summary {
  font-size: 15px;
  color: #666;
  line-height: 1.65;
  grid-column: 2;
  grid-row: 2;
}
.spread.index-card .meta {
  grid-column: 1 / 3;
  grid-row: 3;
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: #999;
  flex-wrap: wrap;
  align-items: center;
}
.spread.index-card .meta .domain { color: var(--gold); font-weight: 600; }
.spread.index-card .meta a { color: #555; text-decoration: none; margin-left: auto; font-weight: 600; }
.spread.index-card .meta a:hover { color: #1A1A1A; }

/* ─── Footer ─── */
.footer {
  background: var(--dark);
  color: #555;
  padding: 40px 60px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}
.footer a { color: #888; text-decoration: none; }
.footer a:hover { color: white; }
"""


def get_domain(url: str) -> str:
    if not url:
        return "news.ycombinator.com"
    domain = re.sub(r"^https?://(www\.)?", "", url.split("/")[0] if "/" in url else url)
    return domain.split("?")[0]


def build_magazine(stories: list[dict], date_str: str) -> str:
    today = datetime.date.today().strftime("%B %d, %Y").upper()

    story_blocks = []
    for i, story in enumerate(stories):
        num = i + 1
        layout = LAYOUTS[i % len(LAYOUTS)]
        title = story.get("title", "")
        url = story.get("url", "") or f"https://news.ycombinator.com/item?id={story.get('id')}"
        score = story.get("score", 0)
        comments = story.get("descendants", 0)
        domain = get_domain(story.get("url", ""))
        summary = make_summary(story)

        block = layout.format(
            num=num,
            title=title,
            url=url,
            score=score,
            comments=comments,
            domain=domain,
            summary=summary,
        )
        story_blocks.append(block)

    stories_html = "\n\n".join(story_blocks)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Morning Edition — {date_str}</title>
  <style>
    {LAYOUT_CSS}
  </style>
</head>
<body>

<header class="masthead">
  <div>
    <div class="edition">Morning Edition — {today}</div>
    <h1>Hacker<br><em>News</em></h1>
  </div>
  <div class="tagline">
    Ten stories curated for curious minds.<br>
    No noise. No politics.<br>
    Just good stuff.
  </div>
</header>

<main class="stories">
{stories_html}
</main>

<footer class="footer">
  <span>Morning Edition &mdash; Curated daily from Hacker News</span>
  <a href="https://news.ycombinator.com">Original →</a>
</footer>

</body>
</html>"""
    return html


# ─── Git ────────────────────────────────────────────────────────────────────

def git_commit_push(filename: str, date_str: str) -> bool:
    # Ensure remote uses token auth
    if GITHUB_TOKEN:
        remote_url = f"https://{GITHUB_TOKEN}@github.com/{GIT_USER}/morning-edition.git"
        subprocess.run(["git", "remote", "set-url", "origin", remote_url], cwd=GIT_REPO_DIR, check=False)
    try:
        subprocess.run(["git", "add", filename], cwd=GIT_REPO_DIR, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"Morning Edition {date_str}"],
            cwd=GIT_REPO_DIR,
            check=True,
            env={**os.environ, "GIT_AUTHOR_EMAIL": GIT_EMAIL, "GIT_COMMITTER_EMAIL": GIT_EMAIL},
        )
        subprocess.run(["git", "push", "origin", "master"], cwd=GIT_REPO_DIR, check=True)
        print(f"  [git] committed and pushed {filename}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  [git] error: {e}")
        return False


# ─── Telegram ───────────────────────────────────────────────────────────────

def send_telegram(issue_date: str, stories: list[dict], page_url: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("  [telegram] token or chat_id not set — skipping")
        return False

    # Build highlights (top 3)
    highlights = []
    for s in stories[:3]:
        title = s.get("title", "")[:70]
        score = s.get("score", 0)
        url = s.get("url", "") or f"https://news.ycombinator.com/item?id={s.get('id')}"
        highlights.append(f"• {title} ({score} pts) — {url}")

    intro = (
        f"Morning Edition — {issue_date}\n"
        f"Ten stories, curated for curious minds.\n"
        f"\n"
        f"Top picks today:\n"
    )
    text = intro + "\n".join(highlights) + f"\n\n→ Read the full edition:\n{page_url}"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": False,
    }).encode()

    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
            if resp.get("ok"):
                print(f"  [telegram] sent successfully")
                return True
            else:
                print(f"  [telegram] error: {resp}")
                return False
    except Exception as e:
        print(f"  [telegram] error: {e}")
        return False


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    filename = f"magazines/{date_str}.html"
    filepath = os.path.join(GIT_REPO_DIR, filename)
    page_url = f"{GH_PAGES_URL}/{date_str}.html"

    print(f"\nMorning Edition — {date_str}")
    print("=" * 50)

    # 1. Fetch
    print("Fetching HN top stories...")
    raw = fetch_hn_top(50)
    print(f"  Got {len(raw)} raw stories")

    # 2. Curate
    stories = curate_top10(raw)
    print(f"  Curated to {len(stories)} stories")

    if not stories:
        print("No stories selected — check the filter logic")
        return

    # 3. Build HTML
    print("Building magazine HTML...")
    html = build_magazine(stories, date_str)

    with open(filepath, "w") as f:
        f.write(html)
    print(f"  Saved to {filepath}")

    # 4. Git commit + push
    print("Committing to git...")
    git_commit_push(filename, date_str)

    # 5. Telegram
    print("Sending Telegram notification...")
    send_telegram(date_str, stories, page_url)

    print(f"\nDone! → {page_url}")


if __name__ == "__main__":
    main()
