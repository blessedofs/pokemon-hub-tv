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
EPIGUIDE_INDEX_URL = f"{SEREBII_BASE}/anime/epiguide/"
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

def scrape_pokeflix_index() -> dict[str, dict]:
    """
    Index Pokéflix direct video URLs and nearby episode thumbnails from browse pages.
    Returns normalized title -> {"url": ..., "thumbnail": ...}.
    """
    pages = discover_pokeflix_browse_pages()
    print(f"Pokéflix browse pages discovered: {len(pages)}")
    video_map: dict[str, dict] = {}

    def nearby_thumbnail(anchor) -> str | None:
        """
        Find an image in the episode card surrounding a /v/ link.
        Pokéflix browse pages place the thumbnail and WATCH NOW link in the same card.
        """
        node = anchor
        for _ in range(6):
            if node is None:
                break

            imgs = node.find_all("img") if hasattr(node, "find_all") else []
            for img in imgs:
                src = (
                    img.get("data-src")
                    or img.get("data-lazy-src")
                    or img.get("src")
                )
                if src and not src.startswith("data:"):
                    return urljoin(POKEFLIX_BASE, src)

            node = getattr(node, "parent", None)

        return None

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
            if not key:
                continue

            record = {"url": href}
            thumb = nearby_thumbnail(a)
            if thumb:
                record["thumbnail"] = thumb

            # Prefer the first URL found, but upgrade it if a later duplicate
            # has a thumbnail and the first one did not.
            if key not in video_map:
                video_map[key] = record
            elif "thumbnail" not in video_map[key] and thumb:
                video_map[key]["thumbnail"] = thumb

        if idx % 10 == 0 or idx == len(pages):
            print(f"Pokéflix pages: {idx}/{len(pages)}")

    thumb_count = sum(1 for item in video_map.values() if item.get("thumbnail"))
    print(f"Pokéflix direct titles indexed: {len(video_map)}")
    print(f"Pokéflix thumbnails indexed: {thumb_count}")
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

def match_pokeflix(title: str, video_map: dict[str, dict]) -> dict | None:
    key = normalize_title(title)
    if key in video_map:
        return video_map[key]

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


def discover_episode_guide_urls() -> dict[str, str]:
    """
    Build normalized English episode title -> Serebii episode guide URL.
    Serebii's master episode index links the English title directly to each guide.
    """
    html = fetch(EPIGUIDE_INDEX_URL, delay=0.10)
    soup = BeautifulSoup(html, "html.parser")
    guides: dict[str, str] = {}

    for a in soup.find_all("a", href=True):
        title = " ".join(a.stripped_strings).strip()
        href = urljoin(SEREBII_BASE, a["href"])

        if not title:
            continue
        if "/anime/epiguide/" not in href:
            continue
        if href.rstrip("/") == EPIGUIDE_INDEX_URL.rstrip("/"):
            continue
        if "/pics.shtml" in href:
            continue

        key = normalize_title(title)
        if key:
            guides.setdefault(key, href)

    print(f"Serebii episode guide links indexed: {len(guides)}")
    return guides


