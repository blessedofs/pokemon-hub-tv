#!/usr/bin/env python3
"""
Build data/appearances.json for Pokémon Hub.

Fixes:
- Pokémon names come from PokéAPI instead of being parsed from Serebii HTML.
- Pokéflix episode URLs are indexed from /v/ href slugs, not anchor text.
- The build fails loudly if the scrape returns suspiciously little data.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

SEREBII_BASE = "https://www.serebii.net"
POKEAPI = "https://pokeapi.co/api/v2"
POKEFLIX_BASE = "https://www.pokeflix.tv"
OUT_PATH = Path("data/appearances.json")

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 PokemonHubTV/1.1",
    "Accept-Language": "en-US,en;q=0.9",
})

def fetch(url: str, delay: float = 0.18, retries: int = 3) -> str:
    last = None
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
            time.sleep(delay)
            return r.text
        except Exception as exc:
            last = exc
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {last}")

def fetch_json(url: str):
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return r.json()

def normalize_title(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.replace("’", "'").replace("‘", "'").replace("–", "-").replace("—", "-")
    text = text.lower().strip()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def pokeflix_title_from_href(href: str) -> str:
    slug = href.rstrip("/").split("/v/")[-1]
    # Pokéflix uses prefixes such as 01-, 02-, etc. in many video slugs.
    slug = re.sub(r"^\d{1,3}-", "", slug)
    return slug.replace("-", " ").strip()

def get_species_names(max_dex: int) -> dict[int, str]:
    # PokéAPI's species list is ordered by species ID.
    data = fetch_json(f"{POKEAPI}/pokemon-species?limit={max_dex}&offset=0")
    out = {}
    for item in data["results"]:
        m = re.search(r"/pokemon-species/(\d+)/", item["url"])
        if not m:
            continue
        dex_id = int(m.group(1))
        if dex_id <= max_dex:
            out[dex_id] = item["name"]
    return out

def discover_pokeflix_browse_pages() -> set[str]:
    pages = set()
    for seed in (f"{POKEFLIX_BASE}/index/", f"{POKEFLIX_BASE}/"):
        try:
            html = fetch(seed, delay=0.10)
        except Exception:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = urljoin(POKEFLIX_BASE, a["href"])
            if "/browse/" in href:
                pages.add(href.split("#")[0].rstrip("/"))
    return pages

def scrape_pokeflix_index() -> dict[str, str]:
    pages = discover_pokeflix_browse_pages()
    print(f"Pokéflix browse pages discovered: {len(pages)}")
    video_map: dict[str, str] = {}

    for idx, url in enumerate(sorted(pages), 1):
        try:
            html = fetch(url, delay=0.10)
        except Exception as exc:
            print(f"[Pokéflix] skip {url}: {exc}")
            continue

        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = urljoin(POKEFLIX_BASE, a["href"]).rstrip("/")
            if "/v/" not in href:
                continue

            title_guess = pokeflix_title_from_href(href)
            key = normalize_title(title_guess)
            if key:
                video_map.setdefault(key, href)

        if idx % 10 == 0 or idx == len(pages):
            print(f"Pokéflix pages: {idx}/{len(pages)}")

    print(f"Pokéflix direct titles indexed: {len(video_map)}")
    return video_map

def extract_episode_rows(html: str) -> list[tuple[str, str]]:
    """
    Pull every Serebii Animédex appearance row.

    The page has many tables, each with columns:
      # | English Episode Name | Japanese Episode Name | Pics
    """
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()

    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue

        code = " ".join(cells[0].stripped_strings).strip()
        title = " ".join(cells[1].stripped_strings).strip()

        if not code or not title:
            continue
        if "English Episode Name" in title or code == "#":
            continue

        # Examples include 10, 108, M01, S01, etc.
        if not re.fullmatch(r"[A-Za-z]*\d+[A-Za-z0-9-]*", code):
            continue

        title = re.sub(r"\s+", " ", title).strip()
        key = (code, title)
        if key not in seen:
            seen.add(key)
            found.append(key)

    return found

def match_pokeflix(title: str, video_map: dict[str, str]) -> str | None:
    key = normalize_title(title)
    if key in video_map:
        return video_map[key]

    # Handle a few common wording differences.
    variants = {
        key.replace(" versus ", " vs "): None,
        key.replace(" vs ", " versus "): None,
        key.replace(" pokemon ", " pokémon "): None,
    }
    for variant in variants:
        variant = normalize_title(variant)
        if variant in video_map:
            return video_map[variant]

    return None


def classify_appearance(code: str, title: str) -> str:
    """
    Heuristic appearance category:
    - movie/special: movie/special/OVA-style codes or titles
    - cameo: titles explicitly marked cameo/brief/flashback
    - featured: everything else
    """
    code_upper = code.upper()

    if (
        code_upper.startswith(("M", "S", "P", "OVA", "PLA"))
        or "movie" in title.lower()
        or "special" in title.lower()
    ):
        return "movie-special"

    cameo_words = (
        "cameo",
        "brief appearance",
        "flashback",
        "montage",
        "photo",
    )
    low = title.lower()
    if any(word in low for word in cameo_words):
        return "cameo"

    return "featured"

def build(max_dex: int, start: int = 1) -> dict[str, list[dict]]:
    species = get_species_names(max_dex)
    print(f"PokéAPI species loaded: {len(species)}")

    pokeflix = scrape_pokeflix_index()

    # Do not silently create a bad database again.
    if len(pokeflix) < 300:
        raise RuntimeError(
            f"Pokéflix index looks wrong: only {len(pokeflix)} direct titles found."
        )

    out: dict[str, list[dict]] = {}
    total_rows = 0
    pokemon_with_appearances = 0
    direct_matches = 0

    for dex_no in range(start, max_dex + 1):
        species_key = species.get(dex_no)
        if not species_key:
            print(f"[PokéAPI] #{dex_no:04d} species missing")
            continue

        url = f"{SEREBII_BASE}/anime/dex/{dex_no:03d}.shtml"
        try:
            html = fetch(url, delay=0.20)
        except Exception as exc:
            print(f"[Serebii] #{dex_no:04d} skipped: {exc}")
            out[species_key] = []
            continue

        rows = extract_episode_rows(html)
        episodes = []

        for code, title in rows:
            direct = match_pokeflix(title, pokeflix)
            item = {
                "series": "Pokémon Anime",
                "episode": code,
                "title": title,
                "sourceUrl": url,
                "category": classify_appearance(code, title),
            }
            if direct:
                item["watchUrl"] = direct
                direct_matches += 1
            else:
                item["searchUrl"] = f"{POKEFLIX_BASE}/search/"
            episodes.append(item)

        out[species_key] = episodes
        total_rows += len(episodes)
        if episodes:
            pokemon_with_appearances += 1

        if dex_no % 25 == 0 or dex_no == max_dex:
            print(
                f"#{dex_no}/{max_dex} | species with appearances={pokemon_with_appearances} "
                f"| rows={total_rows} | direct Pokéflix={direct_matches}"
            )

    # Sanity checks. If these fail, GitHub Actions turns red instead of committing junk.
    if pokemon_with_appearances < 300:
        raise RuntimeError(
            f"Appearance scrape looks wrong: only {pokemon_with_appearances} Pokémon "
            "had any episode rows."
        )
    if total_rows < 3000:
        raise RuntimeError(
            f"Appearance scrape looks wrong: only {total_rows} total rows found."
        )

    print(f"Final Pokémon keys: {len(out)}")
    print(f"Pokémon with appearances: {pokemon_with_appearances}")
    print(f"Total appearance rows: {total_rows}")
    print(f"Direct Pokéflix links: {direct_matches}")
    return out


def write_split_files(data: dict[str, list[dict]], base_dir: Path) -> None:
    """
    Write one small JSON file per Pokémon so the website only downloads
    the selected Pokémon's anime appearances.
    """
    base_dir.mkdir(parents=True, exist_ok=True)

    # Remove old generated JSON files so stale Pokémon data cannot linger.
    for old_file in base_dir.glob("*.json"):
        old_file.unlink()

    for species_key, appearances in data.items():
        out_file = base_dir / f"{species_key}.json"
        out_file.write_text(
            json.dumps(appearances, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    print(f"Wrote {len(data)} split Pokémon appearance files to {base_dir}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-dex", type=int, default=1025)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--out", default=str(OUT_PATH))
    args = parser.parse_args()

    data = build(args.max_dex, args.start)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Keep the master database as a backup/reference file.
    out_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote master database: {out_path}")

    # Website-optimized files: one small JSON file per Pokémon.
    split_dir = out_path.parent / "appearances"
    write_split_files(data, split_dir)


if __name__ == "__main__":
    main()

