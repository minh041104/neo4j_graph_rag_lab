"""
Download Wikipedia pages listed in data/wiki_pages.txt into data/wiki_corpus.txt.

Run from project root:
    python src/00_download_wikipedia_corpus.py
"""
from __future__ import annotations

from pathlib import Path
import wikipediaapi

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
PAGES_PATH = DATA_DIR / "wiki_pages.txt"
OUTPUT_PATH = DATA_DIR / "wiki_corpus.txt"


def section_to_text(section, depth: int = 1, max_depth: int = 2) -> str:
    """Recursively collect section text with a small depth limit."""
    parts: list[str] = []

    if section.title and section.text:
        parts.append(f"{'#' * depth} {section.title}\n{section.text}")

    if depth < max_depth:
        for child in section.sections:
            child_text = section_to_text(child, depth + 1, max_depth)
            if child_text:
                parts.append(child_text)

    return "\n\n".join(parts)


def main() -> None:
    if not PAGES_PATH.exists():
        raise FileNotFoundError(f"Missing {PAGES_PATH}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    wiki = wikipediaapi.Wikipedia(
        user_agent="graphrag-neo4j-lab/1.0 (education project)",
        language="en",
        extract_format=wikipediaapi.ExtractFormat.WIKI,
    )

    titles = [
        line.strip()
        for line in PAGES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    documents: list[str] = []
    missing: list[str] = []

    for idx, title in enumerate(titles, start=1):
        print(f"[{idx}/{len(titles)}] Downloading: {title}")
        page = wiki.page(title)

        if not page.exists():
            print(f"  SKIP: page not found: {title}")
            missing.append(title)
            continue

        parts = [page.summary.strip()]
        for section in page.sections:
            text = section_to_text(section, depth=1, max_depth=2)
            if text:
                parts.append(text)

        doc = "\n\n".join([p for p in parts if p])
        documents.append(f"=== PAGE: {page.title} ===\n\n{doc}")

    OUTPUT_PATH.write_text("\n\n".join(documents), encoding="utf-8")

    print(f"\nSaved corpus: {OUTPUT_PATH}")
    print(f"Pages requested: {len(titles)}")
    print(f"Pages saved: {len(documents)}")
    if missing:
        print("Missing pages:", ", ".join(missing))


if __name__ == "__main__":
    main()
