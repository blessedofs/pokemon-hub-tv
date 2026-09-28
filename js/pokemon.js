const API = "https://pokeapi.co/api/v2";

const params = new URLSearchParams(window.location.search);
const requestedPokemon = (params.get("name") || "hitmonchan").toLowerCase();

const $ = (id) => document.getElementById(id);

const titleCase = (value) =>
  value
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");

const formatGeneration = (value) => {
  const roman = value.replace("generation-", "").toUpperCase();
  return `Generation ${roman}`;
};

const generationRegion = {
  "generation-i": "Kanto",
  "generation-ii": "Johto",
  "generation-iii": "Hoenn",
  "generation-iv": "Sinnoh",
  "generation-v": "Unova",
  "generation-vi": "Kalos",
  "generation-vii": "Alola",
  "generation-viii": "Galar / Hisui",
  "generation-ix": "Paldea"
};

function getEnglishFlavor(species) {
  const entries = species.flavor_text_entries.filter(
    (entry) => entry.language.name === "en"
  );
  if (!entries.length) return "Pokédex description unavailable.";
  return entries[entries.length - 1].flavor_text.replace(/\f|\n|\r/g, " ");
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return response.json();
}

function flattenEvolutionChain(chain, output = []) {
  output.push(chain.species.name);
  chain.evolves_to.forEach((child) => flattenEvolutionChain(child, output));
  return output;
}

async function renderEvolution(species) {
  const container = $("evolutionLine");
  const evolutionData = await getJson(species.evolution_chain.url);
  const names = flattenEvolutionChain(evolutionData.chain);

  container.innerHTML = "";

  names.forEach((name, index) => {
    const speciesIdMatch = evolutionData.chain; // placeholder to keep rendering simple
    const card = document.createElement("a");
    card.className = "evo-card";
    card.href = `pokemon.html?name=${encodeURIComponent(name)}`;

    const img = document.createElement("img");
    img.alt = titleCase(name);
    img.loading = "lazy";

    // Resolve the artwork via the Pokémon endpoint so branching families stay accurate.
    getJson(`${API}/pokemon/${name}`)
      .then((data) => {
        img.src =
          data.sprites.other["official-artwork"].front_default ||
          data.sprites.front_default ||
          "";
      })
      .catch(() => {
        img.remove();
      });

    const label = document.createElement("strong");
    label.textContent = titleCase(name);

    card.append(img, label);
    container.append(card);

    if (index < names.length - 1) {
      const arrow = document.createElement("span");
      arrow.className = "evo-arrow";
      arrow.textContent = "→";
      container.append(arrow);
    }
  });
}

async function renderAppearances(pokemonName) {
  try {
    const response = await fetch("data/appearances.json");
    if (!response.ok) throw new Error();
    const database = await response.json();
    const appearances = database[pokemonName] || [];

    if (!appearances.length) {
      $("appearanceCount").textContent = "0 added";
      $("noAppearances").classList.remove("hidden");
      return;
    }

    $("appearanceCount").textContent =
      `${appearances.length} ${appearances.length === 1 ? "appearance" : "appearances"}`;

    const list = $("appearanceList");
    list.innerHTML = "";

    const batchSize = 10;
    let visibleCount = 0;

    const renderBatch = () => {
      const nextBatch = appearances.slice(visibleCount, visibleCount + batchSize);

      nextBatch.forEach((episode) => {
        const card = document.createElement("article");
        card.className = "episode-card";

        const targetUrl = episode.watchUrl || episode.searchUrl || "https://www.pokeflix.tv/search/";
        const buttonText = episode.watchUrl ? "Watch on Pokéflix ↗" : "Find on Pokéflix ↗";
        const episodeLabel = episode.episode ? `Episode ${episode.episode}` : "Anime appearance";

        card.innerHTML = `
          <div class="episode-poster" aria-hidden="true">
            <div>
              <div class="tv">📺</div>
              <small>${episode.series || "Pokémon Anime"}</small>
            </div>
          </div>
          <div class="episode-body">
            <div class="episode-meta">${episode.series || "Pokémon Anime"} · ${episodeLabel}</div>
            <h3>${episode.title}</h3>
            <p>${episode.note || "Featuring this Pokémon in the anime."}</p>
            <a class="watch-button"
               href="${targetUrl}"
               target="_blank"
               rel="noopener noreferrer">${buttonText}</a>
          </div>
        `;
        list.append(card);
      });

      visibleCount += nextBatch.length;

      let moreButton = document.getElementById("showMoreAppearances");
      if (moreButton) moreButton.remove();

      if (visibleCount < appearances.length) {
        moreButton = document.createElement("button");
        moreButton.id = "showMoreAppearances";
        moreButton.className = "show-more-button";
        moreButton.type = "button";
        moreButton.textContent = `Show 10 more (${appearances.length - visibleCount} remaining)`;
        moreButton.addEventListener("click", renderBatch);
        list.insertAdjacentElement("afterend", moreButton);
      }
    };

    renderBatch();
  } catch {
    $("appearanceCount").textContent = "Unavailable";
    $("noAppearances").classList.remove("hidden");
  }
}

async function init() {
  try {
    const [pokemon, species] = await Promise.all([
      getJson(`${API}/pokemon/${encodeURIComponent(requestedPokemon)}`),
      getJson(`${API}/pokemon-species/${encodeURIComponent(requestedPokemon)}`)
    ]);

    const name = titleCase(pokemon.name);
    document.title = `${name} #${pokemon.id} | Pokémon Hub`;

    $("pokemonName").textContent = name;
    $("dexNumber").textContent = `#${String(pokemon.id).padStart(4, "0")}`;
    $("generation").textContent = formatGeneration(species.generation.name);
    $("region").textContent = generationRegion[species.generation.name] || "Unknown";
    $("description").textContent = getEnglishFlavor(species);

    $("pokemonArt").src =
      pokemon.sprites.other["official-artwork"].front_default ||
      pokemon.sprites.front_default;
    $("pokemonArt").alt = `${name} official artwork`;

    $("height").textContent = `${(pokemon.height / 10).toFixed(1)} m`;
    $("weight").textContent = `${(pokemon.weight / 10).toFixed(1)} kg`;
    $("abilities").textContent = pokemon.abilities
      .map((entry) => titleCase(entry.ability.name))
      .join(", ");

    $("types").innerHTML = pokemon.types
      .map((entry) => `<span class="type-pill">${titleCase(entry.type.name)}</span>`)
      .join("");

    await Promise.all([
      renderEvolution(species),
      renderAppearances(pokemon.name)
    ]);

    $("loadingState").classList.add("hidden");
    $("profile").classList.remove("hidden");
  } catch (error) {
    console.error(error);
    $("loadingState").classList.add("hidden");
    $("errorState").classList.remove("hidden");
  }
}

init();
