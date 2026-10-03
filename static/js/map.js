// Farm Irrigation Workbench — Leaflet map

(function () {
  // ---- init map ----
  const map = L.map("map").setView([33.8455, -4.5860], 15);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 20,
    attribution: '© OpenStreetMap'
  }).addTo(map);

  // layer groups per collection
  const layers = {
    property:  L.layerGroup().addTo(map),
    water_points: L.layerGroup().addTo(map),
    basins:    L.layerGroup().addTo(map),
    sectors:   L.layerGroup().addTo(map),
    zones:     L.layerGroup().addTo(map),
    pipes:     L.layerGroup().addTo(map),
    rows:      L.layerGroup(),
    valves:    L.layerGroup().addTo(map),
    trees:     L.layerGroup(),
    driplines: L.layerGroup(),
    manifolds: L.layerGroup(),
  };

  // colors per collection
  const colors = {
    property:  "#000000",
    water_points: "#e91e63",
    basins:    "#0288d1",
    sectors:   "#00bcd4",
    zones:     "#3f51b5",
    pipes:     "#ff0000",
    rows:      "#00c853",
    valves:    "#e91e63",
    trees:     "#2e7d32",
    driplines: "#00897b",
    manifolds: "#ff9800",
  };

  // ---- helpers ----
  function addGeoJSONFeature(feature) {
    const coll = feature.properties.collection;
    if (!layers[coll]) return;

    const color = colors[coll] || "#888";
    const geom = feature.geometry;

    const style = {
      color: color,
      weight: coll === "property" ? 2 : 1.5,
      fillOpacity: coll === "zones" ? 0.15 : 0,
    };

    if (geom.type === "Point") {
      const latlng = [geom.coordinates[1], geom.coordinates[0]];
      const marker = L.circleMarker(latlng, {
        radius: coll === "trees" ? 2 : 5,
        color: color,
        fillColor: color,
        fillOpacity: 0.8,
      }).bindTooltip(feature.properties.name || "");
      layers[coll].addLayer(marker);
    } else if (geom.type === "LineString") {
      const latlngs = geom.coordinates.map(c => [c[1], c[0]]);
      const line = L.polyline(latlngs, style)
        .bindTooltip(feature.properties.name || "");
      layers[coll].addLayer(line);
    } else if (geom.type === "Polygon") {
      const latlngs = geom.coordinates[0].map(c => [c[1], c[0]]);
      const poly = L.polygon(latlngs, style)
        .bindTooltip(feature.properties.name || "");
      layers[coll].addLayer(poly);
    }
  }

  // ---- load data ----
  fetch(window.FARM_API.geojson)
    .then(r => r.json())
    .then(fc => {
      fc.features.forEach(addGeoJSONFeature);
    })
    .catch(err => console.error("GeoJSON load failed:", err));

  // ---- layer toggles UI ----
  const toggleBox = document.getElementById("layer-toggles");
  Object.keys(layers).forEach(name => {
    const checked = map.hasLayer(layers[name]);
    const id = `layer-${name}`;
    const wrapper = document.createElement("div");
    wrapper.className = "form-check";
    wrapper.innerHTML = `
      <input class="form-check-input" type="checkbox" id="${id}" ${checked ? "checked" : ""}>
      <label class="form-check-label" for="${id}">${name}</label>
    `;
    toggleBox.appendChild(wrapper);
    wrapper.querySelector("input").addEventListener("change", e => {
      if (e.target.checked) map.addLayer(layers[name]);
      else map.removeLayer(layers[name]);
    });
  });

  // ---- fit to property ----
  document.getElementById("fit-btn").addEventListener("click", () => {
    fetch(window.FARM_API.bounds)
      .then(r => r.json())
      .then(d => {
        if (d.bounds) {
          map.fitBounds(d.bounds, { padding: [20, 20] });
        }
      });
  });

})();
