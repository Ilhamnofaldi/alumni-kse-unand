function notice(el, text, where) {
  const p = document.createElement("p");
  p.className = "empty";
  p.textContent = text;
  if (where === "before") {
    el.parentNode.insertBefore(p, el);
  } else {
    el.replaceChildren(p);
  }
}

function popupNode(point) {
  const wrap = document.createElement("div");
  wrap.className = "map-popup";
  const city = document.createElement("strong");
  city.textContent = point.city || "Kota belum terpetakan";
  wrap.append(city);
  if (point.province) {
    wrap.append(document.createElement("br"));
    wrap.append(document.createTextNode(point.province));
  }
  wrap.append(document.createElement("br"));
  wrap.append(document.createTextNode(`${point.count} alumni di area ini`));

  const people = point.alumni || [];
  const shown = people.slice(0, 8);
  if (shown.length) {
    const list = document.createElement("ul");
    list.className = "map-alumni";
    shown.forEach((person) => {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = `/alumni/${person.id}`;
      link.textContent = person.full_name || "Alumni";
      item.append(link);
      const bits = [];
      if (person.major_normalized) bits.push(person.major_normalized);
      if (person.cohort_year) bits.push(String(person.cohort_year));
      if (bits.length) {
        item.append(document.createTextNode(` · ${bits.join(" · ")}`));
      }
      list.append(item);
    });
    wrap.append(list);
  }

  const hidden = Math.max((point.count || 0) - shown.length, 0);
  const more = document.createElement("p");
  const directory = document.createElement("a");
  const cityQuery = encodeURIComponent(point.city || "");
  directory.href = `/direktori?kota=${cityQuery}`;
  directory.textContent = hidden > 0 ? `dan ${hidden} lainnya di direktori` : "Buka di direktori";
  more.append(directory);
  wrap.append(more);
  return wrap;
}

async function main() {
  const el = document.getElementById("map");
  if (!el) return;
  if (typeof L === "undefined") {
    notice(el, "Peta dasar gagal dimuat. Muat ulang halaman.");
    return;
  }
  const map = L.map(el).setView([-2.2, 118], 5);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap",
    maxZoom: 12,
  }).addTo(map);
  const markers = new Map();
  try {
    const res = await fetch("/api/map-points");
    if (!res.ok) throw new Error("map");
    const data = await res.json();
    const points = data.points || [];

    const coords = points.map((p) => [p.lat, p.lng]);
    if (coords.length > 1) {
      map.fitBounds(coords, { padding: [32, 32], maxZoom: 7, animate: false });
    } else if (coords.length === 1) {
      map.setView(coords[0], 7);
    }

    points.forEach((p) => {
      const radius = 5 + Math.sqrt(Math.min(p.count, 200)) * 2.4;
      const marker = L.circleMarker([p.lat, p.lng], {
        radius,
        color: "#07472a",
        weight: 1.5,
        fillColor: "#009048",
        fillOpacity: 0.3,
      })
        .bindPopup(popupNode(p), { maxWidth: 280 })
        .addTo(map);
      markers.set(`${p.city}|${p.lat}|${p.lng}`, marker);
    });
  } catch (err) {
    notice(el, "Titik sebaran belum bisa dimuat. Periksa jaringan.", "before");
  }

  document.querySelector("[data-map-cities]")?.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-lat]");
    if (!btn) return;
    const lat = Number(btn.dataset.lat);
    const lng = Number(btn.dataset.lng);
    if (Number.isNaN(lat) || Number.isNaN(lng)) return;
    map.setView([lat, lng], 8);
    const marker = markers.get(`${btn.dataset.city}|${lat}|${lng}`);
    if (marker) marker.openPopup();
  });
}

main();
