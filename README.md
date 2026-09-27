# Pokémon Hub

A lightweight GitHub Pages-ready Pokémon character hub.

## What works now

- Search by Pokémon name or Pokédex number.
- Dynamic Pokémon profile pages powered by PokéAPI.
- Official artwork, type, generation, region, height, weight, abilities and description.
- Evolution line.
- Anime appearance cards.
- Direct "Watch on Pokéflix" links.
- Hitmonchan is the first Pokémon with a verified anime appearance entry.

## Run it locally

Because the site loads `data/appearances.json`, use a small local web server rather than opening the HTML file directly.

Python:
```bash
python -m http.server 8000
```

Then open:
`http://localhost:8000`

## GitHub Pages

Upload the contents of this folder to a GitHub repository. In the repository:
Settings → Pages → Deploy from a branch → `main` / root.

Then the site works at your GitHub Pages address.

## Add anime appearances

Edit `data/appearances.json`.

Example:
```json
"hitmonchan": [
  {
    "series": "Indigo League",
    "episode": 29,
    "title": "The Punchy Pokémon",
    "note": "A short note.",
    "watchUrl": "https://www.pokeflix.tv/v/01-the-punchy-pokemon"
  }
]
```

The Pokémon page automatically displays entries whose key matches the PokéAPI Pokémon name.
