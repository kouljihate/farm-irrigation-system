// Farm Irrigation System — shared Leaflet + Leaflet-Geoman map
(function () {
  "use strict";

  const cfg = window.FARM_MAP_CONFIG || {};
  const map = L.map(cfg.containerId || "map").setView([33.8455, -4.5860], 15);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 20,
    attribution: "© OpenStreetMap contributors"
  }).addTo(map);

  const layers = {
    property: L.layerGroup().addTo(map),
    water_points: L.layerGroup().addTo(map),
    basins: L.layerGroup().addTo(map),
    sectors: L.layerGroup().addTo(map),
    zones: L.layerGroup().addTo(map),
    pipes: L.layerGroup().addTo(map),
    rows: L.layerGroup(),
    valves: L.layerGroup().addTo(map),
    trees: L.layerGroup(),
    driplines: L.layerGroup(),
    manifolds: L.layerGroup()
  };

  const colors = {
    property: "#000000",
    water_points: "#e91e63",
    basins: "#0288d1",
    sectors: "#00bcd4",
    zones: "#3f51b5",
    pipes: "#ff0000",
    rows: "#00c853",
    valves: "#e91e63",
    trees: "#2e7d32",
    driplines: "#00897b",
    manifolds: "#ff9800"
  };

  const status = document.getElementById(cfg.statusId || "map-edit-status");

  function showStatus(kind, text) {
    if (!status) return;
    status.className = "zones-status " + kind;
    status.textContent = text;
  }

  function styleFor(coll) {
    return {
      color: colors[coll] || "#888",
      weight: coll === "property" ? 2 : 1.5,
      fillColor: colors[coll] || "#888",
      fillOpacity: coll === "zones" ? 0.15 : 0.05,
      opacity: 0.9
    };
  }

  function bindEditable(layer, feature) {
    layer.feature = feature;
    layer.pmIgnore = false;
    layer.bindTooltip(feature.properties?.name || feature.properties?.sector_code || "");
    return layer;
  }

  function addGeoJSONFeature(feature) {
    const coll = feature.properties?.collection;
    if (!layers[coll] || !feature.geometry) return;

    const geom = feature.geometry;
    const style = styleFor(coll);
    let layer;

    if (geom.type === "Point") {
      layer = L.circleMarker([geom.coordinates[1], geom.coordinates[0]], {
        radius: coll === "trees" ? 2 : 5,
        color: style.color,
        fillColor: style.color,
        fillOpacity: 0.85,
        weight: 1
      });
    } else if (geom.type === "LineString") {
      layer = L.polyline(
        geom.coordinates.map(c => [c[1], c[0]]),
        style
      );
    } else if (geom.type === "Polygon") {
      layer = L.polygon(
        geom.coordinates[0].map(c => [c[1], c[0]]),
        style
      );
    } else {
      return;
    }

    bindEditable(layer, feature);
    layers[coll].addLayer(layer);
  }

  function clearLayers() {
    Object.values(layers).forEach(group => group.clearLayers());
  }

  function geometryUrl(feature) {
    return window.FARM_API.geometryBase
      .replace("COLLECTION", encodeURIComponent(feature.properties.collection))
      .replace("OBJECT_ID", encodeURIComponent(feature.properties.id));
  }

  async function saveLayerGeometry(layer) {
    const feature = layer.feature;
    const props = feature?.properties || {};
    if (!props.collection || !props.id) {
      showStatus("err", "Cannot save this geometry: database identity is missing.");
      return;
    }

    const geojson = layer.toGeoJSON();
    try {
      const response = await fetch(geometryUrl(feature), {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({geometry: geojson.geometry})
      });
      const result = await response.json();
      if (!response.ok || !result.ok) {
        throw new Error(result.error || "geometry save failed");
      }
      feature.geometry = geojson.geometry;
      showStatus(
        "ok",
        "✓ Saved " + (props.name || props.collection) + " / تم الحفظ"
      );
    } catch (error) {
      showStatus("err", "✕ " + error.message);
    }
  }

  // Geoman is the single geometry-editing layer for the whole application.
  map.pm.setGlobalOptions({
    snappable: true,
    snapDistance: 20
  });
  map.pm.addControls({
    position: "topleft",
    drawMarker: false,
    drawCircleMarker: false,
    drawPolyline: false,
    drawRectangle: false,
    drawPolygon: false,
    drawCircle: false,
    drawText: false,
    editMode: true,
    dragMode: true,
    cutPolygon: false,
    removalMode: false,
    rotateMode: false
  });

  map.on("pm:editend", event => {
    if (event.layer) saveLayerGeometry(event.layer);
  });

  map.on("pm:dragend", event => {
    if (event.layer) saveLayerGeometry(event.layer);
  });

  async function loadData() {
    clearLayers();
    const response = await fetch(window.FARM_API.geojson);
    if (!response.ok) throw new Error("GeoJSON request failed");
    const fc = await response.json();
    (fc.features || []).forEach(addGeoJSONFeature);
    const boundsResponse = await fetch(window.FARM_API.bounds);
    const boundsData = await boundsResponse.json();
    if (boundsData.bounds) map.fitBounds(boundsData.bounds, {padding: [20, 20]});
    map.invalidateSize(true);
    return fc;
  }

  if (cfg.autoLoad !== false) {
    loadData().catch(err => showStatus("err", "Map load failed: " + err.message));
  }

  const toggleBox = document.getElementById("layer-toggles");
  if (toggleBox) {
    Object.keys(layers).forEach(name => {
      const id = "layer-" + name;
      const wrapper = document.createElement("div");
      wrapper.className = "form-check";
      const checked = map.hasLayer(layers[name]);
      wrapper.innerHTML =
        '<input class="form-check-input" type="checkbox" id="' + id + '"' +
        (checked ? " checked" : "") + '>' +
        '<label class="form-check-label" for="' + id + '">' + name + "</label>";
      toggleBox.appendChild(wrapper);
      wrapper.querySelector("input").addEventListener("change", e => {
        if (e.target.checked) map.addLayer(layers[name]);
        else map.removeLayer(layers[name]);
      });
    });
  }

  const fit = document.getElementById("fit-btn");
  if (fit) {
    fit.addEventListener("click", () => {
      fetch(window.FARM_API.bounds)
        .then(r => r.json())
        .then(d => {
          if (d.bounds) map.fitBounds(d.bounds, {padding: [20, 20]});
        });
    });
  }

  window.addEventListener("resize", () => map.invalidateSize(true));
  window.FARM_MAP_INSTANCE = {map, layers, addGeoJSONFeature, clearLayers, saveLayerGeometry, reload: loadData, fit: () => fetch(window.FARM_API.bounds).then(r => r.json()).then(d => { if (d.bounds) map.fitBounds(d.bounds, {padding:[20,20]}); })};
})();
