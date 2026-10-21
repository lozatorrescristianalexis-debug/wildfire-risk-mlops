// Vigía Fuego: retrospective hotspot explorer
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

  const PROFILE_LABELS = {
    observed: "clima histórico observado",
    dry: "días cálidos y secos regionales",
    wet: "días húmedos regionales",
  };

  function updateWeatherProfileExplanation() {
    const selected = document.getElementById("weather-preset-select").value;
    const observedDate = state.regionWeather?.observed_date || "la fecha indicada";
    const descriptions = {
      observed: `Se usan datos históricos de Open-Meteo de los días previos al ${observedDate} en cada región. Todas comparten la misma fecha de análisis.`,
      dry: "Cada región usa un día seco de su propio historial climático; las fechas pueden ser distintas.",
      wet: "Cada región usa un día húmedo de su propio historial climático; las fechas pueden ser distintas.",
    };
    document.getElementById("weather-profile-explainer").textContent =
      `${descriptions[selected]} El selector cambia temperatura, humedad, lluvia y viento que recibe el modelo; los colores indican probabilidad estimada de detección FIRMS, no el clima ni un pronóstico.`;
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
    const profiles = state.regionWeather?.profiles?.[profileKey];
    if (!profiles) return null;
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

  function applyObservedWeatherToPoint() {
    const lat = Number(document.getElementById("point-lat").value);
    const lon = Number(document.getElementById("point-lon").value);
    if (!pointInGeometry(lon, lat, geometryForRegion(state.regions.find((region) => region.id === "peru")))) return;
    const profile = weatherProfileAt(lon, lat, "observed");
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
        document.getElementById("model-f1").textContent = Number(state.modelInfo.test_metrics.f1).toFixed(3);
        document.getElementById("model-weather-resolution").textContent =
          state.modelInfo.training_region === "peru"
            ? "25 puntos regionales; cada celda usa el clima de su región"
            : "Una serie por celda de la malla";
        document.getElementById("point-date").value = state.modelInfo.date_end;
        document.getElementById("threshold-caption").textContent = `Umbral ${(state.modelInfo.selected_threshold * 100).toFixed(1)}%`;
        document.getElementById("result-threshold-marker").style.left = `${(state.modelInfo.selected_threshold * 100).toFixed(1)}%`;
      }

      if (weatherRes.ok) {
        state.regionWeather = await weatherRes.json();
        document.querySelector('#weather-preset-select option[value="observed"]').textContent =
          `Fecha histórica · ${state.regionWeather.observed_date}`;
        updateWeatherProfileExplanation();
        applyObservedWeatherToPoint();
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
      document.getElementById("grid-insight-title").textContent = "Datos no disponibles";
      document.getElementById("grid-insight-text").textContent = "No se pudo conectar con el servicio. Vuelve a cargar la página.";
    }
  }

  function populateRegionSelector() {
    const selector = document.getElementById("region-select");
    selector.innerHTML = "";
    state.regions.forEach((reg) => {
      const opt = document.createElement("option");
      opt.value = reg.id;
      opt.textContent = reg.name;
      if (reg.id === "madre_de_dios") opt.selected = true;
      selector.appendChild(opt);
    });

    state.selectedRegion = state.regions.find((reg) => reg.id === "madre_de_dios") || state.regions[0] || null;
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
      const scope = state.modelInfo.training_region === "peru" ? "Perú" : "Madre de Dios";
      const names = { hist_gradient_boosting: "HGB", xgboost: "XGBoost", logistic: "Logística", random_forest: "RF" };
      el.textContent = `${names[state.modelInfo.model] || state.modelInfo.model} · ${scope}`;
      el.title = `Modelo retrospectivo ${state.modelInfo.model}, entrenado en ${scope}`;
    }
  }

  function updateScopeNotes() {
    const trainingRegion = state.modelInfo?.training_region || "madre_de_dios";
    const note = document.getElementById("region-scope-note");
    const selected = state.selectedRegion?.id;
    const extrapolated = trainingRegion !== "peru" && selected && selected !== trainingRegion;
    const regional = trainingRegion === "peru" && selected !== "peru"
      ? state.modelInfo?.regional_test_metrics?.[selected] : null;
    note.classList.toggle("is-info", Boolean(regional?.metrics && regional.metrics.f1 >= 0.2));
    note.hidden = !extrapolated && !regional;
    if (extrapolated) {
      note.textContent = "Exploración fuera de Madre de Dios: el modelo se entrenó en esa región. Estos valores son extrapolaciones y no cuentan con validación para esta zona.";
    } else if (regional?.metrics) {
      note.textContent = `Validación temporal en ${regional.name}: ${regional.grid_cells} celdas, ${regional.positive_rows} casos con detección. PR-AUC ${regional.metrics.pr_auc.toFixed(3)} · F1 ${regional.metrics.f1.toFixed(3)}. ${regional.metrics.f1 < 0.2 ? "Desempeño local bajo; interpreta esta zona con cautela. " : ""}Son métricas del modelo nacional para celdas cuyo centro cae en la región.`;
    } else if (regional) {
      note.textContent = `La malla nacional no tiene suficientes ejemplos de ambas clases con centro en ${regional.name} para calcular métricas regionales. El modelo sí se entrenó con datos de todo el Perú; interpreta esta zona con cautela.`;
    }
    updatePointScopeNote();
  }

  function updatePointScopeNote() {
    const note = document.getElementById("point-scope-note");
    const lat = Number(document.getElementById("point-lat").value);
    const lon = Number(document.getElementById("point-lon").value);
    const located = [...state.regionFeatures.values()].find((feature) =>
      pointInGeometry(lon, lat, feature.geometry));
    const regionLabel = document.getElementById("point-region-label");
    if (regionLabel) regionLabel.textContent = located?.properties.name || "Fuera de Perú";
    const trainingRegion = state.modelInfo?.training_region || "madre_de_dios";
    const trainingGeometry = trainingRegion === "peru"
      ? geometryForRegion(state.regions.find((region) => region.id === "peru"))
      : state.regionFeatures.get(trainingRegion)?.geometry;
    const outside = trainingGeometry && Number.isFinite(lat) && Number.isFinite(lon) &&
      !pointInGeometry(lon, lat, trainingGeometry);
    note.hidden = !outside;
    if (outside) note.textContent = trainingRegion === "peru"
      ? "El punto está fuera de Perú, área de entrenamiento del modelo. Interpreta la probabilidad solo como una extrapolación exploratoria."
      : "El punto está fuera de Madre de Dios, área de entrenamiento del modelo. Interpreta la probabilidad solo como una extrapolación exploratoria.";
  }

  function onRegionChanged() {
    const reg = state.selectedRegion;
    if (!reg) return;
    updateScopeNotes();

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
      applyObservedWeatherToPoint();
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
        document.getElementById("header-section-name").textContent = {
          "screen-grid": "Panorama territorial",
          "screen-history": "Archivo de observaciones",
          "screen-point": "Análisis de un punto",
        }[target];
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
      renderScreen1Grid();
    });

    document.getElementById("weather-preset-select").addEventListener("change", () => {
      updateWeatherProfileExplanation();
      renderScreen1Grid();
    });
  }

  async function renderScreen1Grid() {
    if (!state.maps.grid || !state.selectedRegion) return;
    if (!state.regionWeather) {
      document.getElementById("grid-insight-title").textContent = "Clima histórico no disponible";
      document.getElementById("grid-insight-text").textContent = "No se pudieron cargar los perfiles meteorológicos regionales.";
      return;
    }
    const reg = state.selectedRegion;
    const requestId = ++state.gridRequestId;
    const recalculateButton = document.getElementById("btn-recalculate-grid");
    recalculateButton.disabled = true;
    document.getElementById("grid-insight-title").textContent = "Calculando escenario…";
    document.getElementById("grid-insight-text").textContent = "El modelo está evaluando la malla de esta región.";

    const presetKey = document.getElementById("weather-preset-select").value || "observed";

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
      document.getElementById("kpi-total-cells").textContent = visible.length.toLocaleString("es-PE");
      document.getElementById("kpi-high-risk").textContent = aboveThreshold.toLocaleString("es-PE");
      document.getElementById("kpi-max-prob").textContent = `${(maxProb * 100).toFixed(1)}%`;
      document.getElementById("kpi-threshold").textContent = `${(data.threshold * 100).toFixed(1)}%`;
      document.getElementById("grid-insight-title").textContent = aboveThreshold
        ? `${aboveThreshold} de ${visible.length} muestras clasificadas con detección`
        : "Ninguna muestra clasificada con detección";
      const datesNote = presetKey === "observed"
        ? `Fecha histórica: ${state.regionWeather.observed_date}.`
        : "Cada región usa un día histórico propio; no es un mismo día nacional.";
      document.getElementById("grid-insight-text").textContent = `${PROFILE_LABELS[presetKey]}. ${datesNote} Máximo calibrado: ${(maxProb * 100).toFixed(1)}% de detección FIRMS en una celda y día. No representa superficie que se incendiará.`;
      document.getElementById("distribution-total").textContent = `${visible.length} muestras`;
      const labels = { low: "<5%", moderate: "5–15%", high: "15–30%", extreme: "≥30%" };
      document.getElementById("distribution-bars").innerHTML = Object.keys(distribution).map((level) =>
        `<div class="dist-row"><span>${labels[level]}</span><div class="dist-track"><div class="dist-fill" style="width:${100 * distribution[level] / visible.length}%;background:${RISK_COLORS[level]}"></div></div><span class="dist-count">${distribution[level]}</span></div>`
      ).join("");
    } catch (err) {
      console.error("Error evaluating grid:", err);
      if (requestId === state.gridRequestId) {
        document.getElementById("grid-insight-title").textContent = "No se pudo calcular la malla";
        document.getElementById("grid-insight-text").textContent = "Comprueba la conexión con el servicio e inténtalo de nuevo.";
      }
    } finally {
      if (requestId === state.gridRequestId) recalculateButton.disabled = false;
    }
  }

  async function inspectGridPoint(event) {
    const region = state.selectedRegion;
    const lat = +event.latlng.lat.toFixed(5);
    const lon = +event.latlng.lng.toFixed(5);
    const popup = L.popup().setLatLng(event.latlng);
    if (!pointInGeometry(lon, lat, geometryForRegion(region))) {
      popup.setContent("Selecciona un punto dentro del límite de la región.").openOn(state.maps.grid);
      return;
    }
    popup.setContent("Calculando el valor exacto en esta coordenada…").openOn(state.maps.grid);
    const requestId = state.gridRequestId;
    const profile = weatherProfileAt(
      lon, lat, document.getElementById("weather-preset-select").value || "observed"
    );
    if (!profile) {
      popup.setContent("No hay datos meteorológicos para este punto.").openOn(state.maps.grid);
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
      content.innerHTML = `<div class="popup-title">Valor exacto del modelo</div>
        <div class="popup-row"><span>Latitud:</span><span class="popup-val">${lat}</span></div>
        <div class="popup-row"><span>Longitud:</span><span class="popup-val">${lon}</span></div>
        <div class="popup-row"><span>Fecha del clima:</span><span class="popup-val">${profile.date}</span></div>
        <div class="popup-row"><span>Prob. detección:</span><span class="popup-val">${(result.probability * 100).toFixed(1)}%</span></div>
        <div class="popup-row"><span>Clasificación:</span><span class="popup-val">${result.predicted_hotspot ? "Sobre umbral" : "Bajo umbral"}</span></div>`;
      const button = document.createElement("button");
      button.className = "btn btn-secondary";
      button.style.cssText = "margin-top:10px;width:100%;";
      button.textContent = "Analizar este punto →";
      button.addEventListener("click", () => transferToScreen3({
        cell_id: "punto_mapa", latitude: lat, longitude: lon,
      }, features, profile.date));
      content.appendChild(button);
      popup.setContent(content).openOn(state.maps.grid);
    } catch (error) {
      popup.setContent("No se pudo evaluar este punto. Inténtalo de nuevo.").openOn(state.maps.grid);
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
  function initScreen2Map() {
    const container = document.getElementById("map-history");
    if (!container) return;

    const reg = state.selectedRegion || { center: [-12.0, -70.25], zoom: 8 };
    state.maps.history = L.map(container, {
      center: reg.center,
      zoom: reg.zoom,
      zoomControl: true,
    });
    createDarkTileLayer().addTo(state.maps.history);

    state.layers.history = L.layerGroup().addTo(state.maps.history);
    drawRegionBorder(state.maps.history, "historyBorder");

    document.getElementById("filter-confidence").addEventListener("change", renderScreen2History);
    document.getElementById("filter-satellite").addEventListener("change", renderScreen2History);
  }

  async function renderScreen2History() {
    if (!state.maps.history) return;

    try {
      if (state.historicalFires.length === 0) {
        const response = await fetch("/api/historical-fires");
        if (response.ok) {
          state.historicalFires = await response.json();
        } else {
          throw new Error("No se pudo cargar el archivo");
        }
      }

      const confFilter = document.getElementById("filter-confidence").value;
      const satFilter = document.getElementById("filter-satellite").value;

      let filtered = state.historicalFires;
      if (confFilter !== "all") {
        filtered = filtered.filter((f) => confFilter === "nominal"
          ? ["nominal", "high"].includes(f.confidence)
          : f.confidence === "high");
      }
      if (satFilter !== "all") {
        filtered = filtered.filter((f) => (f.instrument || f.satellite || "").toUpperCase().includes(satFilter));
      }

      const unassigned = state.historicalFires.filter((fire) => !fire.mapped_region).length;
      filtered = filtered.filter((fire) => state.selectedRegion?.id === "peru"
        ? Boolean(fire.mapped_region)
        : fire.mapped_region === state.selectedRegion?.id);

      document.getElementById("kpi-history-total").textContent = filtered.length;
      document.getElementById("kpi-history-high").textContent = filtered.filter((f) => f.confidence === "high").length;
      document.getElementById("kpi-history-unmapped").textContent = unassigned;
      document.getElementById("history-empty").hidden = filtered.length > 0;
      const archiveDates = state.historicalFires.map((f) => f.acq_date).sort();
      if (archiveDates.length) document.getElementById("history-range").textContent =
        `Muestra local: ${archiveDates[0]} a ${archiveDates.at(-1)}.`;
      const relabeled = state.historicalFires.filter((fire) => fire.coordinate_issue === "label_mismatch").length;
      document.getElementById("history-summary").textContent =
        `${filtered.length} puntos visibles en ${state.selectedRegion?.name || "la región"}. La región se asigna por coordenadas: ${relabeled} etiquetas originales difieren de su ubicación y ${unassigned} puntos quedan fuera de Perú; estos últimos se excluyen del mapa.`;
      state.layers.history.clearLayers();

      filtered.forEach((fire) => {
        const color = fire.confidence === "high" ? RISK_COLORS.extreme : fire.confidence === "nominal" ? RISK_COLORS.moderate : "#91a4a8";

        const marker = L.circleMarker([fire.latitude, fire.longitude], {
          radius: fire.confidence === "high" ? 7 : 5,
          fillColor: color,
          color: "#1b252c",
          weight: 1.5,
          opacity: 0.9,
          fillOpacity: 0.8,
        });

        marker.bindPopup(`
          <div class="popup-title">Punto del archivo local</div>
          <div class="popup-row"><span>Fecha:</span><span class="popup-val">${escapeHtml(fire.acq_date)}</span></div>
          <div class="popup-row"><span>Coordenadas:</span><span class="popup-val">${fire.latitude}, ${fire.longitude}</span></div>
          <div class="popup-row"><span>Región por coordenadas:</span><span class="popup-val">${escapeHtml(fire.mapped_region_name)}</span></div>
          ${fire.coordinate_issue === "label_mismatch" ? `<div class="popup-row"><span>Etiqueta original:</span><span class="popup-val">${escapeHtml(fire.region)}</span></div>` : ""}
          <div class="popup-row"><span>Confianza:</span><span class="popup-val" style="color: ${color}; text-transform: uppercase;">${escapeHtml(fire.confidence)}</span></div>
          <div class="popup-row"><span>Satélite:</span><span class="popup-val">${escapeHtml(fire.satellite)}</span></div>
          <div class="popup-row"><span>FRP (Potencia):</span><span class="popup-val">${fire.frp} MW</span></div>
        `);

        state.layers.history.addLayer(marker);
      });
    } catch (err) {
      console.error("Error rendering historical fires:", err);
      document.getElementById("history-summary").textContent = "No se pudo cargar el archivo. Vuelve a intentarlo más tarde.";
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
      applyObservedWeatherToPoint();
      updatePointScopeNote();
    });

    for (const id of ["point-lat", "point-lon"]) {
      document.getElementById(id).addEventListener("change", () => {
        document.getElementById("point-cell-id").value = "punto_manual";
        syncMarkerFromInputs();
        applyObservedWeatherToPoint();
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

  function setupPointPredictionForm() {
    const form = document.getElementById("predict-form");
    const fieldsContainer = document.getElementById("feature-fields");

    // Feature schema definitions with min, max, step, and default values
    const featureDefs = [
      { name: "temperature_2m_max_lag1", label: "Temp. Máx. Día Anterior (°C)", min: -20, max: 50, step: 0.1, def: 25 },
      { name: "relative_humidity_2m_mean_lag1", label: "Humedad Media Día Anterior (%)", min: 10, max: 100, step: 1, def: 74 },
      { name: "precipitation_sum_lag1", label: "Lluvia Día Anterior (mm)", min: 0, max: 300, step: 0.1, def: 0 },
      { name: "wind_speed_10m_max_lag1", label: "Viento Máx. Día Anterior (km/h)", min: 0, max: 150, step: 0.1, def: 10 },
      { name: "temperature_2m_max_mean_3d", label: "Temp. Media 3 Días (°C)", min: -20, max: 50, step: 0.1, def: 25 },
      { name: "temperature_2m_max_mean_7d", label: "Temp. Media 7 Días (°C)", min: -20, max: 50, step: 0.1, def: 25 },
      { name: "relative_humidity_2m_mean_mean_7d", label: "Humedad Media 7 Días (%)", min: 10, max: 100, step: 1, def: 75 },
      { name: "wind_speed_10m_max_mean_7d", label: "Viento Medio 7 Días (km/h)", min: 0, max: 150, step: 0.1, def: 10 },
      { name: "precipitation_sum_sum_3d", label: "Lluvia Acumulada 3 Días (mm)", min: 0, max: 600, step: 0.1, def: 0 },
      { name: "precipitation_sum_sum_7d", label: "Lluvia Acumulada 7 Días (mm)", min: 0, max: 1000, step: 0.1, def: 0 },
      { name: "precipitation_sum_sum_30d", label: "Lluvia Acumulada 30 Días (mm)", min: 0, max: 2000, step: 1, def: 0 },
    ];

    fieldsContainer.innerHTML = "";
    featureDefs.forEach((f) => {
      const group = document.createElement("div");
      group.className = "form-group";
      group.innerHTML = `
        <label for="feat-${f.name}">${f.label}</label>
        <div class="input-slider-wrap">
          <input type="range" id="range-${f.name}" min="${f.min}" max="${f.max}" step="${f.step}" value="${f.def}">
          <input type="number" class="input-control" id="feat-${f.name}" name="${f.name}" min="${f.min}" max="${f.max}" step="any" value="${f.def}" required>
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

    const statusEl = document.getElementById("status-indicator");
    statusEl.textContent = `Caso ${kind === "positive" ? "con detección FIRMS" : "sin detección en la celda"} cargado. Puedes ajustar las variables antes de calcular.`;
  }

  async function executePointPrediction() {
    const btn = document.getElementById("submit-button");
    const statusEl = document.getElementById("status-indicator");
    btn.disabled = true;
    statusEl.textContent = `Calculando inferencia con ${state.modelInfo?.model || "el modelo"}...`;

    const cellId = document.getElementById("point-cell-id").value;
    const dateVal = document.getElementById("point-date").value;
    const lat = parseFloat(document.getElementById("point-lat").value);
    const lon = parseFloat(document.getElementById("point-lon").value);
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) {
      statusEl.textContent = "Introduce coordenadas válidas.";
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
      if (!response.ok) throw new Error("El servicio rechazó los datos. Revisa la fecha y las variables.");

      displayPredictionResult(payload, features);
      statusEl.textContent = `Análisis completado con ${payload.model}. La fecha identifica la observación; la probabilidad depende de las coordenadas y las variables meteorológicas.`;
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

    // Update Badge
    const badge = document.getElementById("result-risk-badge");
    badge.className = `risk-badge ${riskLevel}`;
    badge.textContent = result.predicted_hotspot ? "Sobre umbral" : "Bajo umbral";

    // Update Meter
    document.getElementById("result-prob-text").textContent = `${probPercent}%`;
    const meterFill = document.getElementById("result-meter-fill");
    meterFill.style.width = `${probPercent}%`;
    meterFill.style.backgroundColor = riskColor;

    const thresholdMarker = document.getElementById("result-threshold-marker");
    thresholdMarker.style.left = `${(threshold * 100).toFixed(1)}%`;
    document.getElementById("threshold-caption").textContent = `Umbral ${(threshold * 100).toFixed(1)}%`;

    // Diagnostic summary
    const diagText = document.getElementById("result-diagnostic-text");
    const classification = result.predicted_hotspot
      ? "El modelo clasifica esta combinación como celda con detección de foco de calor."
      : "El modelo clasifica esta combinación como celda sin detección de foco de calor.";
    diagText.textContent = `${classification} Probabilidad: ${probPercent}%; umbral: ${(threshold * 100).toFixed(1)}%. No confirma ni pronostica un incendio.`;

    // Add to history table
    addResultToTable(result);
  }

  function addResultToTable(result) {
    const tbody = document.getElementById("results");
    const emptyRow = tbody.querySelector("td[colspan]");
    if (emptyRow) tbody.innerHTML = "";

    const tr = document.createElement("tr");
    const isHotspot = result.predicted_hotspot;
    tr.innerHTML = `
      <td><strong>${escapeHtml(result.cell_id)}</strong></td>
      <td>${escapeHtml(result.date)}</td>
      <td>${(result.probability * 100).toFixed(1)}%</td>
      <td>${(result.threshold * 100).toFixed(1)}%</td>
      <td><span class="risk-badge ${isHotspot ? "extreme" : "low"}">${isHotspot ? "Sobre umbral" : "Bajo umbral"}</span></td>
    `;

    tbody.prepend(tr);
  }
})();
