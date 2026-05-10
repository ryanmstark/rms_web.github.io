"""
Daily flashcard generator.

Generates 5 topic-specific flashcards using Groq API and writes them to
flashcards/index.html for serving via GitHub Pages.
"""

import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from groq import Groq

OUTPUT_PATH = Path(__file__).parent.parent.parent / "flashcards" / "index.html"

TOPICS = [
    {
        "id": "ee_comms",
        "label": "EE · Comms & Space",
        "color": "#0d47a1",
        "light": "#e8f0fe",
        "rss": [
            "https://spacenews.com/feed/",
            "https://www.eetimes.com/rss/",
        ],
        "prompt": (
            "You are an expert electrical engineer specializing in communications systems "
            "and space technology. Write a flashcard about a recent or notable development "
            "in RF communications, satellite systems, phased arrays, link budgets, orbital "
            "mechanics, or space missions. Use headlines for inspiration if provided. "
            "Assume the reader has an MS in EE."
        ),
    },
    {
        "id": "ee_core",
        "label": "EE · Core Concepts",
        "color": "#1565c0",
        "light": "#e3f2fd",
        "rss": [],
        "prompt": (
            "You are an expert electrical engineer. Write a flashcard on a specific, "
            "non-trivial concept from signal processing, analog/RF circuit design, "
            "control systems, power electronics, or electromagnetics. Topics should rotate "
            "across the subdisciplines and should not repeat obvious fundamentals. "
            "Include equations or quantitative reasoning where helpful. "
            "Assume the reader has an MS in EE."
        ),
    },
    {
        "id": "news",
        "label": "News",
        "color": "#c62828",
        "light": "#ffebee",
        "rss": [
            "https://feeds.reuters.com/reuters/topNews",
            "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
        ],
        "prompt": (
            "You are a clear-eyed journalist. Write a flashcard summarizing one important "
            "current event or geopolitical development. Present facts neutrally. "
            "Use the provided headlines as your source material — pick the most substantive "
            "story. Avoid opinion. Explain why the story matters."
        ),
    },
    {
        "id": "history",
        "label": "History",
        "color": "#4a148c",
        "light": "#f3e5f5",
        "rss": [],
        "prompt": (
            "You are a historian specializing in US and world history from WW1 to the present. "
            "Write a flashcard on a specific, illuminating historical event, decision, or figure "
            "from this era. Choose topics that reveal how the modern world was shaped. "
            "Be specific — name dates, people, and consequences. Rotate through different eras "
            "and regions across flashcards."
        ),
    },
    {
        "id": "ai",
        "label": "AI & Tools",
        "color": "#00695c",
        "light": "#e0f2f1",
        "rss": [
            "https://feeds.feedburner.com/blogspot/gJZg",
        ],
        "prompt": (
            "You are an AI researcher and practitioner. Write a flashcard about a specific "
            "AI technique, recent model development, research result, or practical tool "
            "relevant to engineers. Topics can include transformer architectures, training "
            "methods, inference optimization, agent frameworks, or evaluation approaches. "
            "Be technically precise. Assume the reader can read Python and understands ML basics."
        ),
    },
]

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: monospace;
  background: #f8f8f8;
  color: #111;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

