#!/usr/bin/env python3
"""
Build data/appearances.json for the Pokémon Hub.

Sources:
- Serebii Animédex: Pokémon -> anime episode appearances
- Pokéflix: episode title -> direct watch URL when an exact title match is found

This script is intentionally rate-limited. It is designed to be run manually
from GitHub Actions, not on every page load.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

SEREBII_BASE = "https://www.serebii.net"
POKEFLIX_BASE = "https://www.pokeflix.tv"
OUT_PATH = Path("data/appearances.json")

UA = (
    "PokemonHubTV/1.0 "
    "(GitHub Pages fan project; low-rate public-page indexer)"
)

session = requests.Session()
session.headers.update({"User-Agent": UA})

def fetch(url: str, delay: float = 0.35, retries: int = 3) -> str:
    last = None
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
            time.sleep(delay)
            return r.text
        except Exception as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {last}")

def normalize_title(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.replace("’", "'").replace("‘", "'").replace("–", "-").replace("—", "-")
    text = text.lower().strip()
    text = re.sub(r"^\\d+\\s*[-–:]\\s*", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\\s+", " ", text).strip()

def scrape_pokeflix_index() -> dict[str, dict]:
    """
    Crawl Pokéflix browse pages reachable from its index and specials pages,
    returning normalized English episode/movie title -> direct URL.
    """
    seed_urls = [
        f"{POKEFLIX_BASE}/index/",
        f"{POKEFLIX_BASE}/specials/",
    ]
    browse_urls = set()
    video_map: dict[str, dict] = {}

    # Discover browse pages.
    for seed in seed_urls:
        html = fetch(seed, delay=0.20)
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = urljoin(POKEFLIX_BASE, a["href"])
            if "/browse/" in href:
                browse_urls.add(href.split("#")[0])

    # Include search page because it sometimes contains direct video links.
    browse_urls.add(f"{POKEFLIX_BASE}/search/")

    print(f"Pokéflix browse pages discovered: {len(browse_urls)}")

    # Crawl all discovered browse pages and collect direct /v/ links.
    for idx, url in enumerate(sorted(browse_urls), 1):
        try:
            html = fetch(url, delay=0.20)
        except Exception as exc:
            print(f"[Pokéflix] skip {url}: {exc}")
            continue

        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = urljoin(POKEFLIX_BASE, a["href"])
            if "/v/" not in href:
                continue

            # Anchor text is not always the title, so inspect nearby content.
            title = " ".join(a.stripped_strings).strip()
            if not title:
                parent = a.parent
                if parent:
                    title = " ".join(parent.stripped_strings).strip()

            # Clean common CTA text.
            title = re.sub(r"\\bWATCH NOW\\b", "", title, flags=re.I).strip()
            title = re.sub(r"^\\d+\\s*[-–]\\s*", "", title).strip()

            if not title or len(title) > 180:
                # Derive a fallback title from the slug.
                slug = href.rstrip("/").split("/v/")[-1]
                slug = re.sub(r"^\\d{2}-", "", slug)
                title = slug.replace("-", " ").strip()

            key = normalize_title(title)
            if key:
                video_map.setdefault(
                    key,
                    {"title": title, "url": href.rstrip("/")},
                )

        if idx % 10 == 0:
            print(f"  Pokéflix pages: {idx}/{len(browse_urls)}")

    print(f"Pokéflix direct titles indexed: {len(video_map)}")
    return video_map

def episode_rows_from_serebii(html: str) -> list[tuple[str, str]]:
    """
    Extract (episode code, English title) pairs from Serebii Animédex tables.
    Handles standard episodes, movies, specials, shorts, and Horizons numbering.
    """
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        table_text = " ".join(table.stripped_strings)
        if "English Episode Name" not in table_text:
            continue

        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            code = " ".join(cells[0].stripped_strings).strip()
            title = " ".join(cells[1].stripped_strings).strip()

            if not code or not title:
                continue
            if "English Episode Name" in title or code == "#":
                continue

            # Valid Serebii codes include 29, 1225, M2, P1, S23, PLA1, etc.
            if not re.fullmatch(r"[A-Za-z]*\\d+[A-Za-z0-9-]*", code):
                continue

            title = re.sub(r"\\s+", " ", title).strip()
            key = (code, title)
            if key not in seen:
                seen.add(key)
                found.append(key)

    return found

def pokemon_name_from_page(html: str, dex_no: int) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    # Serebii pages contain a prominent heading like "#0107 Hitmonchan".
    text = " ".join(soup.stripped_strings)
    m = re.search(rf"#0*{dex_no}\\s+([A-Za-z0-9:' .♀♂-]+)", text)
    if m:
        raw = m.group(1).strip()
        # Stop before common following labels.
        raw = re.split(r"\\s+(?:Gen|Image|Special|Wild|Picture|Name)\\b", raw)[0].strip()
        if raw:
            return raw

    # Fallback from title.
    if soup.title:
        title = soup.title.get_text(" ", strip=True)
        m = re.search(r"Animédex\\s*-\\s*#?\\d+\\s+(.+?)(?:\\s*\\||$)", title, re.I)
        if m:
            return m.group(1).strip()

    return None

def slugify_species(name: str) -> str:
    # Map display names to PokéAPI-style species names.
    replacements = {
        "Nidoran♀": "nidoran-f",
        "Nidoran♂": "nidoran-m",
        "Mr. Mime": "mr-mime",
        "Mime Jr.": "mime-jr",
        "Mr. Rime": "mr-rime",
        "Type: Null": "type-null",
        "Farfetch'd": "farfetchd",
        "Sirfetch'd": "sirfetchd",
        "Flabébé": "flabebe",
        "Porygon-Z": "porygon-z",
        "Jangmo-o": "jangmo-o",
        "Hakamo-o": "hakamo-o",
        "Kommo-o": "kommo-o",
        "Wo-Chien": "wo-chien",
        "Chien-Pao": "chien-pao",
        "Ting-Lu": "ting-lu",
        "Chi-Yu": "chi-yu",
    }
    if name in replacements:
        return replacements[name]

    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    ascii_name = ascii_name.lower().replace("'", "")
    ascii_name = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")
    return ascii_name

def build(max_dex: int, start: int = 1) -> dict[str, list[dict]]:
    pokeflix = scrape_pokeflix_index()
    out: dict[str, list[dict]] = {}

    total_appearances = 0
    direct_matches = 0

    for dex_no in range(start, max_dex + 1):
        url = f"{SEREBII_BASE}/anime/dex/{dex_no:03d}.shtml"
        try:
            html = fetch(url, delay=0.35)
        except Exception as exc:
            print(f"[Serebii] #{dex_no:04d} skipped: {exc}")
            continue

        name = pokemon_name_from_page(html, dex_no)
        if not name:
            print(f"[Serebii] #{dex_no:04d} name not found")
            continue

        species_key = slugify_species(name)
        rows = episode_rows_from_serebii(html)
        episodes = []

        for code, title in rows:
            norm = normalize_title(title)
            matched = pokeflix.get(norm)

            item = {
                "series": "Pokémon Anime",
                "episode": code,
                "title": title,
                "sourceUrl": url,
            }

            if matched:
                item["watchUrl"] = matched["url"]
                direct_matches += 1
            else:
                # Keep the appearance even when a direct Pokéflix match is not
                # available. The site will show a Pokéflix search button.
                item["searchUrl"] = f"{POKEFLIX_BASE}/search/"

            episodes.append(item)

        out[species_key] = episodes
        total_appearances += len(episodes)

        if dex_no % 25 == 0 or dex_no == max_dex:
            print(
                f"Serebii #{dex_no}/{max_dex} | "
                f"appearances={total_appearances} | "
                f"direct Pokéflix matches={direct_matches}"
            )

    print(f"Pokémon keys: {len(out)}")
    print(f"Total appearance rows: {total_appearances}")
    print(f"Direct Pokéflix links: {direct_matches}")
    return out

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-dex", type=int, default=1025)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--out", default=str(OUT_PATH))
    args = parser.parse_args()

    data = build(args.max_dex, args.start)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {out_path}")

if __name__ == "__main__":
    main()
