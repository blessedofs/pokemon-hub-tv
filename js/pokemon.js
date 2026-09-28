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
    const response = await fetch(
      `data/appearances/${encodeURIComponent(pokemonName)}.json`
    );

    if (response.status === 404) {
      $("appearanceCount").textContent = "0 added";
      $("noAppearances").classList.remove("hidden");
      return;
    }

    if (!response.ok) throw new Error();

    const appearances = await response.json();

    if (!appearances.length) {
      $("appearanceCount").textContent = "0 added";
      $("noAppearances").classList.remove("hidden");
      return;
    }

    $("appearanceCount").textContent =
      `${appearances.length} ${appearances.length === 1 ? "appearance" : "appearances"}`;

    const list = $("appearanceList");
    list.innerHTML = "";
    // Force the outer anime container to stack sections vertically on desktop.
    list.style.display = "block";
    list.style.width = "100%";
    list.style.maxWidth = "100%";

    const firstAppearance = appearances[0];
    const featured = appearances.filter(
      (episode) => (episode.category || "featured") === "featured"
    );
    const cameos = appearances.filter(
      (episode) => episode.category === "cameo"
    );
    const movies = appearances.filter(
      (episode) => episode.category === "movie-special"
    );

    const createEpisodeCard = (episode) => {
      const card = document.createElement("article");
      card.className = "episode-card";
      card.style.display = "grid";
      card.style.gridTemplateColumns = window.innerWidth <= 650
        ? "1fr"
        : "220px minmax(0, 1fr)";
      card.style.width = "100%";
      card.style.maxWidth = "none";
      card.style.minWidth = "0";

      const targetUrl =
        episode.watchUrl ||
        episode.searchUrl ||
        "https://www.pokeflix.tv/search/";

      const buttonText = episode.watchUrl
        ? "Watch on Pokéflix ↗"
        : "Find on Pokéflix ↗";

      const episodeLabel = episode.episode
        ? `Episode ${episode.episode}`
        : "Anime appearance";

      card.innerHTML = `
        <div class="episode-poster ${episode.thumbnail ? "has-thumbnail" : ""}" aria-hidden="true">
          ${episode.thumbnail
            ? `<img class="episode-thumbnail" src="${episode.thumbnail}" alt="" loading="lazy">`
            : `<div>
                 <div class="tv">📺</div>
                 <small>${episode.series || "Pokémon Anime"}</small>
               </div>`
          }
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

      return card;
    };

    const createSection = (title, items, options = {}) => {
      if (!items.length) return;

      const section = document.createElement("section");
      section.className = "anime-subsection";
      section.style.display = "block";
      section.style.width = "100%";
      section.style.maxWidth = "100%";
      section.style.marginTop = "30px";

      const heading = document.createElement("div");
      heading.className = "anime-subheading";

      const titleEl = document.createElement("h3");
      titleEl.textContent = title;

      const count = document.createElement("span");
      count.className = "count-pill";
      count.textContent = `${items.length}`;

      heading.append(titleEl, count);
      section.append(heading);

      const grid = document.createElement("div");
      grid.className = "appearance-grid";
      grid.style.display = "grid";
      grid.style.gridTemplateColumns = "minmax(0, 1fr)";
      grid.style.gap = "18px";
      grid.style.width = "100%";
      section.append(grid);

      const batchSize = options.batchSize || 10;
      let visibleCount = 0;

      const renderBatch = () => {
        const next = items.slice(visibleCount, visibleCount + batchSize);

        next.forEach((episode) => {
          grid.append(createEpisodeCard(episode));
        });

        visibleCount += next.length;

        const oldButton = section.querySelector(".show-more-button");
        if (oldButton) oldButton.remove();

        if (visibleCount < items.length) {
          const button = document.createElement("button");
          button.className = "show-more-button";
          button.type = "button";
          button.textContent =
            `Show 10 more (${items.length - visibleCount} remaining)`;
          button.addEventListener("click", renderBatch);
          section.append(button);
        }
      };

      renderBatch();
      list.append(section);
    };

    const firstWrap = document.createElement("section");
    firstWrap.className = "first-appearance-card";
    firstWrap.style.display = "block";
    firstWrap.style.width = "100%";
    firstWrap.style.maxWidth = "100%";
    firstWrap.innerHTML = `
      <div>
        <p class="eyebrow">First Anime Appearance</p>
        <h3>${firstAppearance.title}</h3>
        <p>${firstAppearance.series || "Pokémon Anime"} · Episode ${firstAppearance.episode || "—"}</p>
      </div>
    `;
    firstWrap.append(createEpisodeCard(firstAppearance));
    list.append(firstWrap);

    createSection("Featured / Major Appearances", featured);
    createSection("Cameo Appearances", cameos);
    createSection("Movies & Specials", movies, { batchSize: 6 });

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

