// Vigía Fuego: hotspot weather-scenario explorer
(function () {
  "use strict";

  // Application State
  const state = {
    activeTab: "screen-grid",
    regions: [],
    boundaries: null,
    regionFeatures: new Map(),
    selectedRegion: null,
    modelInfo: null,
    regionWeather: null,
    liveWeather: null,
    liveWeatherError: false,
    hasChosenWeatherMode: false,
    realExamples: null,
    maps: {
      grid: null,
      history: null,
      point: null,
    },
    layers: {
      grid: null,
      history: null,
      pointMarker: null,
      gridBorder: null,
      historyBorder: null,
      pointBorder: null,
      gridSelection: null,
    },
    historicalFires: [],
    historyRequestId: 0,
    historyPeriod: "week",
    historyMetadata: null,
    historyLoading: false,
    predictionHistory: [],
    gridRequestId: 0,
    gridDirty: false,
  };

  // Solid Alert Colors
  const RISK_COLORS = {
    low: "#4ca6a0",
    moderate: "#e6bd6d",
    high: "#e68e50",
    extreme: "#dc6a59",
  };

  function isEn() {
    return document.documentElement.lang === "en";
  }

  function getProfileLabel(key) {
    if (isEn()) {
      return {
        today: "today's weather",
        rainy: "simulated rainy day",
        hot: "simulated hot day",
        observed: "historical baseline weather",
      }[key] || key;
    }
    return {
      today: "clima de hoy",
      rainy: "día lluvioso simulado",
      hot: "día caluroso simulado",
      observed: "clima histórico de referencia",
    }[key] || key;
  }

  function updateWeatherProfileExplanation() {
    const en = isEn();
    const selected = document.getElementById("weather-preset-select").value;
    const observedDate = state.regionWeather?.observed_date || (en ? "indicated date" : "la fecha indicada");
    const weatherDate = state.liveWeather?.weather_date || (en ? "today" : "hoy");
    const targetDate = state.liveWeather?.target_date || (en ? "tomorrow" : "mañana");
    const descriptions = en ? {
      today: `Uses estimated weather for ${weatherDate} and preceding 29 days. Model evaluates ${targetDate}.`,
      rainy: `Simulates today with at least 20 mm rainfall, 85% humidity, and 2 °C lower maximum temperature. Model evaluates ${targetDate}.`,
      hot: `Simulates today with 4 °C higher maximum temperature, 15 points lower humidity, and zero rain. Model evaluates ${targetDate}.`,
      observed: `Uses weather from days prior to ${observedDate} across each region. Reproduces a historical baseline date.`,
    } : {
      today: `Usa el clima estimado para ${weatherDate} y los 29 días anteriores. El modelo evalúa ${targetDate}.`,
      rainy: `Simula hoy con al menos 20 mm de lluvia, 85% de humedad y 2 °C menos de temperatura máxima. El modelo evalúa ${targetDate}.`,
      hot: `Simula hoy con 4 °C más de temperatura máxima, 15 puntos menos de humedad y sin lluvia. El modelo evalúa ${targetDate}.`,
      observed: `Usa el clima de los días previos al ${observedDate} en cada región. Esta opción reproduce una fecha histórica.`,
    };
    document.getElementById("weather-profile-explainer").textContent = en
      ? `${descriptions[selected] || ""} Colors indicate estimated FIRMS hotspot detection probability, not temperature or ground fires. Future evaluation is experimental.`
      : `${descriptions[selected] || ""} Los colores indican probabilidad estimada de detección FIRMS, no temperatura ni incendios confirmados. La evaluación futura es experimental.`;
  }

  // Public ArcGIS raster basemap; attribution remains visible on every map.
  function createDarkTileLayer() {
    return L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
      {
        attribution: 'Mapa &copy; <a href="https://www.esri.com/">Esri</a>, HERE, Garmin, &copy; OpenStreetMap contributors, GIS User Community',
        maxZoom: 16,
      }
    );
  }

  function geometryForRegion(region) {
    if (!region) return null;
    if (region.id === "peru") {
      return { type: "GeometryCollection", geometries: state.boundaries.features.map((feature) => feature.geometry) };
    }
    return state.regionFeatures.get(region.id)?.geometry || null;
  }

  function weatherProfileAt(lon, lat, profileKey) {
    const profiles = profileKey === "observed"
      ? state.regionWeather?.profiles?.observed
      : state.liveWeather?.profiles?.[profileKey];
    if (!profiles) return null;
    const cell = state.regionWeather?.weather_cells?.find(({ bbox: [west, south, east, north] }) =>
      lon >= west && lon < east && lat >= south && lat < north);
    if (cell) return profiles[cell.weather_id] || null;
    const region = state.regions.slice(1).find((candidate) => {
      const [west, south, east, north] = candidate.bbox;
      return lon >= west && lon <= east && lat >= south && lat <= north &&
        pointInGeometry(lon, lat, state.regionFeatures.get(candidate.id)?.geometry);
    });
    const nearest = region || state.regions.slice(1).reduce((best, candidate) => {
      const distance = (candidate.center[0] - lat) ** 2 + (candidate.center[1] - lon) ** 2;
      return !best || distance < best.distance ? { id: candidate.id, distance } : best;
    }, null);
    return profiles[nearest?.id] || null;
  }

  function applySelectedWeatherToPoint() {
    const lat = Number(document.getElementById("point-lat").value);
    const lon = Number(document.getElementById("point-lon").value);
    if (!pointInGeometry(lon, lat, geometryForRegion(state.regions.find((region) => region.id === "peru")))) return;
    const profile = weatherProfileAt(
      lon, lat, document.getElementById("weather-preset-select").value || "observed"
    );
    if (!profile) return;
    document.getElementById("point-date").value = profile.date;
    for (const [key, value] of Object.entries(profile.features)) {
      const input = document.getElementById(`feat-${key}`);
      const slider = document.getElementById(`range-${key}`);
      if (input) input.value = value;
      if (slider) slider.value = value;
    }
  }

  function pointInRing(lon, lat, ring) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i];
      const [xj, yj] = ring[j];
      const cross = (lon - xi) * (yj - yi) - (lat - yi) * (xj - xi);
      if (Math.abs(cross) < 1e-9 && lon >= Math.min(xi, xj) - 1e-9 &&
          lon <= Math.max(xi, xj) + 1e-9 && lat >= Math.min(yi, yj) - 1e-9 &&
          lat <= Math.max(yi, yj) + 1e-9) return true;
      if ((yi > lat) !== (yj > lat) && lon < (xj - xi) * (lat - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }

  function pointInGeometry(lon, lat, geometry) {
    if (!geometry) return false;
    if (geometry.type === "GeometryCollection") {
      return geometry.geometries.some((part) => pointInGeometry(lon, lat, part));
    }
    const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
    return polygons.some((rings) => pointInRing(lon, lat, rings[0]) &&
      !rings.slice(1).some((hole) => pointInRing(lon, lat, hole)));
  }

  function fitRegion(map, region) {
    if (!map || !region) return;
    const [west, south, east, north] = region.bbox;
    map.fitBounds([[south, west], [north, east]], { padding: [20, 20], maxZoom: 11, animate: false });
  }

  function drawRegionBorder(map, layerKey) {
    if (!map || !state.selectedRegion || !state.boundaries) return;
    if (state.layers[layerKey]) map.removeLayer(state.layers[layerKey]);
    const national = state.selectedRegion.id === "peru";
    const feature = national ? state.boundaries : state.regionFeatures.get(state.selectedRegion.id);
    state.layers[layerKey] = L.geoJSON(feature, {
      interactive: false,
      style: {
        color: national ? "#b5c9b5" : "#f0d2a1",
        weight: national ? 1.2 : 2.3,
        opacity: national ? 0.65 : 0.92,
        fillOpacity: 0,
      },
    }).addTo(map);
  }

  function mercatorY(lat) {
    const radians = lat * Math.PI / 180;
    return Math.log(Math.tan(Math.PI / 4 + radians / 2));
  }

  function latitudeFromMercator(y) {
    return (2 * Math.atan(Math.exp(y)) - Math.PI / 2) * 180 / Math.PI;
  }

  function bracket(values, value) {
    if (value <= values[0]) return [0, 0, 0];
    const last = values.length - 1;
    if (value >= values[last]) return [last, last, 0];
    let low = 0;
    let high = last;
    while (high - low > 1) {
      const mid = (low + high) >> 1;
      if (values[mid] <= value) low = mid;
      else high = mid;
    }
    return [low, high, (value - values[low]) / (values[high] - values[low])];
  }

  function probabilityColor(probability) {
    const stops = [
      [0, [49, 105, 112]], [0.05, [76, 166, 160]],
      [0.15, [230, 189, 109]], [0.30, [230, 142, 80]],
      [0.60, [220, 106, 89]], [1, [184, 66, 61]],
    ];
    for (let index = 1; index < stops.length; index++) {
      if (probability <= stops[index][0]) {
        const [p0, rgb0] = stops[index - 1];
        const [p1, rgb1] = stops[index];
        const fraction = (probability - p0) / (p1 - p0);
        return rgb0.map((value, channel) => Math.round(value + (rgb1[channel] - value) * fraction));
      }
    }
    return stops.at(-1)[1];
  }

  function drawMaskPolygon(ctx, rings, project) {
    ctx.beginPath();
    rings.forEach((ring) => {
      ring.forEach(([lon, lat], index) => {
        const [x, y] = project(lon, lat);
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.closePath();
    });
    ctx.fill("evenodd");
  }

  function drawMaskGeometry(ctx, geometry, project) {
    if (geometry.type === "GeometryCollection") {
      geometry.geometries.forEach((part) => drawMaskGeometry(ctx, part, project));
    } else {
      const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
      polygons.forEach((rings) => drawMaskPolygon(ctx, rings, project));
    }
  }

  // Smooth only the display between actual model samples; never count interpolated pixels as cells.
  function makeSurface(cells, results, region) {
    const [west, south, east, north] = region.bbox;
    const top = mercatorY(north);
    const bottom = mercatorY(south);
    const lonSpan = (east - west) * Math.PI / 180;
    const mercSpan = top - bottom;
    const scale = 900 / Math.max(lonSpan, mercSpan);
    const width = Math.max(128, Math.round(lonSpan * scale));
    const height = Math.max(128, Math.round(mercSpan * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    const image = context.createImageData(width, height);
    const columns = cells.filter((cell) => cell.row === 0).length;
    const rows = cells.length / columns;
    const lons = cells.slice(0, columns).map((cell) => cell.longitude);
    const lats = Array.from({ length: rows }, (_, row) => cells[row * columns].latitude);
    const xBrackets = Array.from({ length: width }, (_, x) =>
      bracket(lons, west + (x + 0.5) / width * (east - west)));
    const yBrackets = Array.from({ length: height }, (_, y) =>
      bracket(lats, latitudeFromMercator(top - (y + 0.5) / height * mercSpan)));

    for (let y = 0; y < height; y++) {
      const [y0, y1, ty] = yBrackets[y];
      for (let x = 0; x < width; x++) {
        const [x0, x1, tx] = xBrackets[x];
        const lower = results[y0 * columns + x0].probability * (1 - tx) +
          results[y0 * columns + x1].probability * tx;
        const upper = results[y1 * columns + x0].probability * (1 - tx) +
          results[y1 * columns + x1].probability * tx;
        const [red, green, blue] = probabilityColor(lower * (1 - ty) + upper * ty);
        const index = (y * width + x) * 4;
        image.data[index] = red;
        image.data[index + 1] = green;
        image.data[index + 2] = blue;
        image.data[index + 3] = 255;
      }
    }
    context.putImageData(image, 0, 0);

    const mask = document.createElement("canvas");
    mask.width = width;
    mask.height = height;
    const maskContext = mask.getContext("2d");
    maskContext.fillStyle = "#fff";
    const project = (lon, lat) => [
      (lon - west) / (east - west) * width,
      (top - mercatorY(lat)) / mercSpan * height,
    ];
    drawMaskGeometry(maskContext, geometryForRegion(region), project);
    context.globalCompositeOperation = "destination-in";
    context.drawImage(mask, 0, 0);
    return L.imageOverlay(canvas.toDataURL("image/png"), [[south, west], [north, east]], {
      opacity: 0.72, interactive: false,
    });
  }

  // Initialization
  document.addEventListener("DOMContentLoaded", async () => {
    setupTabNavigation();
    setupPointPredictionForm();
    await loadInitialData();
    if (typeof L === "undefined") {
      document.getElementById("grid-insight-title").textContent = "Mapa no disponible";
      document.getElementById("grid-insight-text").textContent = "No se pudo cargar Leaflet. Verifica la conexión y vuelve a intentar.";
      return;
    }
    initScreen1Map();
    initScreen2Map();
    initScreen3Map();
    renderScreen1Grid();
    renderScreen2History();
    loadLiveWeather();
    setupLanguageSwitcher();
  });

  // Load Regions and Model Info
  async function loadInitialData() {
    try {
      const [regionsRes, boundariesRes, infoRes, examplesRes, weatherRes] = await Promise.all([
        fetch("/api/regions"),
        fetch("/api/regions-geojson"),
        fetch("/model-info"),
        fetch("/examples/real"),
        fetch("/api/region-weather"),
      ]);

      if (regionsRes.ok && boundariesRes.ok) {
        state.regions = await regionsRes.json();
        state.boundaries = await boundariesRes.json();
        state.regionFeatures = new Map(
          state.boundaries.features.map((feature) => [feature.properties.id, feature])
        );
        populateRegionSelector();
      } else {
        throw new Error("No se pudieron cargar los límites de las regiones");
      }

      if (infoRes.ok) {
        state.modelInfo = await infoRes.json();
        if (state.modelInfo.training_region === "peru") {
          const national = state.regions.find((region) => region.id === "peru");
          if (national) {
            state.selectedRegion = national;
            document.getElementById("region-select").value = "peru";
            onRegionChanged();
          }
        }
        updateScopeNotes();
        updateModelBadge();
        document.getElementById("model-period").textContent = `${state.modelInfo.date_start} – ${state.modelInfo.date_end}`;
        const usage = state.modelInfo.training_data;
        const en = isEn();
        document.getElementById("model-data-usage").textContent = usage
          ? `${formatCount(usage.fit_rows)} ${en ? "training" : "de ajuste"} · ${formatCount(usage.test_rows)} ${en ? "testing" : "de prueba"}`
          : (en ? "Breakdown unavailable" : "Desglose no disponible");
        document.getElementById("model-f1").textContent = Number(state.modelInfo.test_metrics.f1).toFixed(3);
        document.getElementById("model-weather-resolution").textContent =
          state.modelInfo.training_region === "peru"
            ? (state.modelInfo.weather_sampling?.includes("Puno grid-cell")
              ? (en ? "Puno: grid-cell weather · rest of country: regional stations" : "Puno: clima por celda · resto del país: puntos regionales")
              : (en ? "25 regional stations; each cell uses its region's weather" : "25 puntos regionales; cada celda usa el clima de su región"))
            : (en ? "One series per grid cell" : "Una serie por celda de la malla");
        document.getElementById("point-date").value = state.modelInfo.date_end;
        document.getElementById("threshold-caption").textContent = `${en ? "Threshold" : "Umbral"} ${(state.modelInfo.selected_threshold * 100).toFixed(1)}%`;
        document.getElementById("result-threshold-marker").style.left = `${(state.modelInfo.selected_threshold * 100).toFixed(1)}%`;
      }

      if (weatherRes.ok) {
        state.regionWeather = await weatherRes.json();
        const obsOpt = document.querySelector('#weather-preset-select option[value="observed"]');
        if (obsOpt) {
          obsOpt.textContent = isEn()
            ? `Historical date · ${state.regionWeather.observed_date}`
            : `Fecha histórica · ${state.regionWeather.observed_date}`;
        }
        updateWeatherProfileExplanation();
        applySelectedWeatherToPoint();
      } else {
        throw new Error("No se pudieron cargar los perfiles climáticos regionales");
      }

      if (examplesRes.ok) {
        state.realExamples = await examplesRes.json();
        document.getElementById("load-positive-example").disabled = false;
        document.getElementById("load-negative-example").disabled = false;
      }
    } catch (err) {
      console.error("Error loading initial data:", err);
      const en = isEn();
      document.getElementById("grid-insight-title").textContent = en ? "Data unavailable" : "Datos no disponibles";
      document.getElementById("grid-insight-text").textContent = en ? "Could not connect to service. Please reload page." : "No se pudo conectar con el servicio. Vuelve a cargar la página.";
    }
  }

  async function loadLiveWeather() {
    try {
      const response = await fetch("/api/live-weather", { cache: "no-store" });
      if (!response.ok) throw new Error(`Clima reciente: HTTP ${response.status}`);
      const data = await response.json();
      if (!data.profiles?.today || !data.current || !data.weather_date || !data.target_date) {
        throw new Error("El servicio devolvió clima incompleto");
      }
      const firstLoad = !state.liveWeather;
      state.liveWeather = data;
      state.liveWeatherError = false;
      const select = document.getElementById("weather-preset-select");
      for (const key of ["today", "rainy", "hot"]) {
        select.querySelector(`option[value="${key}"]`).disabled = false;
      }
      const en = isEn();
      select.querySelector('option[value="today"]').textContent = en
        ? `Today ${data.weather_date} · estimate tomorrow`
        : `Hoy ${data.weather_date} · estimar mañana`;
      if (firstLoad && !state.hasChosenWeatherMode) select.value = "today";
      updateWeatherProfileExplanation();
      renderLiveWeatherCard();
      applySelectedWeatherToPoint();
      if (state.activeTab === "screen-grid") renderScreen1Grid();
      else state.gridDirty = true;
    } catch (error) {
      console.error("No se pudo cargar el clima de hoy:", error);
      state.liveWeatherError = true;
      renderLiveWeatherCard();
      if (!state.liveWeather) {
        document.getElementById("weather-profile-explainer").textContent = isEn()
          ? "Open-Meteo did not respond. Historical analysis is retained; you can retry with «Update analysis»."
          : "Open-Meteo no respondió. Se mantiene el análisis histórico; puedes reintentar con «Actualizar análisis».";
      }
    }
  }

  function renderLiveWeatherCard() {
    const en = isEn();
    const data = state.liveWeather;
    const title = document.getElementById("weather-data-region");
    const note = document.getElementById("weather-data-note");
    if (!data || !state.selectedRegion) {
      title.textContent = state.liveWeatherError
        ? (en ? "Today's weather unavailable" : "Clima de hoy no disponible")
        : (en ? "Loading current conditions…" : "Cargando condiciones actuales…");
      note.textContent = state.liveWeatherError
        ? (en ? "Historical view retained. Retry query when Open-Meteo is available." : "Se conserva la vista histórica. Reintenta la consulta cuando Open-Meteo esté disponible.")
        : (en ? "Querying daily weather and regional conditions across 25 stations." : "Consultando datos diarios y condiciones actuales de 25 puntos regionales.");
      return;
    }
    const selected = document.getElementById("weather-preset-select").value;
    const scenario = ["rainy", "hot"].includes(selected) ? selected : "today";
    const keys = state.selectedRegion.id === "peru"
      ? state.regions.slice(1).map((region) => region.id)
      : [state.selectedRegion.id];
    const average = (values) => values.reduce((sum, value) => sum + value, 0) / values.length;
    const dailyValue = (field) => average(keys.map((key) => data.profiles[scenario][key].today_daily[field]));
    const currentValue = (field) => average(keys.map((key) => data.current[key][field]));
    const national = state.selectedRegion.id === "peru";
    title.textContent = national
      ? (en ? "Peru · 25-point regional average" : "Perú · promedio de 25 puntos")
      : `${state.selectedRegion.name} · ${en ? "regional station" : "punto regional"}`;
    document.getElementById("weather-data-updated").textContent = en
      ? `Query ${new Date(data.retrieved_at).toLocaleTimeString("en-US", {timeZone: "America/Lima", hour: "2-digit", minute: "2-digit"})} · Peru time`
      : `Consulta ${new Date(data.retrieved_at).toLocaleTimeString("es-PE", {timeZone: "America/Lima", hour: "2-digit", minute: "2-digit"})} · hora Perú`;
    document.getElementById("weather-data-temperature").textContent = `${dailyValue("temperature_2m_max").toFixed(1)} °C`;
    document.getElementById("weather-data-humidity").textContent = `${dailyValue("relative_humidity_2m_mean").toFixed(0)} %`;
    document.getElementById("weather-data-rain").textContent = `${dailyValue("precipitation_sum").toFixed(1)} mm`;
    document.getElementById("weather-data-wind").textContent = `${dailyValue("wind_speed_10m_max").toFixed(1)} km/h`;
    const scenarioNote = en
      ? (scenario === "today" ? "Today's daily estimate" :
         scenario === "rainy" ? "Simulated daily values for a rainy day" :
         "Simulated daily values for a hot day")
      : (scenario === "today" ? "Estimación diaria de hoy" :
         scenario === "rainy" ? "Valores diarios simulados para un día lluvioso" :
         "Valores diarios simulados para un día caluroso");
    const currentNote = en
      ? `Now, from weather model: ${currentValue("temperature_2m").toFixed(1)} °C, ${currentValue("relative_humidity_2m").toFixed(0)}% humidity, ${currentValue("precipitation").toFixed(1)} mm rain in 15 min, and ${currentValue("wind_speed_10m").toFixed(1)} km/h wind.`
      : `Ahora, según el modelo meteorológico: ${currentValue("temperature_2m").toFixed(1)} °C, ${currentValue("relative_humidity_2m").toFixed(0)} % de humedad, ${currentValue("precipitation").toFixed(1)} mm de lluvia en 15 min y ${currentValue("wind_speed_10m").toFixed(1)} km/h de viento.`;
    const scopeNote = en
      ? (national ? "Each metric averages 25 regional points." : `Reference coordinate: ${state.selectedRegion.center[0].toFixed(2)}, ${state.selectedRegion.center[1].toFixed(2)}.`)
      : (national ? "Cada dato es un promedio de 25 puntos, no una medición uniforme del país." : `Punto de referencia: ${state.selectedRegion.center[0].toFixed(2)}, ${state.selectedRegion.center[1].toFixed(2)}.`);
    note.textContent = `${scenarioNote} (${data.weather_date}, ${en ? "UTC day" : "día UTC"}). ${currentNote} ${scopeNote} ${en ? "Model evaluates" : "El modelo evalúa"} ${data.target_date}.` +
      (state.liveWeatherError ? (en ? " Unable to refresh; displaying last received data." : " No se pudo actualizar la consulta; se muestran los últimos datos recibidos.") : "");
  }

  function populateRegionSelector() {
    const selector = document.getElementById("region-select");
    selector.innerHTML = "";
    state.regions.forEach((reg) => {
      const opt = document.createElement("option");
      opt.value = reg.id;
      opt.textContent = reg.name;
      if (reg.id === "peru") opt.selected = true;
      selector.appendChild(opt);
    });

    state.selectedRegion = state.regions.find((reg) => reg.id === "peru") || state.regions[0] || null;
    updateScopeNotes();

    selector.addEventListener("change", (e) => {
      const found = state.regions.find((r) => r.id === e.target.value);
      if (found) {
        state.selectedRegion = found;
        onRegionChanged();
      }
    });
  }

  function updateModelBadge() {
    const el = document.getElementById("model-badge-text");
    if (el && state.modelInfo) {
      const en = isEn();
      const scope = state.modelInfo.training_region === "peru" ? (en ? "Peru" : "Perú") : "Madre de Dios";
      const names = { hist_gradient_boosting: "HGB", xgboost: "XGBoost", logistic: en ? "Logistic" : "Logística", random_forest: "RF" };
      el.textContent = `${names[state.modelInfo.model] || state.modelInfo.model} · ${scope}`;
      el.title = en
        ? `FIRMS hotspot detection model ${state.modelInfo.model}, trained on ${scope}`
        : `Modelo de detección FIRMS ${state.modelInfo.model}, entrenado en ${scope}`;
    }
  }

  function updateScopeNotes() {
    const en = isEn();
    const trainingRegion = state.modelInfo?.training_region || "madre_de_dios";
    const note = document.getElementById("region-scope-note");
    const selected = state.selectedRegion?.id;
    const extrapolated = trainingRegion !== "peru" && selected && selected !== trainingRegion;
    const regional = trainingRegion === "peru" && selected !== "peru"
      ? state.modelInfo?.regional_test_metrics?.[selected] : null;
    note.hidden = !extrapolated;
    note.textContent = extrapolated
      ? (en
          ? "The model was trained in Madre de Dios. This region is outside its training validation area."
          : "El modelo se entrenó en Madre de Dios. Esta zona está fuera de su área de validación.")
      : "";
    const detail = document.getElementById("model-regional-validation");
    const metrics = regional?.metrics || (selected === "peru" ? state.modelInfo?.test_metrics : null);
    if (detail) {
      if (metrics) {
        detail.textContent = en
          ? `${regional?.name || "Peru"} · PR-AUC ${metrics.pr_auc.toFixed(3)} · F1 ${metrics.f1.toFixed(3)}. Historical temporal evaluation with national threshold; does not validate an operational alert.`
          : `${regional?.name || "Perú"} · PR-AUC ${metrics.pr_auc.toFixed(3)} · F1 ${metrics.f1.toFixed(3)}. Evaluación temporal histórica con el umbral nacional; no valida una alerta operativa.`;
      } else {
        detail.textContent = en
          ? "Insufficient examples of both classes to compute localized metrics for this selection."
          : "No hay suficientes ejemplos de ambas clases para calcular métricas de esta selección.";
      }
    }
    updatePointScopeNote();
  }

  function updatePointScopeNote() {
    const en = isEn();
    const note = document.getElementById("point-scope-note");
    const lat = Number(document.getElementById("point-lat").value);
    const lon = Number(document.getElementById("point-lon").value);
    const located = [...state.regionFeatures.values()].find((feature) =>
      pointInGeometry(lon, lat, feature.geometry));
    const regionLabel = document.getElementById("point-region-label");
    if (regionLabel) regionLabel.textContent = located?.properties.name || (en ? "Outside Peru" : "Fuera de Perú");
    const trainingRegion = state.modelInfo?.training_region || "madre_de_dios";
    const trainingGeometry = trainingRegion === "peru"
      ? geometryForRegion(state.regions.find((region) => region.id === "peru"))
      : state.regionFeatures.get(trainingRegion)?.geometry;
    const outside = trainingGeometry && Number.isFinite(lat) && Number.isFinite(lon) &&
      !pointInGeometry(lon, lat, trainingGeometry);
    note.hidden = !outside;
    if (outside) {
      note.textContent = en
        ? (trainingRegion === "peru"
            ? "Point is outside Peru's model training area. Interpret probability only as an exploratory extrapolation."
            : "Point is outside Madre de Dios model training area. Interpret probability only as an exploratory extrapolation.")
        : (trainingRegion === "peru"
            ? "El punto está fuera de Perú, área de entrenamiento del modelo. Interpreta la probabilidad solo como una extrapolación exploratoria."
            : "El punto está fuera de Madre de Dios, área de entrenamiento del modelo. Interpreta la probabilidad solo como una extrapolación exploratoria.");
    }
  }

  function onRegionChanged() {
    const reg = state.selectedRegion;
    if (!reg) return;
    updateScopeNotes();
    renderLiveWeatherCard();

    if (state.maps.grid) {
      if (state.activeTab === "screen-grid") fitRegion(state.maps.grid, reg);
      drawRegionBorder(state.maps.grid, "gridBorder");
      if (state.layers.gridSelection) {
        state.maps.grid.removeLayer(state.layers.gridSelection);
        state.layers.gridSelection = null;
      }
      if (state.activeTab === "screen-grid") renderScreen1Grid();
      else {
        state.gridRequestId++;
        state.gridDirty = true;
      }
    }
    if (state.maps.history) {
      if (state.activeTab === "screen-history") fitRegion(state.maps.history, reg);
      drawRegionBorder(state.maps.history, "historyBorder");
      renderScreen2History();
    }
    if (state.maps.point) {
      if (state.activeTab === "screen-point") fitRegion(state.maps.point, reg);
      drawRegionBorder(state.maps.point, "pointBorder");
      state.layers.pointMarker.setLatLng(reg.center);
      document.getElementById("point-lat").value = reg.center[0];
      document.getElementById("point-lon").value = reg.center[1];
      document.getElementById("point-cell-id").value = "punto_manual";
      applySelectedWeatherToPoint();
      updatePointScopeNote();
    }
  }

  // Tab Navigation Handling
  function setupTabNavigation() {
    const buttons = document.querySelectorAll(".tab-btn");
    buttons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = btn.dataset.tab;
        if (target === state.activeTab) return;

        buttons.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");

        document.querySelectorAll(".screen-view").forEach((view) => {
          view.classList.remove("active");
        });

        const activeView = document.getElementById(target);
        if (activeView) activeView.classList.add("active");
        const titlesEn = {
          "screen-grid": "Territorial Overview",
          "screen-history": "Satellite Observatory",
          "screen-point": "Inference Lab",
        };
        const titlesEs = {
          "screen-grid": "Panorama territorial",
          "screen-history": "Archivo de observaciones",
          "screen-point": "Análisis de un punto",
        };
        document.getElementById("header-section-name").textContent =
          (isEn() ? titlesEn : titlesEs)[target] || "";
        buttons.forEach((b) => b.removeAttribute("aria-current"));
        btn.setAttribute("aria-current", "page");

        state.activeTab = target;

        // Invalidate Leaflet sizes on tab switch
        setTimeout(() => {
          const map = target === "screen-grid" ? state.maps.grid : target === "screen-history" ? state.maps.history : state.maps.point;
          if (map) {
            map.invalidateSize();
            fitRegion(map, state.selectedRegion);
          }
          if (target === "screen-grid" && state.gridDirty) {
            state.gridDirty = false;
            renderScreen1Grid();
          }
        }, 100);
      });
    });
  }

  // ==========================================
  // PANTALLA 1: MAPA DE CALOR POR CELDAS
  // ==========================================
  function initScreen1Map() {
    const container = document.getElementById("map-grid");
    if (!container) return;

    const reg = state.selectedRegion || { center: [-12.0, -70.25], zoom: 8 };
    state.maps.grid = L.map(container, {
      center: reg.center,
      zoom: reg.zoom,
      zoomControl: true,
    });
    createDarkTileLayer().addTo(state.maps.grid);

    state.layers.grid = L.layerGroup().addTo(state.maps.grid);
    fitRegion(state.maps.grid, state.selectedRegion);
    drawRegionBorder(state.maps.grid, "gridBorder");
    state.maps.grid.on("click", inspectGridPoint);

    document.getElementById("btn-recalculate-grid").addEventListener("click", () => {
      if (document.getElementById("weather-preset-select").value === "observed" && !state.liveWeatherError) {
        renderScreen1Grid();
      } else {
        loadLiveWeather();
      }
    });

    document.getElementById("weather-preset-select").addEventListener("change", () => {
      state.hasChosenWeatherMode = true;
      updateWeatherProfileExplanation();
      renderLiveWeatherCard();
      applySelectedWeatherToPoint();
      renderScreen1Grid();
    });
  }

  async function renderScreen1Grid() {
    if (!state.maps.grid || !state.selectedRegion) return;
    const presetKey = document.getElementById("weather-preset-select").value || "observed";
    if (presetKey === "observed" ? !state.regionWeather : !state.liveWeather) {
      document.getElementById("grid-insight-title").textContent = "Datos meteorológicos no disponibles";
      document.getElementById("grid-insight-text").textContent = "Comprueba la conexión con Open-Meteo o selecciona la fecha histórica.";
      return;
    }
    const reg = state.selectedRegion;
    const requestId = ++state.gridRequestId;
    const recalculateButton = document.getElementById("btn-recalculate-grid");
    recalculateButton.disabled = true;
    document.getElementById("grid-insight-title").textContent = "Calculando escenario…";
    document.getElementById("grid-insight-text").textContent = "El modelo está evaluando la malla de esta región.";

    // Score a regular sample lattice, then mask the visual surface to the real boundary.
    const [west, south, east, north] = reg.bbox;
    const step = reg.grid_step || 0.25;

    const cells = [];
    let r = 0;
    for (let lat = south; lat < north; lat += step) {
      let c = 0;
      for (let lon = west; lon < east; lon += step) {
        const centerLat = +((lat + Math.min(lat + step, north)) / 2).toFixed(4);
        const centerLon = +((lon + Math.min(lon + step, east)) / 2).toFixed(4);
        cells.push({
          cell_id: `r${String(r).padStart(3, "0")}_c${String(c).padStart(3, "0")}`,
          latitude: centerLat,
          longitude: centerLon,
          row: r,
          col: c,
        });
        c++;
      }
      r++;
    }

    // Call /api/predict-grid for vector prediction
    try {
      const response = await fetch("/api/predict-grid", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cells: cells.map((cell) => {
            const profile = weatherProfileAt(cell.longitude, cell.latitude, presetKey);
            if (!profile) throw new Error("Falta clima regional para una celda");
            return {
              cell_id: cell.cell_id,
              latitude: cell.latitude,
              longitude: cell.longitude,
              features: profile.features,
            };
          }),
        }),
      });

      if (!response.ok) throw new Error("Fallo en cálculo de grilla");
      const data = await response.json();
      if (requestId !== state.gridRequestId) return;
      const results = data.results || [];
      if (results.length !== cells.length) throw new Error("La respuesta de la malla está incompleta");
      const geometry = geometryForRegion(reg);
      const visible = results.filter((_, index) =>
        pointInGeometry(cells[index].longitude, cells[index].latitude, geometry));
      if (!visible.length) throw new Error("No hay muestras dentro de la región");
      state.layers.grid.clearLayers();
      state.layers.grid.addLayer(makeSurface(cells, results, reg));
      state.layers.gridBorder?.eachLayer((layer) => layer.bringToFront?.());

      const distribution = { low: 0, moderate: 0, high: 0, extreme: 0 };
      let aboveThreshold = 0;
      let maxProb = 0;

      visible.forEach((res) => {
        const prob = res.probability;
        if (prob > maxProb) maxProb = prob;
        if (res.predicted_hotspot) aboveThreshold++;
        if (Object.hasOwn(distribution, res.risk_level)) distribution[res.risk_level]++;
      });

      // Update KPI DOM
      const en = isEn();
      document.getElementById("kpi-total-cells").textContent = visible.length.toLocaleString(en ? "en-US" : "es-PE");
      document.getElementById("kpi-high-risk").textContent = aboveThreshold.toLocaleString(en ? "en-US" : "es-PE");
      document.getElementById("kpi-max-prob").textContent = `${(maxProb * 100).toFixed(1)}%`;
      document.getElementById("kpi-threshold").textContent = `${(data.threshold * 100).toFixed(1)}%`;
      document.getElementById("grid-insight-title").textContent = aboveThreshold
        ? (en ? `${aboveThreshold} of ${visible.length} samples classified with detection` : `${aboveThreshold} de ${visible.length} muestras clasificadas con detección`)
        : (en ? "No samples classified with detection" : "Ninguna muestra clasificada con detección");
      const datesNote = presetKey === "observed"
        ? (en ? `Historical date: ${state.regionWeather.observed_date}.` : `Fecha histórica: ${state.regionWeather.observed_date}.`)
        : (en ? `Weather from ${state.liveWeather.weather_date}; evaluated date: ${state.liveWeather.target_date}.` : `Clima de ${state.liveWeather.weather_date}; fecha evaluada: ${state.liveWeather.target_date}.`);
      document.getElementById("grid-insight-text").textContent = en
        ? `${getProfileLabel(presetKey)}. ${datesNote} Maximum: ${(maxProb * 100).toFixed(1)}% FIRMS detection probability. ${presetKey === "observed" ? "Retrospective baseline view." : "Experimental future estimation; not an operational alert."} Does not represent burned ground surface.`
        : `${getProfileLabel(presetKey)}. ${datesNote} Máximo: ${(maxProb * 100).toFixed(1)}% de detección FIRMS en el conjunto de referencia. ${presetKey === "observed" ? "Vista retrospectiva." : "Estimación futura experimental, sin validación operativa."} No representa superficie que se incendiará.`;
      document.getElementById("distribution-total").textContent = `${visible.length} ${en ? "samples" : "muestras"}`;
      const labels = { low: "<5%", moderate: "5–15%", high: "15–30%", extreme: "≥30%" };
      document.getElementById("distribution-bars").innerHTML = Object.keys(distribution).map((level) =>
        `<div class="dist-row"><span>${labels[level]}</span><div class="dist-track"><div class="dist-fill" style="width:${100 * distribution[level] / visible.length}%;background:${RISK_COLORS[level]}"></div></div><span class="dist-count">${distribution[level]}</span></div>`
      ).join("");
    } catch (err) {
      console.error("Error evaluating grid:", err);
      if (requestId === state.gridRequestId) {
        const en = isEn();
        document.getElementById("grid-insight-title").textContent = en ? "Could not evaluate grid" : "No se pudo calcular la malla";
        document.getElementById("grid-insight-text").textContent = en ? "Check connection with service and try again." : "Comprueba la conexión con el servicio e inténtalo de nuevo.";
      }
    } finally {
      if (requestId === state.gridRequestId) recalculateButton.disabled = false;
    }
  }

  async function inspectGridPoint(event) {
    const en = isEn();
    const region = state.selectedRegion;
    const lat = +event.latlng.lat.toFixed(5);
    const lon = +event.latlng.lng.toFixed(5);
    const popup = L.popup().setLatLng(event.latlng);
    if (!pointInGeometry(lon, lat, geometryForRegion(region))) {
      popup.setContent(en ? "Select a point inside the regional boundary." : "Selecciona un punto dentro del límite de la región.").openOn(state.maps.grid);
      return;
    }
    popup.setContent(en ? "Calculating exact value at this coordinate…" : "Calculando el valor exacto en esta coordenada…").openOn(state.maps.grid);
    const requestId = state.gridRequestId;
    const presetKey = document.getElementById("weather-preset-select").value || "observed";
    const profile = weatherProfileAt(
      lon, lat, presetKey
    );
    if (!profile) {
      popup.setContent(en ? "No weather data for this point." : "No hay datos meteorológicos para este punto.").openOn(state.maps.grid);
      return;
    }
    const features = profile.features;
    try {
      const response = await fetch("/predict", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cell_id: "punto_mapa",
          date: profile.date,
          features: { ...features, latitude: lat, longitude: lon },
        }),
      });
      if (!response.ok) throw new Error("No se pudo evaluar el punto");
      const result = await response.json();
      if (requestId !== state.gridRequestId) return;
      if (state.layers.gridSelection) state.maps.grid.removeLayer(state.layers.gridSelection);
      state.layers.gridSelection = L.circleMarker([lat, lon], {
        radius: 7, weight: 2, color: "#fff", fillColor: "#15242c", fillOpacity: 1,
      }).addTo(state.maps.grid);
      const content = document.createElement("div");
      content.innerHTML = `<div class="popup-title">${en ? "Exact Model Value" : "Valor exacto del modelo"}</div>
        <div class="popup-row"><span>${en ? "Latitude:" : "Latitud:"}</span><span class="popup-val">${lat}</span></div>
        <div class="popup-row"><span>${en ? "Longitude:" : "Longitud:"}</span><span class="popup-val">${lon}</span></div>
        <div class="popup-row"><span>${en ? "Scenario:" : "Escenario:"}</span><span class="popup-val">${getProfileLabel(presetKey)}</span></div>
        <div class="popup-row"><span>${en ? "Evaluated date:" : "Fecha evaluada:"}</span><span class="popup-val">${profile.date}</span></div>
        <div class="popup-row"><span>${en ? "Detection prob.:" : "Prob. detección:"}</span><span class="popup-val">${(result.probability * 100).toFixed(1)}%</span></div>
        <div class="popup-row"><span>${en ? "Classification:" : "Clasificación:"}</span><span class="popup-val">${result.predicted_hotspot ? (en ? "Above threshold" : "Sobre umbral") : (en ? "Below threshold" : "Bajo umbral")}</span></div>`;
      const button = document.createElement("button");
      button.className = "btn btn-secondary";
      button.style.cssText = "margin-top:10px;width:100%;";
      button.textContent = en ? "Analyze this point →" : "Analizar este punto →";
      button.addEventListener("click", () => transferToScreen3({
        cell_id: "punto_mapa", latitude: lat, longitude: lon,
      }, features, profile.date));
      content.appendChild(button);
      popup.setContent(content).openOn(state.maps.grid);
    } catch (error) {
      popup.setContent(en ? "Could not evaluate this point. Try again." : "No se pudo evaluar este punto. Inténtalo de nuevo.").openOn(state.maps.grid);
    }
  }

  function transferToScreen3(cell, baseFeatures, observationDate) {
    // Switch tab
    document.querySelector('[data-tab="screen-point"]').click();

    // Populate coordinates
    document.getElementById("point-cell-id").value = cell.cell_id;
    document.getElementById("point-date").value = observationDate;
    document.getElementById("point-lat").value = cell.latitude;
    document.getElementById("point-lon").value = cell.longitude;
    updatePointScopeNote();

    // Populate weather inputs
    Object.keys(baseFeatures).forEach((key) => {
      const input = document.getElementById(`feat-${key}`);
      const range = document.getElementById(`range-${key}`);
      if (input) input.value = baseFeatures[key];
      if (range) range.value = baseFeatures[key];
    });
    document.querySelector(".weather-details").open = true;

    // Move marker on Map 3
    if (state.maps.point) {
      state.maps.point.setView([cell.latitude, cell.longitude], 10);
      if (state.layers.pointMarker) {
        state.layers.pointMarker.setLatLng([cell.latitude, cell.longitude]);
      } else {
        state.layers.pointMarker = L.marker([cell.latitude, cell.longitude]).addTo(state.maps.point);
      }
    }

    // Trigger prediction
    document.getElementById("submit-button").click();
  }

  // ==========================================
  // PANTALLA 2: HISTÓRICO DE INCENDIOS (FIRMS)
  // ==========================================
  // One canvas for all detections: no DOM/SVG marker per observation and no sampling cap.
  function createObservationCanvas() {
    const ObservationLayer = L.Layer.extend({
      onAdd(map) {
        this._map = map;
        this._canvas = L.DomUtil.create("canvas", "observation-canvas leaflet-zoom-hide");
        this._canvas.setAttribute("aria-hidden", "true");
        map.getPane("overlayPane").appendChild(this._canvas);
        map.on("moveend zoomend resize", this.schedule, this);
        map.on("click", this.inspect, this);
        this.schedule();
      },
      onRemove(map) {
        map.off("moveend zoomend resize", this.schedule, this);
        map.off("click", this.inspect, this);
        cancelAnimationFrame(this._frame);
        this._canvas.remove();
      },
      schedule() {
        cancelAnimationFrame(this._frame);
        this._frame = requestAnimationFrame(() => this.draw());
      },
      draw() {
        const map = this._map;
        const size = map.getSize();
        if (!size.x || !size.y) return;
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        const canvas = this._canvas;
        canvas.width = size.x * ratio;
        canvas.height = size.y * ratio;
        canvas.style.width = `${size.x}px`;
        canvas.style.height = `${size.y}px`;
        L.DomUtil.setPosition(canvas, map.containerPointToLayerPoint([0, 0]));
        const ctx = canvas.getContext("2d");
        ctx.scale(ratio, ratio);
        const radius = map.getZoom() >= 10 ? 4 : map.getZoom() >= 7 ? 2.6 : 1.8;
        const bounds = map.getBounds();
        this._index = new Map();
        let count = 0;
        for (const fire of state.historicalFires) {
          if (!bounds.contains([fire.latitude, fire.longitude])) continue;
          count++;
          const point = map.latLngToContainerPoint([fire.latitude, fire.longitude]);
          const key = `${Math.floor(point.x / 16)},${Math.floor(point.y / 16)}`;
          if (!this._index.has(key)) this._index.set(key, []);
          this._index.get(key).push({ x: point.x, y: point.y, fire });
          ctx.fillStyle = fire.confidence === "high" ? RISK_COLORS.extreme : fire.confidence === "nominal" ? RISK_COLORS.moderate : "#a4b6c1";
          ctx.globalAlpha = 0.8;
          ctx.beginPath();
          ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
          ctx.fill();
        }
        document.getElementById("kpi-history-visible").textContent = state.historyLoading ? "—" : formatCount(count);
        document.getElementById("history-map-label").textContent = `${formatCount(count)} ${isEn() ? "IN THIS VIEW · ORIGINAL COORDINATES" : "EN ESTA VISTA · COORDENADAS ORIGINALES"}`;
      },
      inspect(event) {
        if (state.historyLoading || !this._index) return;
        const p = event.containerPoint;
        const col = Math.floor(p.x / 16), row = Math.floor(p.y / 16);
        let nearest = null, distance = 100;
        for (let x = col - 1; x <= col + 1; x++) {
          for (let y = row - 1; y <= row + 1; y++) {
            for (const item of this._index.get(`${x},${y}`) || []) {
              const d = (p.x - item.x) ** 2 + (p.y - item.y) ** 2;
              if (d <= distance) { distance = d; nearest = item.fire; }
            }
          }
        }
        if (nearest) showObservationPopup(nearest);
      },
    });
    return new ObservationLayer();
  }

  function formatCount(value) {
    return Number(value || 0).toLocaleString(isEn() ? "en-US" : "es-PE");
  }

  function formatArchiveDate(value, includeTime = false) {
    const en = isEn();
    if (!value) return en ? "No record" : "Sin registro";
    const date = new Date(String(value).length === 10 ? `${value}T12:00:00Z` : value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString(en ? "en-US" : "es-PE", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC", ...(includeTime ? { hour: "2-digit", minute: "2-digit" } : {}) }) + (includeTime ? " UTC" : "");
  }

  function showObservationPopup(fire) {
    const en = isEn();
    const confLabels = en
      ? { high: "High", nominal: "Nominal", low: "Low" }
      : { high: "Alta", nominal: "Nominal", low: "Baja" };
    const rows = [
      [en ? "Date" : "Fecha", `${fire.acq_date || "—"} ${fire.acq_time ? String(fire.acq_time).padStart(4, "0").replace(/^(\d{2})(\d{2})$/, "$1:$2") + " UTC" : (en ? "· time unavailable" : "· hora no disponible")}`],
      [en ? "Coordinates" : "Coordenadas", `${Number(fire.latitude).toFixed(5)}, ${Number(fire.longitude).toFixed(5)}`],
      [en ? "Region" : "Región", fire.mapped_region_name || (en ? "Outside Peru" : "Fuera de Perú")],
      [en ? "Confidence" : "Confianza", confLabels[fire.confidence] || (en ? "No data" : "Sin dato")],
      [en ? "Sensor / satellite" : "Satélite / sensor", `${fire.satellite || "—"} / ${fire.instrument || "—"}`],
      [en ? "Radiative power" : "Potencia radiativa", fire.frp == null ? (en ? "No data" : "Sin dato") : `${Number(fire.frp).toFixed(1)} MW`],
      [en ? "Source" : "Fuente", fire.source || (en ? "No data" : "Sin dato")],
    ];
    L.popup({ maxWidth: 330 }).setLatLng([fire.latitude, fire.longitude]).setContent(
      `<div class="popup-title">${en ? "Satellite Detection" : "Detección satelital"}</div>${rows.map(([label, value]) => `<div class="popup-row"><span>${escapeHtml(label)}</span><span class="popup-val">${escapeHtml(value)}</span></div>`).join("")}`
    ).openOn(state.maps.history);
  }

  function initScreen2Map() {
    const container = document.getElementById("map-history");
    if (!container) return;
    const reg = state.selectedRegion || { center: [-9.2, -75.0], zoom: 5 };
    state.maps.history = L.map(container, { center: reg.center, zoom: reg.zoom, preferCanvas: true, zoomControl: false });
    L.control.zoom({ position: "bottomright" }).addTo(state.maps.history);
    L.control.scale({ position: "bottomleft", imperial: false }).addTo(state.maps.history);
    state.historyBasemap = createDarkTileLayer().addTo(state.maps.history);
    state.layers.history = createObservationCanvas().addTo(state.maps.history);
    drawRegionBorder(state.maps.history, "historyBorder");
    fitRegion(state.maps.history, state.selectedRegion);

    document.getElementById("history-filters").addEventListener("submit", (event) => {
      event.preventDefault();
      renderScreen2History();
    });
    for (const id of ["filter-confidence", "filter-satellite"]) {
      document.getElementById(id).addEventListener("change", () => renderScreen2History());
    }
    for (const id of ["history-start", "history-end"]) {
      document.getElementById(id).addEventListener("change", () => setHistoryPeriod("custom", false));
    }
    document.querySelectorAll("[data-period]").forEach((button) => {
      button.addEventListener("click", () => {
        setHistoryPeriod(button.dataset.period);
        if (button.dataset.period !== "custom") renderScreen2History();
        else document.getElementById("history-start").focus();
      });
    });
    document.getElementById("history-reload").addEventListener("click", () => renderScreen2History(true));
    document.getElementById("history-fit").addEventListener("click", () => fitRegion(state.maps.history, state.selectedRegion));
    document.getElementById("history-basemap").addEventListener("change", (event) => {
      state.maps.history.removeLayer(state.historyBasemap);
      const type = event.target.value;
      state.historyBasemap = type === "dark" ? createDarkTileLayer() : type === "streets"
        ? L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' })
        : L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 18, attribution: 'Imágenes &copy; Esri, Maxar, Earthstar Geographics, GIS User Community' });
      state.historyBasemap.addTo(state.maps.history);
    });
  }

  function setHistoryPeriod(period, changeDates = true) {
    state.historyPeriod = period;
    document.querySelectorAll("[data-period]").forEach((button) => {
      const selected = button.dataset.period === period;
      button.classList.toggle("selected", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    const metadata = state.historyMetadata;
    if (!changeDates || !metadata || period === "custom") return;
    const end = String(metadata.date_end || metadata.last_detection || "").slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(end)) return;
    let start = end;
    if (period === "week") {
      const date = new Date(`${end}T12:00:00Z`);
      date.setUTCDate(date.getUTCDate() - 6);
      start = date.toISOString().slice(0, 10);
    } else if (period === "all") start = String(metadata.date_start || end).slice(0, 10);
    document.getElementById("history-start").value = start;
    document.getElementById("history-end").value = end;
  }

  function showHistoryMetadata(metadata) {
    state.historyMetadata = metadata;
    document.getElementById("history-latest").textContent = formatArchiveDate(metadata.last_detection || metadata.date_end);
    document.getElementById("history-coverage").textContent = `${formatArchiveDate(metadata.date_start)} — ${formatArchiveDate(metadata.date_end)}`;
    document.getElementById("history-generated").textContent = formatArchiveDate(metadata.generated_at, true);
    document.getElementById("kpi-history-archive").textContent = formatCount(metadata.total_records);
    document.getElementById("history-duplicates").textContent = formatCount(metadata.duplicates_removed);
    document.getElementById("history-invalid").textContent = formatCount(metadata.invalid_rows);
    document.getElementById("kpi-history-unmapped").textContent = formatCount(metadata.outside_peru);
    const en = isEn();
    const sourceNames = en ? {
      raw_csv: "Consolidated CSV files",
      local_csv: "Local CSV files",
      consolidated: "Consolidated archive",
      firms_api: "NASA FIRMS API",
      archive: "Historical archive",
      legacy_sample: "Legacy sample",
      local_archive: "Local consolidated archive",
      local_firms_archive: "Local FIRMS historical archive",
      local_csv_import: "Imported & validated CSVs",
      firms_multisource: "FIRMS · multi-sensor",
    } : {
      raw_csv: "Archivos CSV consolidados",
      local_csv: "Archivos CSV locales",
      consolidated: "Archivo consolidado",
      firms_api: "NASA FIRMS API",
      archive: "Archivo histórico",
      legacy_sample: "Muestra visual heredada",
      local_archive: "Archivo local consolidado",
      local_firms_archive: "Archivo histórico FIRMS local",
      local_csv_import: "CSV importados y validados",
      firms_multisource: "FIRMS · múltiples sensores",
    };
    document.getElementById("history-source-kind").textContent = sourceNames[metadata.source_kind] || metadata.source_kind || (en ? "Consolidated archive" : "Archivo consolidado");
    const badge = document.getElementById("history-source-status");
    const fallback = metadata.serving_fallback || /fallback|degraded|sample/.test(`${metadata.status} ${metadata.source_kind}`);
    badge.textContent = fallback
      ? (en ? "Using backup" : "Usando respaldo")
      : metadata.status === "stale"
        ? (en ? "Historical archive" : "Archivo histórico")
        : (en ? "Archive available" : "Archivo disponible");
    badge.classList.toggle("is-fallback", fallback);
    const sources = document.getElementById("history-sources");
    sources.replaceChildren();
    for (const [name, count] of Object.entries(metadata.source_counts || {})) {
      const row = document.createElement("div");
      const title = document.createElement("span");
      title.textContent = sourceNames[name] || name;
      title.title = name;
      const value = document.createElement("strong");
      value.textContent = formatCount(typeof count === "object" ? count.records ?? count.count : count);
      row.append(title, value);
      sources.append(row);
    }
    if (!sources.children.length) sources.textContent = en ? "No breakdown available" : "Sin desglose disponible";
    const refresh = metadata.refresh || {};
    const refreshFailed = /fail|error|fallback|offline|partial/.test(refresh.status || "");
    document.getElementById("history-refresh-note").textContent = refreshFailed
      ? (refresh.status === "partial"
          ? (en ? "Partial update: some sensors timed out. Preserving valid records; check coverage dates." : "Actualización parcial: algunos sensores no respondieron. Se conserva su historial; revisa las fechas de cobertura.")
          : (en ? "Last update incomplete. Preserving last valid archive; verify coverage dates." : "La última actualización no se completó. Se conserva el último archivo válido; revisa su fecha de cobertura."))
      : (en ? "Reloading queries the published archive. Adding fresh data depends on scheduled download pipelines; does not certify complete satellite coverage." : "Recargar vuelve a consultar el archivo publicado. La incorporación de nuevos datos depende del proceso de descarga; no acredita cobertura satelital completa.");
  }

  async function renderScreen2History(refreshMetadata = false) {
    if (!state.maps.history || !state.selectedRegion) return;
    state.historyController?.abort();
    const controller = new AbortController();
    state.historyController = controller;
    const requestId = ++state.historyRequestId;
    const status = document.getElementById("history-load-status");
    const empty = document.getElementById("history-empty");
    const en = isEn();
    state.historyLoading = true;
    state.historicalFires = [];
    state.layers.history.schedule();
    state.maps.history.closePopup();
    empty.hidden = true;
    status.classList.remove("has-error");
    status.textContent = en ? "Querying archive…" : "Consultando el archivo…";
    document.getElementById("history-reload").disabled = true;
    document.getElementById("map-history").setAttribute("aria-busy", "true");
    for (const id of ["kpi-history-total", "kpi-history-high", "kpi-history-visible"]) document.getElementById(id).textContent = "—";
    const getJson = async (url) => {
      const timeout = setTimeout(() => controller.abort("timeout"), 60000);
      try {
        const response = await fetch(url, { signal: controller.signal, cache: "no-store" });
        if (!response.ok) throw new Error(response.status === 409 ? (en ? "Archive changed during query. Click Reload archive." : "El archivo cambió durante la consulta. Pulsa Recargar archivo para obtener una versión consistente.") : (en ? `Service responded HTTP ${response.status}. Click Reload archive.` : `El servicio respondió HTTP ${response.status}. Pulsa Recargar archivo para reintentar.`));
        return await response.json();
      } finally { clearTimeout(timeout); }
    };
    try {
      if (!state.historyMetadata || refreshMetadata === true) {
        const statusData = await getJson("/api/fire-observations/status");
        if (requestId !== state.historyRequestId) return;
        showHistoryMetadata(statusData.metadata || statusData);
        setHistoryPeriod(state.historyPeriod || "week");
      }
      const start = document.getElementById("history-start").value;
      const end = document.getElementById("history-end").value;
      if (!start || !end) throw new Error(en ? "Archive does not have a valid period." : "El archivo no tiene un período válido. Comprueba el proceso de descarga.");
      if (start > end) throw new Error(en ? "Start date must be earlier or equal to end date." : "La fecha inicial debe ser anterior o igual a la fecha final.");
      const regionName = state.selectedRegion.name;
      const params = new URLSearchParams({
        region: state.selectedRegion.id, start_date: start, end_date: end,
        confidence: document.getElementById("filter-confidence").value,
        instrument: document.getElementById("filter-satellite").value,
        limit: "5000", offset: "0",
      });
      document.getElementById("history-range").textContent = `${formatArchiveDate(start)} — ${formatArchiveDate(end)} · UTC`;
      const items = [];
      let offset = 0, total = null, snapshot = null;
      while (true) {
        params.set("offset", String(offset));
        if (snapshot) params.set("snapshot_id", snapshot);
        const page = await getJson(`/api/fire-observations?${params}`);
        if (requestId !== state.historyRequestId) return;
        if (!Array.isArray(page.items) || !Number.isInteger(page.total) || page.total < 0) throw new Error(en ? "Invalid archive response." : "La respuesta del archivo no es válida.");
        if (snapshot !== null && (page.snapshot_id !== snapshot || page.total !== total)) throw new Error(en ? "Archive modified during query. Click Reload archive." : "El archivo cambió durante la consulta. Pulsa Recargar archivo para obtener una versión consistente.");
        snapshot = page.snapshot_id;
        total = page.total;
        items.push(...page.items);
        status.textContent = en
          ? `Loading ${formatCount(items.length)} of ${formatCount(total)} detections…`
          : `Cargando ${formatCount(items.length)} de ${formatCount(total)} detecciones…`;
        if (page.metadata && offset === 0) showHistoryMetadata(page.metadata);
        if (page.next_offset == null) break;
        if (!Number.isInteger(page.next_offset) || page.next_offset <= offset || page.items.length === 0) throw new Error(en ? "Incomplete archive pagination. Reload." : "La paginación del archivo está incompleta. Vuelve a cargarlo.");
        offset = page.next_offset;
      }
      if (items.length !== total) throw new Error(en ? `Received ${formatCount(items.length)} of ${formatCount(total)} records.` : `La consulta recibió ${formatCount(items.length)} de ${formatCount(total)} registros. Recarga para completar los datos.`);
      if (items.some((fire) => !Number.isFinite(fire.latitude) || !Number.isFinite(fire.longitude) || Math.abs(fire.latitude) > 90 || Math.abs(fire.longitude) > 180)) throw new Error(en ? "Archive contains invalid coordinates." : "El archivo contiene coordenadas inválidas. Revisa su validación antes de mostrarlo.");
      state.historicalFires = items;
      document.getElementById("kpi-history-total").textContent = formatCount(total);
      document.getElementById("kpi-history-high").textContent = formatCount(items.filter((fire) => fire.confidence === "high").length);
      status.textContent = en
        ? `${formatCount(total)} detections loaded · ${regionName}`
        : `${formatCount(total)} detecciones cargadas · ${regionName}`;
      document.getElementById("history-summary").textContent = en
        ? `${formatCount(total)} detections in ${regionName} between ${formatArchiveDate(start)} and ${formatArchiveDate(end)}. Complete archive query matching selected filters.`
        : `${formatCount(total)} detecciones en ${regionName} entre ${formatArchiveDate(start)} y ${formatArchiveDate(end)}. Consulta completa del archivo disponible con los filtros seleccionados.`;
      empty.textContent = en
        ? "No detections found for this region, period, and filters. Try 'Full archive' or change filter criteria."
        : "No hay detecciones para esta región, período y filtros. Prueba Todo el archivo o cambia los filtros.";
      empty.hidden = total > 0;
    } catch (error) {
      if (requestId !== state.historyRequestId || (controller.signal.aborted && controller.signal.reason !== "timeout")) return;
      const message = controller.signal.reason === "timeout" ? (en ? "Archive request timed out. Click Reload archive to retry." : "El archivo tardó demasiado en responder. Pulsa Recargar archivo para reintentar.") : error.message;
      status.textContent = en ? "Unable to complete query" : "No se pudo completar la consulta";
      status.classList.add("has-error");
      document.getElementById("history-summary").textContent = message;
      empty.textContent = message;
      empty.hidden = false;
    } finally {
      if (requestId === state.historyRequestId) {
        state.historyLoading = false;
        state.layers.history.schedule();
        document.getElementById("history-reload").disabled = false;
        document.getElementById("map-history").setAttribute("aria-busy", "false");
      }
    }
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  }

  // ==========================================
  // PANTALLA 3: PREDICCIÓN PUNTUAL E INFERENCIA
  // ==========================================
  function initScreen3Map() {
    const container = document.getElementById("map-point-picker");
    if (!container) return;

    const reg = state.selectedRegion || { center: [-12.0, -70.25], zoom: 8 };
    state.maps.point = L.map(container, {
      center: reg.center,
      zoom: reg.zoom,
      zoomControl: true,
    });
    createDarkTileLayer().addTo(state.maps.point);
    drawRegionBorder(state.maps.point, "pointBorder");

    const initialLat = Number(document.getElementById("point-lat").value);
    const initialLon = Number(document.getElementById("point-lon").value);
    state.layers.pointMarker = L.circleMarker([initialLat, initialLon], {
      radius: 9, color: "#fff4df", weight: 3, fillColor: RISK_COLORS.extreme, fillOpacity: 1,
    }).addTo(state.maps.point);

    state.maps.point.on("click", (e) => {
      const lat = +e.latlng.lat.toFixed(5);
      const lon = +e.latlng.lng.toFixed(5);
      state.layers.pointMarker.setLatLng([lat, lon]);
      document.getElementById("point-lat").value = lat;
      document.getElementById("point-lon").value = lon;
      document.getElementById("point-cell-id").value = "punto_manual";
      applySelectedWeatherToPoint();
      updatePointScopeNote();
    });

    for (const id of ["point-lat", "point-lon"]) {
      document.getElementById(id).addEventListener("change", () => {
        document.getElementById("point-cell-id").value = "punto_manual";
        syncMarkerFromInputs();
        applySelectedWeatherToPoint();
      });
    }
    document.getElementById("point-lat").addEventListener("input", updatePointScopeNote);
    document.getElementById("point-lon").addEventListener("input", updatePointScopeNote);
  }

  function syncMarkerFromInputs() {
    const lat = parseFloat(document.getElementById("point-lat").value);
    const lon = parseFloat(document.getElementById("point-lon").value);
    if (!isNaN(lat) && !isNaN(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180 && state.layers.pointMarker) {
      state.layers.pointMarker.setLatLng([lat, lon]);
      state.maps.point.setView([lat, lon]);
    }
    updatePointScopeNote();
  }

  function renderFeatureFields() {
    const fieldsContainer = document.getElementById("feature-fields");
    if (!fieldsContainer) return;
    const en = isEn();
    const featureDefs = [
      { name: "temperature_2m_max_lag1", label: en ? "Prev. Day Max Temp (°C)" : "Temp. Máx. Día Anterior (°C)", min: -20, max: 50, step: 0.1, def: 25 },
      { name: "relative_humidity_2m_mean_lag1", label: en ? "Prev. Day Mean Humidity (%)" : "Humedad Media Día Anterior (%)", min: 10, max: 100, step: 1, def: 74 },
      { name: "precipitation_sum_lag1", label: en ? "Prev. Day Rainfall (mm)" : "Lluvia Día Anterior (mm)", min: 0, max: 300, step: 0.1, def: 0 },
      { name: "wind_speed_10m_max_lag1", label: en ? "Prev. Day Max Wind (km/h)" : "Viento Máx. Día Anterior (km/h)", min: 0, max: 150, step: 0.1, def: 10 },
      { name: "temperature_2m_max_mean_3d", label: en ? "3-Day Mean Temp (°C)" : "Temp. Media 3 Días (°C)", min: -20, max: 50, step: 0.1, def: 25 },
      { name: "temperature_2m_max_mean_7d", label: en ? "7-Day Mean Temp (°C)" : "Temp. Media 7 Días (°C)", min: -20, max: 50, step: 0.1, def: 25 },
      { name: "relative_humidity_2m_mean_mean_7d", label: en ? "7-Day Mean Humidity (%)" : "Humedad Media 7 Días (%)", min: 10, max: 100, step: 1, def: 75 },
      { name: "wind_speed_10m_max_mean_7d", label: en ? "7-Day Mean Wind (km/h)" : "Viento Medio 7 Días (km/h)", min: 0, max: 150, step: 0.1, def: 10 },
      { name: "precipitation_sum_sum_3d", label: en ? "3-Day Accumulated Rain (mm)" : "Lluvia Acumulada 3 Días (mm)", min: 0, max: 600, step: 0.1, def: 0 },
      { name: "precipitation_sum_sum_7d", label: en ? "7-Day Accumulated Rain (mm)" : "Lluvia Acumulada 7 Días (mm)", min: 0, max: 1000, step: 0.1, def: 0 },
      { name: "precipitation_sum_sum_30d", label: en ? "30-Day Accumulated Rain (mm)" : "Lluvia Acumulada 30 Días (mm)", min: 0, max: 2000, step: 1, def: 0 },
    ];

    const existing = {};
    featureDefs.forEach((f) => {
      const cur = document.getElementById(`feat-${f.name}`);
      if (cur) existing[f.name] = cur.value;
    });

    fieldsContainer.innerHTML = "";
    featureDefs.forEach((f) => {
      const val = existing[f.name] !== undefined ? existing[f.name] : f.def;
      const group = document.createElement("div");
      group.className = "form-group";
      group.innerHTML = `
        <label for="feat-${f.name}">${f.label}</label>
        <div class="input-slider-wrap">
          <input type="range" id="range-${f.name}" min="${f.min}" max="${f.max}" step="${f.step}" value="${val}">
          <input type="number" class="input-control" id="feat-${f.name}" name="${f.name}" min="${f.min}" max="${f.max}" step="any" value="${val}" required>
        </div>
      `;
      fieldsContainer.appendChild(group);

      const slider = group.querySelector(`#range-${f.name}`);
      const numInput = group.querySelector(`#feat-${f.name}`);

      slider.addEventListener("input", (e) => {
        numInput.value = e.target.value;
      });
      numInput.addEventListener("input", (e) => {
        slider.value = e.target.value;
      });
    });
  }

  function setupPointPredictionForm() {
    const form = document.getElementById("predict-form");
    renderFeatureFields();

    // Real examples buttons
    document.getElementById("load-positive-example").addEventListener("click", () => loadHoldoutExample("positive"));
    document.getElementById("load-negative-example").addEventListener("click", () => loadHoldoutExample("negative"));

    // Form submit
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      await executePointPrediction();
    });
  }

  function loadHoldoutExample(kind) {
    if (!state.realExamples || !state.realExamples[kind]) return;
    const example = state.realExamples[kind];

    document.getElementById("point-cell-id").value = example.cell_id;
    document.getElementById("point-date").value = example.date;
    document.getElementById("point-lat").value = example.features.latitude;
    document.getElementById("point-lon").value = example.features.longitude;

    Object.keys(example.features).forEach((key) => {
      if (key !== "latitude" && key !== "longitude") {
        const numInput = document.getElementById(`feat-${key}`);
        const slider = document.getElementById(`range-${key}`);
        if (numInput) numInput.value = example.features[key];
        if (slider) slider.value = example.features[key];
      }
    });

    syncMarkerFromInputs();

    const en = isEn();
    const statusEl = document.getElementById("status-indicator");
    statusEl.textContent = en
      ? `Holdout case ${kind === "positive" ? "with FIRMS detection" : "without detection in cell"} loaded. You can adjust features before calculating.`
      : `Caso ${kind === "positive" ? "con detección FIRMS" : "sin detección en la celda"} cargado. Puedes ajustar las variables antes de calcular.`;
  }

  async function executePointPrediction() {
    const en = isEn();
    const btn = document.getElementById("submit-button");
    const statusEl = document.getElementById("status-indicator");
    btn.disabled = true;
    statusEl.textContent = en
      ? `Computing inference with ${state.modelInfo?.model || "model"}...`
      : `Calculando inferencia con ${state.modelInfo?.model || "el modelo"}...`;

    const cellId = document.getElementById("point-cell-id").value;
    const dateVal = document.getElementById("point-date").value;
    const lat = parseFloat(document.getElementById("point-lat").value);
    const lon = parseFloat(document.getElementById("point-lon").value);
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
      statusEl.textContent = en ? "Enter valid coordinates." : "Introduce coordenadas válidas.";
      btn.disabled = false;
      return;
    }

    const features = {
      latitude: lat,
      longitude: lon,
    };

    document.querySelectorAll('#feature-fields input[type="number"]').forEach((input) => {
      features[input.name] = parseFloat(input.value);
    });

    try {
      const response = await fetch("/predict", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cell_id: cellId,
          date: dateVal,
          features: features,
        }),
      });

      const payload = await response.json();
      if (!response.ok) throw new Error(en ? "Service rejected request. Check date and features." : "El servicio rechazó los datos. Revisa la fecha y las variables.");

      displayPredictionResult(payload, features);
      statusEl.textContent = en
        ? `Analysis completed with ${payload.model}. Observation date labels case; probability is driven by coordinates and weather features.`
        : `Análisis completado con ${payload.model}. La fecha identifica la observación; la probabilidad depende de las coordenadas y las variables meteorológicas.`;
    } catch (err) {
      statusEl.textContent = `Error: ${err.message}`;
    } finally {
      btn.disabled = false;
    }
  }

  function displayPredictionResult(result, features) {
    const prob = result.probability;
    const threshold = result.threshold;
    const probPercent = (prob * 100).toFixed(1);

    let riskLevel = "low";
    let riskColor = RISK_COLORS.low;

    if (prob >= 0.30) {
      riskLevel = "extreme";
      riskColor = RISK_COLORS.extreme;
    } else if (prob >= 0.15) {
      riskLevel = "high";
      riskColor = RISK_COLORS.high;
    } else if (prob >= 0.05) {
      riskLevel = "moderate";
      riskColor = RISK_COLORS.moderate;
    }

    const en = isEn();
    // Update Badge
    const badge = document.getElementById("result-risk-badge");
    badge.className = `risk-badge ${riskLevel}`;
    badge.textContent = result.predicted_hotspot ? (en ? "Above threshold" : "Sobre umbral") : (en ? "Below threshold" : "Bajo umbral");

    // Update Meter
    document.getElementById("result-prob-text").textContent = `${probPercent}%`;
    const meterFill = document.getElementById("result-meter-fill");
    meterFill.style.width = `${probPercent}%`;
    meterFill.style.backgroundColor = riskColor;

    const thresholdMarker = document.getElementById("result-threshold-marker");
    thresholdMarker.style.left = `${(threshold * 100).toFixed(1)}%`;
    document.getElementById("threshold-caption").textContent = `${en ? "Threshold" : "Umbral"} ${(threshold * 100).toFixed(1)}%`;

    // Diagnostic summary
    const diagText = document.getElementById("result-diagnostic-text");
    const classification = result.predicted_hotspot
      ? (en ? "The model classifies this feature profile as a hotspot detection." : "El modelo clasifica esta combinación como celda con detección de foco de calor.")
      : (en ? "The model classifies this feature profile as no hotspot detection." : "El modelo clasifica esta combinación como celda sin detección de foco de calor.");
    diagText.textContent = en
      ? `${classification} Probability: ${probPercent}%; threshold: ${(threshold * 100).toFixed(1)}%. Does not confirm ground fire or constitute operational alert.`
      : `${classification} Probabilidad: ${probPercent}%; umbral: ${(threshold * 100).toFixed(1)}%. No confirma un incendio ni constituye una alerta operativa.`;

    // Add to history table
    addResultToTable(result);
  }

  function addResultToTable(result) {
    const tbody = document.getElementById("results");
    const emptyRow = tbody.querySelector("td[colspan]");
    if (emptyRow) tbody.innerHTML = "";

    const tr = document.createElement("tr");
    const isHotspot = result.predicted_hotspot;
    const en = isEn();
    tr.innerHTML = `
      <td><strong>${escapeHtml(result.cell_id)}</strong></td>
      <td>${escapeHtml(result.date)}</td>
      <td>${(result.probability * 100).toFixed(1)}%</td>
      <td>${(result.threshold * 100).toFixed(1)}%</td>
      <td><span class="risk-badge ${isHotspot ? "extreme" : "low"}">${isHotspot ? (en ? "Above threshold" : "Sobre umbral") : (en ? "Below threshold" : "Bajo umbral")}</span></td>
    `;

    tbody.prepend(tr);
  }

  // ==========================================
  // BILINGUAL LANGUAGE SWITCHER (EN / ES)
  // ==========================================
  function setupLanguageSwitcher() {
    const toggleBtn = document.getElementById("lang-toggle-btn");
    const langLabel = document.getElementById("lang-label");

    const I18N = {
      en: {
        brand_sub: "Territorial Intelligence",
        sidebar_caption: "EXPLORE",
        tab_grid: "Overview",
        tab_history: "Observations",
        tab_point: "Point Analysis",
        sidebar_note_title: "How to read this platform",
        sidebar_note_desc: "Exploration of FIRMS detections. Tomorrow's estimation is experimental and not an operational alert.",
        sidebar_credits: "FIRMS · Open-Meteo · ML Model",
        header_eyebrow: "ANALYSIS CENTER / PERU",
        header_section_grid: "Territorial Overview",
        header_section_history: "Satellite Observatory",
        header_section_point: "Inference Lab",
        region_label: "Region",

        // Screen 1: Grid
        s1_kicker: "OVERVIEW",
        s1_title: "The territory, <em>in perspective.</em>",
        s1_desc: "Monitor today's weather, compare simulated scenarios, and explore regional historical records.",
        s1_intro_strong: "Today & tomorrow",
        s1_intro_sub: "Experimental estimate; not an operational alert.",
        s1_kpi_total: "Evaluated Samples",
        s1_kpi_total_sub: "Grid points within regional boundary",
        s1_kpi_threshold: "Above Threshold",
        s1_kpi_threshold_sub: "Statistical classification, not fires",
        s1_kpi_peak: "Max Detection Prob.",
        s1_kpi_peak_sub: "Highest value across grid",
        s1_kpi_cutoff: "Model Decision Threshold",
        s1_kpi_cutoff_sub: "Classification cutoff",
        s1_map_kicker: "01 / INTERACTIVE MAP",
        s1_map_title: "Spatial Distribution",
        s1_map_live: "Scenario Analysis",
        s1_controls_label: "Weather scenario used by model",
        s1_btn_update: "↻ &nbsp;Update analysis",
        s1_legend_title: "DETECTION PROBABILITY",
        s1_map_hint: "Click anywhere to evaluate exact coordinates",
        s1_method_p: "The color surface is <strong>interpolated across model sample points</strong> and clipped to the regional boundary. Clicking evaluates exact coordinates. Colors do not represent burned areas.",
        s1_insight_kicker: "QUICK READING",
        s1_dist_head: "Sample Distribution",
        s1_about_kicker: "ABOUT THE MODEL",
        s1_about_title: "What this result means",
        s1_about_p: "The figure estimates a <strong>satellite hotspot detection</strong> per cell-day. Validated with historical records; tomorrow's estimation is exploratory.",
        s1_fact_data: "Model dataset",
        s1_fact_val: "Temporal validation · F1",
        s1_fact_source: "Source",
        s1_fact_res: "Weather resolution",

        // Screen 2: History
        s2_kicker: "SATELLITE OBSERVATORY / PERU",
        s2_title: "Every detection, <em>in its place.</em>",
        s2_desc: "Explore original coordinates, available timeframe, and detection provenance.",
        s2_stamp_title: "LATEST AVAILABLE DETECTION",
        s2_stamp_sub: "Historical archive · no live streaming",
        s2_kpi_total: "Filtered Detections",
        s2_kpi_total_sub: "Total matching current query",
        s2_kpi_visible: "In Map Viewport",
        s2_kpi_visible_sub: "Updates on pan and zoom",
        s2_kpi_high: "High Confidence",
        s2_kpi_high_sub: "Within selected period and region",
        s2_kpi_archive: "Consolidated Archive",
        s2_kpi_archive_sub: "Valid records before filters",
        s2_map_kicker: "GEOGRAPHIC EXPLORER",
        s2_map_title: "Hotspot Detections",
        s2_btn_reload: "↻ Reload archive",
        s2_period_caption: "PERIOD",
        s2_period_day: "Latest available day",
        s2_period_week: "7 available days",
        s2_period_all: "Full archive",
        s2_period_custom: "Custom",
        s2_filter_start: "From",
        s2_filter_end: "To",
        s2_filter_conf: "Confidence",
        s2_filter_sat: "Instrument",
        s2_btn_apply: "Apply filters",
        s2_legend_title: "CONFIDENCE",
        s2_legend_high: "High",
        s2_legend_nominal: "Nominal",
        s2_legend_low: "Low / unknown",
        s2_map_hint: "Zoom in and click a detection",
        s2_method_p: "Points represent <strong>satellite-detected thermal anomalies</strong>; they do not confirm a ground fire. Original coordinates are preserved.",
        s2_prov_kicker: "PROVENANCE",
        s2_prov_title: "Data Origin",
        s2_prov_summary: "Querying archive sources and timeframes.",
        s2_prov_cov: "Archive coverage",
        s2_prov_gen: "Generated on",
        s2_prov_source: "Source used",
        s2_prov_list: "RECORDS PER SENSOR",
        s2_qc_kicker: "QUALITY CONTROL",
        s2_qc_title: "What the map includes",
        s2_qc_dup: "Duplicates dropped",
        s2_qc_inv: "Invalid rows",
        s2_qc_unmapped: "Outside Peru boundary",
        s2_qc_p: "The Peru view excludes observations outside its borders. The consolidated archive and filters may show different counts.",

        // Screen 3: Point Analysis
        s3_kicker: "INFERENCE LAB",
        s3_title: "Investigate <em>a specific location.</em>",
        s3_desc: "Input pre-observation meteorological conditions or test a holdout case.",
        s3_note_strong: "Experimental Model",
        s3_note_sub: "Future scenarios are not operational fire alerts.",
        s3_form_kicker: "03 / INPUTS",
        s3_form_title: "Analysis Parameters",
        s3_sec_loc: "Location and Date",
        s3_sec_loc_small: "Click on the map to pick a point",
        s3_lbl_cell: "Cell Identifier",
        s3_lbl_date: "Observation Date",
        s3_lbl_lat: "Latitude",
        s3_lbl_lon: "Longitude",
        s3_sec_cases: "Holdout Test Cases",
        s3_btn_pos: "Load case with detection",
        s3_btn_neg: "Load case without detection",
        s3_help_text: '"Without detection" means no hotspot was recorded for this cell on an active regional day. Date labels the case but does not affect the model output.',
        s3_weather_summary: "Pre-observation meteorological variables",
        s3_weather_small: "11 inputs for temperature, humidity, rainfall and wind",
        s3_btn_submit: "Compute probability <span>→</span>",
        s3_status_init: "Select a point on the map or load an example to start.",
        s3_picker_kicker: "GEOGRAPHIC SELECTION",
        s3_picker_title: "Locate the Cell",
        s3_picker_foot: "Region by coordinates:",
        s3_diag_kicker: "MODEL RESULT",
        s3_diag_title: "Cell Assessment",
        s3_badge_none: "No analysis",
        s3_meter_label: "Detection probability",
        s3_threshold_caption: "Cutoff threshold",
        s3_diag_init: "Fill in the variables and run the model to view an estimate.",
        s3_table_kicker: "LOCAL LOG",
        s3_table_title: "Queries in this session",
        s3_table_note: "Cleared on page refresh",
        s3_th_cell: "Cell",
        s3_th_date: "Date",
        s3_th_prob: "Probability",
        s3_th_threshold: "Threshold",
        s3_th_class: "Classification",
        s3_table_empty: "No queries performed yet."
      }
    };

    function applyLanguage(lang) {
      if (lang === "en") {
        document.documentElement.lang = "en";
        if (langLabel) langLabel.textContent = "ES";
        if (toggleBtn) toggleBtn.title = "Cambiar a Español";

        const t = I18N.en;

        // Sidebar
        const brandSmall = document.querySelector(".brand small");
        if (brandSmall) brandSmall.textContent = t.brand_sub;
        const sideCap = document.querySelector(".sidebar-caption");
        if (sideCap) sideCap.textContent = t.sidebar_caption;
        const navBtns = document.querySelectorAll(".sidebar .tab-btn");
        if (navBtns[0]) navBtns[0].childNodes[1].nodeValue = " " + t.tab_grid;
        if (navBtns[1]) navBtns[1].childNodes[1].nodeValue = " " + t.tab_history;
        if (navBtns[2]) navBtns[2].childNodes[1].nodeValue = " " + t.tab_point;
        const sideNoteStrong = document.querySelector(".source-mini strong");
        if (sideNoteStrong) sideNoteStrong.textContent = t.sidebar_note_title;
        const sideNoteP = document.querySelector(".source-mini p");
        if (sideNoteP) sideNoteP.textContent = t.sidebar_note_desc;
        const sideCred = document.querySelector(".sidebar-credit");
        if (sideCred) sideCred.textContent = t.sidebar_credits;

        // Header
        const eyebrow = document.querySelector(".header-heading .eyebrow");
        if (eyebrow) eyebrow.textContent = t.header_eyebrow;
        const regSpan = document.querySelector(".region-selector span");
        if (regSpan) regSpan.textContent = t.region_label;

        // Screen 1: Grid
        const s1Kicker = document.querySelector("#screen-grid .section-kicker");
        if (s1Kicker) s1Kicker.innerHTML = '<span class="kicker-line"></span> ' + t.s1_kicker;
        const s1H1 = document.getElementById("grid-title");
        if (s1H1) s1H1.innerHTML = t.s1_title;
        const s1P = document.querySelector("#screen-grid .page-intro p");
        if (s1P) s1P.textContent = t.s1_desc;
        const s1NoteStrong = document.querySelector("#screen-grid .intro-note strong");
        if (s1NoteStrong) s1NoteStrong.textContent = t.s1_intro_strong;
        const s1NoteSub = document.querySelector("#screen-grid .intro-note span:last-child");
        if (s1NoteSub) s1NoteSub.textContent = t.s1_intro_sub;

        const kpis1 = document.querySelectorAll("#screen-grid .kpi-card");
        if (kpis1[0]) { kpis1[0].querySelector(".kpi-label").textContent = t.s1_kpi_total; kpis1[0].querySelector(".kpi-sub").textContent = t.s1_kpi_total_sub; }
        if (kpis1[1]) { kpis1[1].querySelector(".kpi-label").textContent = t.s1_kpi_threshold; kpis1[1].querySelector(".kpi-sub").textContent = t.s1_kpi_threshold_sub; }
        if (kpis1[2]) { kpis1[2].querySelector(".kpi-label").textContent = t.s1_kpi_peak; kpis1[2].querySelector(".kpi-sub").textContent = t.s1_kpi_peak_sub; }
        if (kpis1[3]) { kpis1[3].querySelector(".kpi-label").textContent = t.s1_kpi_cutoff; kpis1[3].querySelector(".kpi-sub").textContent = t.s1_kpi_cutoff_sub; }

        const s1MapKicker = document.querySelector("#screen-grid .map-card .section-kicker");
        if (s1MapKicker) s1MapKicker.textContent = t.s1_map_kicker;
        const s1MapH2 = document.querySelector("#screen-grid .map-card h2");
        if (s1MapH2) s1MapH2.textContent = t.s1_map_title;
        const s1MapLive = document.querySelector("#screen-grid .map-live-label");
        if (s1MapLive) s1MapLive.innerHTML = "<span></span> " + t.s1_map_live;
        const s1ControlsLabel = document.querySelector("#screen-grid .map-controls label");
        if (s1ControlsLabel) s1ControlsLabel.childNodes[0].nodeValue = t.s1_controls_label + " ";
        const s1BtnUpdate = document.getElementById("btn-recalculate-grid");
        if (s1BtnUpdate) s1BtnUpdate.innerHTML = t.s1_btn_update;
        const s1LegTitle = document.querySelector("#screen-grid .legend-title");
        if (s1LegTitle) s1LegTitle.textContent = t.s1_legend_title;
        const s1MapHint = document.querySelector("#screen-grid .map-hint");
        if (s1MapHint) s1MapHint.textContent = t.s1_map_hint;
        const s1MethodP = document.querySelector("#screen-grid .method-strip p");
        if (s1MethodP) s1MethodP.innerHTML = t.s1_method_p;

        // Select options: Weather scenarios
        const optToday = document.querySelector('#weather-preset-select option[value="today"]');
        if (optToday) {
          optToday.textContent = state.liveWeather?.weather_date
            ? `Today ${state.liveWeather.weather_date} · estimate tomorrow`
            : "Today · estimate tomorrow";
        }
        const optRainy = document.querySelector('#weather-preset-select option[value="rainy"]');
        if (optRainy) optRainy.textContent = "Simulate rainy day";
        const optHot = document.querySelector('#weather-preset-select option[value="hot"]');
        if (optHot) optHot.textContent = "Simulate hot day";
        const optObs = document.querySelector('#weather-preset-select option[value="observed"]');
        if (optObs) {
          optObs.textContent = state.regionWeather?.observed_date
            ? `Historical baseline date · ${state.regionWeather.observed_date}`
            : "Historical baseline date";
        }

        // Weather card labels
        const wKicker = document.querySelector(".weather-data-card .section-kicker");
        if (wKicker) wKicker.textContent = "OPEN-METEO · TODAY";
        const wLabels = document.querySelectorAll(".weather-data-grid div span");
        if (wLabels[0]) wLabels[0].textContent = "Max temperature";
        if (wLabels[1]) wLabels[1].textContent = "Mean humidity";
        if (wLabels[2]) wLabels[2].textContent = "Daily rainfall";
        if (wLabels[3]) wLabels[3].textContent = "Max wind speed";
        const wLink = document.querySelector(".weather-data-card a");
        if (wLink) wLink.textContent = "Source: Open-Meteo ↗";

        // Map overlay label
        const gridOverlay = document.querySelector("#screen-grid .map-overlay-label");
        if (gridOverlay) gridOverlay.innerHTML = '<span class="map-overlay-dot"></span> FIRMS HOTSPOT · ML MODEL';

        const s1InsightKicker = document.querySelector("#screen-grid .insight-card .section-kicker");
        if (s1InsightKicker) s1InsightKicker.textContent = t.s1_insight_kicker;
        const s1DistHead = document.querySelector("#screen-grid .distribution-head strong");
        if (s1DistHead) s1DistHead.textContent = t.s1_dist_head;
        const s1AboutKicker = document.querySelector("#screen-grid .context-card .section-kicker");
        if (s1AboutKicker) s1AboutKicker.textContent = t.s1_about_kicker;
        const s1AboutH2 = document.querySelector("#screen-grid .context-card h2");
        if (s1AboutH2) s1AboutH2.textContent = t.s1_about_title;
        const s1AboutP = document.querySelector("#screen-grid .context-card p");
        if (s1AboutP) s1AboutP.innerHTML = t.s1_about_p;

        // Context facts
        const factLabels = document.querySelectorAll(".model-facts div span");
        if (factLabels[0]) factLabels[0].textContent = "Model dataset";
        if (factLabels[1]) factLabels[1].textContent = "Cell-day records";
        if (factLabels[2]) factLabels[2].textContent = "Model update";
        if (factLabels[3]) factLabels[3].textContent = "Temporal validation · F1";
        if (factLabels[4]) factLabels[4].textContent = "Source";
        if (factLabels[5]) factLabels[5].textContent = "Weather resolution";
        const factUpdate = document.querySelector(".model-facts div:nth-child(3) strong");
        if (factUpdate) factUpdate.textContent = "Downloading observations does not retrain the model";
        const modValSummary = document.querySelector(".model-validation summary");
        if (modValSummary) modValSummary.textContent = "View model validation";

        // Screen 2: History
        const s2Kicker = document.querySelector("#screen-history .section-kicker");
        if (s2Kicker) s2Kicker.innerHTML = '<span class="kicker-line"></span> ' + t.s2_kicker;
        const s2H1 = document.getElementById("history-title");
        if (s2H1) s2H1.innerHTML = t.s2_title;
        const s2P = document.querySelector("#screen-history .page-intro p");
        if (s2P) s2P.textContent = t.s2_desc;
        const s2StampSpan = document.querySelector("#screen-history .archive-stamp span");
        if (s2StampSpan) s2StampSpan.textContent = t.s2_stamp_title;
        const s2StampSmall = document.querySelector("#screen-history .archive-stamp small");
        if (s2StampSmall) s2StampSmall.textContent = t.s2_stamp_sub;

        const kpis2 = document.querySelectorAll("#screen-history .kpi-card");
        if (kpis2[0]) { kpis2[0].querySelector(".kpi-label").textContent = t.s2_kpi_total; kpis2[0].querySelector(".kpi-sub").textContent = t.s2_kpi_total_sub; }
        if (kpis2[1]) { kpis2[1].querySelector(".kpi-label").textContent = t.s2_kpi_visible; kpis2[1].querySelector(".kpi-sub").textContent = t.s2_kpi_visible_sub; }
        if (kpis2[2]) { kpis2[2].querySelector(".kpi-label").textContent = t.s2_kpi_high; kpis2[2].querySelector(".kpi-sub").textContent = t.s2_kpi_high_sub; }
        if (kpis2[3]) { kpis2[3].querySelector(".kpi-label").textContent = t.s2_kpi_archive; kpis2[3].querySelector(".kpi-sub").textContent = t.s2_kpi_archive_sub; }

        const s2MapKicker = document.querySelector("#screen-history .map-card .section-kicker");
        if (s2MapKicker) s2MapKicker.textContent = t.s2_map_kicker;
        const s2MapH2 = document.querySelector("#screen-history .map-card h2");
        if (s2MapH2) s2MapH2.textContent = t.s2_map_title;
        const s2BtnReload = document.getElementById("history-reload");
        if (s2BtnReload) s2BtnReload.textContent = t.s2_btn_reload;

        const s2PeriodCaption = document.querySelector(".period-row .filter-caption");
        if (s2PeriodCaption) s2PeriodCaption.textContent = t.s2_period_caption;
        const pBtns = document.querySelectorAll(".period-options button");
        if (pBtns[0]) pBtns[0].textContent = t.s2_period_day;
        if (pBtns[1]) pBtns[1].textContent = t.s2_period_week;
        if (pBtns[2]) pBtns[2].textContent = t.s2_period_all;
        if (pBtns[3]) pBtns[3].textContent = t.s2_period_custom;

        const labels = document.querySelectorAll(".filter-fields label");
        if (labels[0]) labels[0].childNodes[0].nodeValue = t.s2_filter_start;
        if (labels[1]) labels[1].childNodes[0].nodeValue = t.s2_filter_end;
        if (labels[2]) labels[2].childNodes[0].nodeValue = t.s2_filter_conf;
        if (labels[3]) labels[3].childNodes[0].nodeValue = t.s2_filter_sat;
        const filterSubmit = document.querySelector(".filter-fields button[type='submit']");
        if (filterSubmit) filterSubmit.textContent = t.s2_btn_apply;

        // Screen 2 Selects & Provenance & Quality Control
        const optConfAll = document.querySelector('#filter-confidence option[value="all"]');
        if (optConfAll) optConfAll.textContent = "All confidence levels";
        const optConfHigh = document.querySelector('#filter-confidence option[value="high"]');
        if (optConfHigh) optConfHigh.textContent = "High";
        const optConfNom = document.querySelector('#filter-confidence option[value="nominal"]');
        if (optConfNom) optConfNom.textContent = "Nominal & high";

        const optSatAll = document.querySelector('#filter-satellite option[value="all"]');
        if (optSatAll) optSatAll.textContent = "All sensors";

        const optMapDark = document.querySelector('#history-basemap option[value="dark"]');
        if (optMapDark) optMapDark.textContent = "Dark canvas";
        const optMapStreets = document.querySelector('#history-basemap option[value="streets"]');
        if (optMapStreets) optMapStreets.textContent = "Streets";
        const optMapSat = document.querySelector('#history-basemap option[value="satellite"]');
        if (optMapSat) optMapSat.textContent = "Satellite imagery";

        const histFitSpan = document.querySelector("#history-fit span");
        if (histFitSpan) histFitSpan.textContent = "Center region";

        const s2LegTitle = document.querySelector(".legend-container .legend-title");
        if (s2LegTitle) s2LegTitle.textContent = "CONFIDENCE";
        const s2LegItems = document.querySelectorAll(".legend-container .legend-item");
        if (s2LegItems[0]) s2LegItems[0].innerHTML = '<i class="legend-color legend-ext"></i> High';
        if (s2LegItems[1]) s2LegItems[1].innerHTML = '<i class="legend-color legend-mod"></i> Nominal';
        if (s2LegItems[2]) s2LegItems[2].innerHTML = '<i class="legend-color legend-unknown"></i> Low / unknown';

        const provKicker = document.querySelector(".provenance-card .section-kicker");
        if (provKicker) provKicker.textContent = "DATA PROVENANCE";
        const provH2 = document.querySelector(".provenance-card h2");
        if (provH2) provH2.textContent = "Data Origin";
        const provDl = document.querySelectorAll(".provenance-facts dt");
        if (provDl[0]) provDl[0].textContent = "Archive coverage";
        if (provDl[1]) provDl[1].textContent = "Generated on";
        if (provDl[2]) provDl[2].textContent = "Source used";
        const srcListLabel = document.querySelector(".source-list-label");
        if (srcListLabel) srcListLabel.textContent = "RECORDS PER SENSOR";

        const qcKicker = document.querySelector(".coverage-card .section-kicker");
        if (qcKicker) qcKicker.textContent = "QUALITY CONTROL";
        const qcH2 = document.querySelector(".coverage-card h2");
        if (qcH2) qcH2.textContent = "What the map includes";
        const qcRows = document.querySelectorAll(".quality-row span");
        if (qcRows[0]) qcRows[0].textContent = "Duplicates dropped";
        if (qcRows[1]) qcRows[1].textContent = "Invalid rows";
        if (qcRows[2]) qcRows[2].textContent = "Outside Peru boundary";
        const qcP = document.querySelector(".coverage-card p");
        if (qcP) qcP.textContent = "The Peru view excludes observations outside its borders. The consolidated archive and filters may show different counts.";
        const qcLink = document.querySelector(".coverage-card a");
        if (qcLink) qcLink.innerHTML = 'Query NASA FIRMS <span aria-hidden="true">↗</span>';

        const obsNote = document.querySelector(".observation-note p");
        if (obsNote) obsNote.innerHTML = '<strong>Observation and model are distinct.</strong> Use Overview to compare recent weather, simulations, and historical predictions.';

        // Screen 3: Point Analysis
        const s3Kicker = document.querySelector("#screen-point .section-kicker");
        if (s3Kicker) s3Kicker.innerHTML = '<span class="kicker-line"></span> ' + t.s3_kicker;
        const s3H1 = document.getElementById("point-title");
        if (s3H1) s3H1.innerHTML = t.s3_title;
        const s3P = document.querySelector("#screen-point .page-intro p");
        if (s3P) s3P.textContent = t.s3_desc;
        const s3NoteStrong = document.querySelector("#screen-point .intro-note strong");
        if (s3NoteStrong) s3NoteStrong.textContent = t.s3_note_strong;
        const s3NoteSub = document.querySelector("#screen-point .intro-note span:last-child");
        if (s3NoteSub) s3NoteSub.textContent = t.s3_note_sub;

        const s3FormKicker = document.querySelector("#screen-point .form-panel .section-kicker");
        if (s3FormKicker) s3FormKicker.textContent = t.s3_form_kicker;
        const s3FormH2 = document.querySelector("#screen-point .form-panel h2");
        if (s3FormH2) s3FormH2.textContent = t.s3_form_title;

        const s3Titles = document.querySelectorAll("#predict-form .form-section-title");
        if (s3Titles[0]) s3Titles[0].innerHTML = t.s3_sec_loc + " <small>" + t.s3_sec_loc_small + "</small>";
        if (s3Titles[1]) s3Titles[1].textContent = t.s3_sec_cases;

        const s3Labels = document.querySelectorAll("#predict-form .form-grid label");
        if (s3Labels[0]) s3Labels[0].textContent = t.s3_lbl_cell;
        if (s3Labels[1]) s3Labels[1].textContent = t.s3_lbl_date;
        if (s3Labels[2]) s3Labels[2].textContent = t.s3_lbl_lat;
        if (s3Labels[3]) s3Labels[3].textContent = t.s3_lbl_lon;

        const btnPos = document.getElementById("load-positive-example");
        if (btnPos) btnPos.textContent = t.s3_btn_pos;
        const btnNeg = document.getElementById("load-negative-example");
        if (btnNeg) btnNeg.textContent = t.s3_btn_neg;
        const formHelp = document.querySelector(".form-help");
        if (formHelp) formHelp.textContent = t.s3_help_text;

        const summaryStrong = document.querySelector(".weather-details summary strong");
        if (summaryStrong) summaryStrong.textContent = t.s3_weather_summary;
        const summarySmall = document.querySelector(".weather-details summary small");
        if (summarySmall) summarySmall.textContent = t.s3_weather_small;

        const submitBtn = document.getElementById("submit-button");
        if (submitBtn) submitBtn.innerHTML = t.s3_btn_submit;

        // Screen 3 Picker & Diagnosis & Local Log
        const pickerKicker = document.querySelector(".picker-card .section-kicker");
        if (pickerKicker) pickerKicker.textContent = "GEOGRAPHIC SELECTION";
        const pickerH2 = document.querySelector(".picker-card h2");
        if (pickerH2) pickerH2.textContent = "Locate the Cell";
        const pickerOverlay = document.querySelector(".picker-card .map-live-label");
        if (pickerOverlay) pickerOverlay.textContent = "INTERACTIVE MAP";
        const pickerFoot = document.querySelector(".picker-foot");
        if (pickerFoot) pickerFoot.innerHTML = 'Region by coordinates: <strong id="point-region-label">—</strong>. Click on map or enter coordinates.';

        const s3DiagKicker = document.querySelector(".diagnosis-card .section-kicker");
        if (s3DiagKicker) s3DiagKicker.textContent = t.s3_diag_kicker;
        const s3DiagH2 = document.querySelector(".diagnosis-card h2");
        if (s3DiagH2) s3DiagH2.textContent = t.s3_diag_title;
        const diagBadge = document.getElementById("result-risk-badge");
        if (diagBadge && (diagBadge.textContent === "Sin análisis" || diagBadge.textContent === "No analysis")) {
          diagBadge.textContent = "No analysis";
        }
        const meterLabel = document.querySelector(".prob-meter-box .meter-header span");
        if (meterLabel) meterLabel.textContent = t.s3_meter_label;
        const diagStatusMsg = document.getElementById("result-diagnostic-text");
        if (diagStatusMsg && (diagStatusMsg.textContent.includes("Completa las variables") || diagStatusMsg.textContent.includes("Fill in the variables"))) {
          diagStatusMsg.textContent = "Fill in the variables and run the model to view an estimate.";
        }

        const tableKicker = document.querySelector(".table-panel .section-kicker");
        if (tableKicker) tableKicker.textContent = "LOCAL LOG";
        const tableH2 = document.querySelector(".table-panel h2");
        if (tableH2) tableH2.textContent = "Queries in this session";
        const tableNote = document.querySelector(".table-panel .table-note");
        if (tableNote) tableNote.textContent = "Cleared on page refresh";

        const ths = document.querySelectorAll(".data-table th");
        if (ths[0]) ths[0].textContent = t.s3_th_cell;
        if (ths[1]) ths[1].textContent = t.s3_th_date;
        if (ths[2]) ths[2].textContent = t.s3_th_prob;
        if (ths[3]) ths[3].textContent = t.s3_th_threshold;
        if (ths[4]) ths[4].textContent = t.s3_th_class;
        const emptyTd = document.querySelector(".empty-table");
        if (emptyTd) emptyTd.textContent = t.s3_table_empty;

        // Footer
        const footerSpans = document.querySelectorAll(".app-footer span");
        if (footerSpans[0]) footerSpans[0].textContent = "VIGÍA FUEGO · SCENARIO EXPLORER";
        if (footerSpans[1]) footerSpans[1].textContent = "Data: FIRMS and Open-Meteo · Boundaries: geoBoundaries · Not intended for operational alerts";

        // Dynamic components
        renderFeatureFields();
        updateWeatherProfileExplanation();
        renderLiveWeatherCard();
        updateModelBadge();
        updateScopeNotes();

        const curTabTitles = {
          "screen-grid": "Territorial Overview",
          "screen-history": "Satellite Observatory",
          "screen-point": "Inference Lab",
        };
        const curTabHeader = document.getElementById("header-section-name");
        if (curTabHeader) curTabHeader.textContent = curTabTitles[state.activeTab] || "";
      } else {
        // Reload page to reset natural Spanish HTML
        window.location.reload();
      }
    }

    if (toggleBtn) {
      toggleBtn.addEventListener("click", () => {
        const cur = document.documentElement.lang;
        const next = cur === "en" ? "es" : "en";
        localStorage.setItem("vigia_lang", next);
        applyLanguage(next);
      });
    }

    // Auto-apply English by default unless explicitly set to Spanish
    const urlParams = new URLSearchParams(window.location.search);
    const saved = urlParams.get("lang") || localStorage.getItem("vigia_lang") || "en";
    if (saved !== "es") {
      applyLanguage("en");
    }
  }
})();