def extract_short_episode_description(html: str, max_words: int = 22) -> str | None:
    """
    Extract a short teaser from a Serebii episode guide.

    We intentionally keep this very short rather than copying the full guide.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    # Older Serebii guides place the story text directly after this site-use notice.
    markers = [
        "Do Not Translate it into your languange and claim ownership",
        "Do Not Translate it into your language and claim ownership",
        "Do not claim this is yours",
    ]

    story = None
    for marker in markers:
        pos = text.find(marker)
        if pos != -1:
            story = text[pos + len(marker):].strip()
            break

    if not story:
        return None

    # Stop before common metadata / character sections.
    stop_markers = [
        "\nPics\n",
        "\nCharacters\n",
        "\nPokémon\n",
        "\nAsh:",
        "\nMisty:",
        "\nRocket:",
        "\nWild:",
    ]
    for stop in stop_markers:
        idx = story.find(stop)
        if idx != -1:
            story = story[:idx].strip()

    # Collapse whitespace and keep only the opening teaser.
    story = re.sub(r"\s+", " ", story).strip()
    if not story:
        return None

    # Prefer the first sentence, then cap to a short teaser.
    sentence_match = re.match(r"(.+?[.!?])(?:\s|$)", story)
    teaser = sentence_match.group(1) if sentence_match else story

    words = teaser.split()
    if len(words) > max_words:
        teaser = " ".join(words[:max_words]).rstrip(" ,;:-") + "…"

    return teaser


def load_description_cache(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_description_cache(path: Path, cache: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_episode_description(
    title: str,
    guide_index: dict[str, str],
    cache: dict[str, str],
) -> str | None:
    key = normalize_title(title)

    if key in cache:
        return cache[key] or None

    url = guide_index.get(key)
    if not url:
        cache[key] = ""
        return None

    try:
        html = fetch(url, delay=0.08)
        teaser = extract_short_episode_description(html)
    except Exception as exc:
        print(f"[Description] skip {title}: {exc}")
        teaser = None

    cache[key] = teaser or ""
    return teaser

def build(max_dex: int, start: int = 1, description_cache_path: Path | None = None) -> dict[str, list[dict]]:
    species = get_species_names(max_dex)
    print(f"PokéAPI species loaded: {len(species)}")

    pokeflix = scrape_pokeflix_index()

    # Do not silently create a bad database again.
    if len(pokeflix) < 300:
        raise RuntimeError(
            f"Pokéflix index looks wrong: only {len(pokeflix)} direct titles found."
        )

    guide_index = discover_episode_guide_urls()
    description_cache_path = description_cache_path or Path("data/episode-descriptions.json")
    description_cache = load_description_cache(description_cache_path)

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

            description = get_episode_description(
                title,
                guide_index,
                description_cache,
            )
            if description:
                item["description"] = description
            if direct:
                item["watchUrl"] = direct["url"]
                if direct.get("thumbnail"):
                    item["thumbnail"] = direct["thumbnail"]
                direct_matches += 1
            else:
                item["searchUrl"] = f"{POKEFLIX_BASE}/search/"
            episodes.append(item)

        out[species_key] = episodes
        total_rows += len(episodes)
        if episodes:
            pokemon_with_appearances += 1

        if dex_no % 25 == 0 or dex_no == max_dex:
            save_description_cache(description_cache_path, description_cache)
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

    save_description_cache(description_cache_path, description_cache)
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


def write_search_index(data: dict[str, list[dict]], out_file: Path) -> None:
    """
    Build a lightweight, deduplicated search index for homepage searches.
    It contains episode/movie titles, codes, connected Pokémon, and Pokéflix URLs.
    """
    merged: dict[tuple[str, str], dict] = {}

    for species_key, appearances in data.items():
        for item in appearances:
            title = item.get("title", "").strip()
            if not title:
                continue

            episode = str(item.get("episode", ""))
            category = item.get("category", "featured")
            item_type = "movie-special" if category == "movie-special" else "episode"
            key = (episode, title)

            if key not in merged:
                merged[key] = {
                    "episode": episode,
                    "title": title,
                    "type": item_type,
                    "pokemon": [],
                }

                if item.get("watchUrl"):
                    merged[key]["watchUrl"] = item["watchUrl"]
                else:
                    merged[key]["searchUrl"] = item.get(
                        "searchUrl",
                        "https://www.pokeflix.tv/search/",
                    )

                if item.get("thumbnail"):
                    merged[key]["thumbnail"] = item["thumbnail"]

            if species_key not in merged[key]["pokemon"]:
                merged[key]["pokemon"].append(species_key)

            # If any source marks it as a movie/special, preserve that stronger type.
            if item_type == "movie-special":
                merged[key]["type"] = "movie-special"

    records = sorted(
        merged.values(),
        key=lambda x: (x.get("title", "").lower(), x.get("episode", "")),
    )

    out_file.write_text(
        json.dumps(records, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"Wrote search index: {out_file} ({len(records)} titles)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-dex", type=int, default=1025)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--out", default=str(OUT_PATH))
    args = parser.parse_args()

    data = build(args.max_dex, args.start, Path("data/episode-descriptions.json"))
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

    search_file = out_path.parent / "search-index.json"
    write_search_index(data, search_file)


if __name__ == "__main__":
    main()