header {
  background: #111;
  color: #fff;
  padding: 14px 20px;
  display: flex;
  align-items: center;
  gap: 16px;
}
header a { color: #aaa; text-decoration: none; font-size: 0.85rem; }
header a:hover { color: #fff; }
header h1 { font-size: 1rem; }
.generated-at { margin-left: auto; font-size: 0.75rem; color: #666; }

main {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 32px 16px 48px;
  max-width: 720px;
  width: 100%;
  margin: 0 auto;
}

.deck-nav {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 24px;
  width: 100%;
  justify-content: center;
}

.dot {
  width: 10px; height: 10px; border-radius: 50%;
  background: #ccc;
  cursor: pointer;
  border: none;
  padding: 0;
  transition: background 0.15s;
}
.dot.active { background: var(--cc); }

.card {
  width: 100%;
  background: #fff;
  border: 1px solid #ddd;
  border-top: 5px solid var(--cc);
  padding: 28px 28px 24px;
  display: none;
}
.card.visible { display: block; }

.card-label {
  font-size: 0.7rem;
  font-weight: bold;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--cc);
  margin-bottom: 10px;
}

.card h2 {
  font-size: 1.1rem;
  margin-bottom: 18px;
  line-height: 1.4;
}

.card-body p {
  font-size: 0.875rem;
  line-height: 1.65;
  color: #222;
  margin-bottom: 12px;
}
.card-body p:last-child { margin-bottom: 0; }

.card-sources {
  margin-top: 20px;
  padding-top: 14px;
  border-top: 1px solid #eee;
  font-size: 0.75rem;
  color: #777;
}
.card-sources strong { color: #444; }
.card-sources a { color: #555; text-decoration: underline; }
.card-sources a:hover { color: #000; }

.prev-next {
  display: flex;
  gap: 12px;
  margin-top: 20px;
  width: 100%;
}
.prev-next button {
  flex: 1;
  padding: 10px;
  font-family: monospace;
  font-size: 0.9rem;
  background: #111;
  color: #fff;
  border: none;
  cursor: pointer;
}
.prev-next button:hover { background: #333; }
.prev-next button:disabled { background: #ccc; cursor: default; }

@media (max-width: 480px) {
  .card { padding: 20px 18px 18px; }
}
"""

_JS = """
const cards = document.querySelectorAll('.card');
const dots  = document.querySelectorAll('.dot');
const prevBtn = document.getElementById('prev-btn');
const nextBtn = document.getElementById('next-btn');
let current = 0;

function show(idx) {
  cards.forEach((c, i) => c.classList.toggle('visible', i === idx));
  dots.forEach((d, i)  => d.classList.toggle('active',  i === idx));
  prevBtn.disabled = idx === 0;
  nextBtn.disabled = idx === cards.length - 1;
  current = idx;
}

dots.forEach((d, i) => d.addEventListener('click', () => show(i)));
prevBtn.addEventListener('click', () => { if (current > 0) show(current - 1); });
nextBtn.addEventListener('click', () => { if (current < cards.length - 1) show(current + 1); });

show(0);
"""


def fetch_headlines(urls: list[str], limit: int = 8) -> list[str]:
    """
    Fetches RSS feeds and returns up to `limit` headline strings.

    Parameters
    ----------
    urls : list[str]
        RSS feed URLs to try, in order.
    limit : int
        Max total headlines to return across all feeds.
    """
    headlines: list[str] = []
    for url in urls:
        if len(headlines) >= limit:
            break
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "flashcard-bot/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                body = resp.read()
            root = ET.fromstring(body)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            # RSS 2.0
            for item in root.iter("item"):
                title = item.findtext("title", "").strip()
                if title:
                    headlines.append(title)
                if len(headlines) >= limit:
                    break
            # Atom
            if not headlines:
                for entry in root.findall("atom:entry", ns):
                    title_el = entry.find("atom:title", ns)
                    if title_el is not None and title_el.text:
                        headlines.append(title_el.text.strip())
                    if len(headlines) >= limit:
                        break
        except Exception:
            pass
    return headlines[:limit]


def generate_card(client: Groq, topic: dict, headlines: list[str], today: str) -> dict:
    """
    Calls Groq to generate one flashcard for the given topic.

    Parameters
    ----------
    client : Groq
        Initialized Groq client.
    topic : dict
        Topic config dict from TOPICS.
    headlines : list[str]
        Recent headlines for context (may be empty).
    today : str
        ISO date string for grounding the prompt.

    Returns
    -------
    dict
        Parsed card dict with keys: id, title, body (list of str), sources (list of dicts).
    """
    headline_block = ""
    if headlines:
        headline_block = "\n\nRecent headlines for context:\n" + "\n".join(f"- {h}" for h in headlines)

    system = topic["prompt"]
    user = (
        f"Today is {today}. Generate exactly ONE flashcard in this JSON format:\n\n"
        '{"id": "<topic_id>", "title": "<specific descriptive title>", '
        '"body": ["<paragraph 1>", "<paragraph 2>", ...], '
        '"sources": [{"name": "<source name>", "url": "<url>"}]}\n\n'
        "Requirements:\n"
        "- title: specific and informative (not generic)\n"
        "- body: 2-5 paragraphs, technically accurate, self-contained\n"
        "- sources: 1-3 real, reputable sources with real URLs\n"
        f'- id field must be: "{topic["id"]}"\n'
        "- respond with ONLY the JSON object, no markdown fences"
        + headline_block
    )

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=2000,
        temperature=0.72,
    )

    raw = response.choices[0].message.content.strip()
    # Strip markdown fences if model adds them anyway
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return json.loads(raw)


def _card_html(card: dict, topic: dict, idx: int, total: int) -> str:
    """
    Renders a single flashcard as an HTML string.

    Parameters
    ----------
    card : dict
        Card data with title, body, sources.
    topic : dict
        Topic config for color and label.
    idx : int
        Zero-based card index (for visibility toggle).
    total : int
        Total number of cards (unused currently, kept for future use).
    """
    visible = " visible" if idx == 0 else ""
    paragraphs = "".join(f"<p>{p}</p>" for p in card.get("body", []))

    sources_html = ""
    sources = card.get("sources", [])
    if sources:
        links = ", ".join(
            f'<a href="{s["url"]}" target="_blank" rel="noopener">{s["name"]}</a>'
            for s in sources
        )
        sources_html = f'<div class="card-sources"><strong>Sources:</strong> {links}</div>'

    return (
        f'<div class="card{visible}" style="--cc:{topic["color"]};--cl:{topic["light"]}">\n'
        f'  <div class="card-label">{topic["label"]}</div>\n'
        f'  <h2>{card.get("title", "")}</h2>\n'
        f'  <div class="card-body">{paragraphs}</div>\n'
        f'  {sources_html}\n'
        f'</div>\n'
    )


def build_html(cards_with_topics: list[tuple[dict, dict]], generated_at: str) -> str:
    """
    Assembles the full flashcards page HTML.

    Parameters
    ----------
    cards_with_topics : list[tuple[dict, dict]]
        List of (card_data, topic_config) pairs.
    generated_at : str
        Human-readable generation timestamp string.
    """
    dots = "".join(
        f'<button class="dot{" active" if i == 0 else ""}" '
        f'style="--cc:{topic["color"]}" aria-label="Card {i+1}"></button>\n'
        for i, (_, topic) in enumerate(cards_with_topics)
    )

    cards_html = "".join(
        _card_html(card, topic, i, len(cards_with_topics))
        for i, (card, topic) in enumerate(cards_with_topics)
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Daily Flashcards</title>
  <style>{_CSS}</style>
</head>
<body>
  <header>
    <a href="/">← Home</a>
    <h1>Daily Flashcards</h1>
    <span class="generated-at">Generated {generated_at}</span>
  </header>
  <main>
    <div class="deck-nav">
      {dots}
    </div>
    {cards_html}
    <div class="prev-next">
      <button id="prev-btn" disabled>← Prev</button>
      <button id="next-btn">Next →</button>
    </div>
  </main>
  <script>{_JS}</script>
</body>
</html>
"""


def main() -> None:
    """Entry point: fetch RSS, generate cards via Groq, write index.html."""
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    generated_at = datetime.now(timezone.utc).strftime("%B %-d, %Y at %H:%M UTC")

    cards_with_topics: list[tuple[dict, dict]] = []
    for topic in TOPICS:
        headlines = fetch_headlines(topic["rss"]) if topic["rss"] else []
        card = generate_card(client, topic, headlines, today)
        cards_with_topics.append((card, topic))
        print(f"  [{topic['id']}] {card.get('title', '(no title)')}")

    html = build_html(cards_with_topics, generated_at)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
