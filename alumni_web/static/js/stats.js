const FACULTY_LABELS = {
  pertanian: "Pertanian",
  teknik: "Teknik",
  fateta: "Teknologi Pertanian",
  fmipa: "FMIPA",
  peternakan: "Peternakan",
  feb: "FEB",
  hukum: "Hukum",
  fisip: "FISIP",
  fkm: "Kesehatan Masyarakat",
  farmasi: "Farmasi",
  kedokteran: "Kedokteran",
  fib: "Ilmu Budaya",
  fti: "Teknologi Informasi",
  keperawatan: "Keperawatan",
  fkg: "Kedokteran Gigi",
  lain: "Lainnya",
};

const STATUS_LABELS = {
  bekerja: "Bekerja",
  wirausaha: "Wirausaha",
  mahasiswa: "Mahasiswa",
  belum_bekerja: "Belum bekerja",
};

const OFFICE_LABELS = {
  ketua: "Ketua Paguyuban",
  wakil_ketua: "Wakil Ketua",
  sekretaris: "Sekretaris",
  bendahara: "Bendahara",
  community_development: "Community Development",
  humas: "Humas",
  humaniora: "Humaniora",
  pengabdian: "Pengabdian Masyarakat",
  rumah_anak_cerdas: "Rumah Anak Cerdas",
  pendidikan: "Pendidikan",
  kestari: "Kestari",
  kewirausahaan: "Kewirausahaan",
  anggota_divisi: "Anggota Divisi",
  sekbend_community_development: "Sekbend Community Development",
  sekbend_humas: "Sekbend Humas",
  sekbend_humaniora: "Sekbend Humaniora",
  sekbend_pengabdian: "Sekbend Pengabdian Masyarakat",
  sekbend_rumah_anak_cerdas: "Sekbend Rumah Anak Cerdas",
  sekbend_pendidikan: "Sekbend Pendidikan",
  sekbend_kestari: "Sekbend Kestari",
  sekbend_kewirausahaan: "Sekbend Kewirausahaan",
  mnb_community_development: "MnB Community Development",
  pj_universitas: "PJ Universitas",
  pj_fakultas: "PJ Fakultas",
  anggota_community_development: "Anggota Community Development",
  anggota_humas: "Anggota Humas",
  anggota_humaniora: "Anggota Humaniora",
  anggota_pengabdian: "Anggota Pengabdian Masyarakat",
  anggota_rumah_anak_cerdas: "Anggota Rumah Anak Cerdas",
  anggota_pendidikan: "Anggota Pendidikan",
  anggota_kestari: "Anggota Kestari",
  anggota_kewirausahaan: "Anggota Kewirausahaan",
  core: "Pengurus inti",
  lead: "Koordinator divisi",
  member: "Anggota divisi",
  pj: "Penanggung jawab",
};

const FACULTY_KEYS = Object.keys(FACULTY_LABELS);
const STATUS_KEYS = Object.keys(STATUS_LABELS);
const OFFICE_KEYS = Object.keys(OFFICE_LABELS);
const OFFICE_KIND_KEYS = ["core", "lead", "member", "pj"];

const MUTED = "#6f6a60";
const LINE = "#e2dbcb";
const SURFACE = "#ffffff";
const FALLBACK = [
  "#0a6b3d",
  "#c09030",
  "#2b6cb0",
  "#9b2c5a",
  "#c45c26",
  "#0e7c7b",
  "#5b4b8a",
  "#3d7a2e",
  "#b45309",
  "#1d4e89",
  "#a33b5d",
  "#4a6b3a",
];

function readToken(name, fallback) {
  const styles = getComputedStyle(document.documentElement);
  return styles.getPropertyValue(name).trim() || fallback;
}

function readPalette() {
  const colors = [];
  for (let i = 1; i <= 12; i += 1) {
    const value = readToken(`--chart-${i}`, "");
    if (value) colors.push(value);
  }
  return colors.length ? colors : FALLBACK;
}

function colorFor(kind, key, index) {
  const palette = readPalette();
  let slot = index;
  if (kind === "faculty") {
    const found = FACULTY_KEYS.indexOf(key);
    if (found >= 0) slot = found;
  } else if (kind === "status") {
    const found = STATUS_KEYS.indexOf(key);
    if (found >= 0) slot = found;
  } else if (kind === "office") {
    const kindSlot = OFFICE_KIND_KEYS.indexOf(key);
    if (kindSlot >= 0) {
      slot = kindSlot;
    } else {
      let lookup = key;
      if (key.startsWith("anggota_") && key !== "anggota_divisi") {
        lookup = key.slice("anggota_".length);
      } else if (key.startsWith("sekbend_")) {
        lookup = key.slice("sekbend_".length);
      } else if (key.startsWith("mnb_")) {
        lookup = key.slice("mnb_".length);
      }
      const found = OFFICE_KEYS.indexOf(lookup);
      if (found >= 0) slot = found;
    }
  }
  return palette[slot % palette.length];
}

function labels(kind, keys) {
  if (kind === "faculty") return keys.map((k) => FACULTY_LABELS[k] || k);
  if (kind === "status") return keys.map((k) => STATUS_LABELS[k] || k);
  if (kind === "office") return keys.map((k) => OFFICE_LABELS[k] || k);
  return keys.map((k) => String(k));
}

const node = document.getElementById("stats-data");
const offline = document.getElementById("chart-offline");

if (!node || typeof Chart === "undefined") {
  if (offline) offline.hidden = false;
} else {
  let stats;
  try {
    stats = JSON.parse(node.textContent);
  } catch (err) {
    if (offline) offline.hidden = false;
    stats = null;
  }
  if (!stats) {
    if (offline) offline.hidden = false;
  } else {
  const ink = readToken("--ink-3", MUTED);
  const line = readToken("--line", LINE);
  const surface = readToken("--surface", SURFACE);

  Chart.defaults.font.family =
    'Figtree, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif';
  Chart.defaults.font.size = 12;
  Chart.defaults.color = ink;

  function paintRank(canvas, names, colors) {
    const list = canvas.closest("figure")?.querySelector(".rank");
    if (!list) return;
    list.querySelectorAll("li").forEach((li) => {
      const cell = li.querySelector("span");
      if (!cell) return;
      const index = names.indexOf(cell.textContent.trim());
      if (index < 0) return;
      if (cell.querySelector(".swatch")) return;
      const dot = document.createElement("span");
      dot.className = "swatch";
      dot.style.background = colors[index];
      cell.prepend(dot);
    });
  }

  function paintList(selector) {
    const list = document.querySelector(selector);
    if (!list) return;
    const palette = readPalette();
    list.querySelectorAll("li").forEach((li, index) => {
      const cell = li.querySelector("span");
      if (!cell || cell.querySelector(".swatch")) return;
      const dot = document.createElement("span");
      dot.className = "swatch";
      dot.style.background = palette[index % palette.length];
      cell.prepend(dot);
    });
  }

  function packKeys(pack) {
    return (pack.keys || pack.labels || []).map((key) => String(key));
  }

  function packNames(kind, pack, keys) {
    if (pack.labels && pack.labels.length) return pack.labels.map((name) => String(name));
    return labels(kind, keys);
  }

  function doughnut(id, kind, pack) {
    const canvas = document.getElementById(id);
    if (!canvas || !pack) return;
    const data = pack.data || [];
    if (!data.length) return;
    const keys = packKeys(pack);
    const names = packNames(kind, pack, keys);
    const colors = keys.map((key, index) => colorFor(kind, key, index));
    new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: names,
        datasets: [
          {
            data,
            backgroundColor: colors,
            borderColor: surface,
            borderWidth: 2,
            hoverOffset: 0,
          },
        ],
      },
      options: {
        cutout: "68%",
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
      },
    });
    paintRank(canvas, names, colors);
  }

  function bars(id, kind, pack, axis) {
    const canvas = document.getElementById(id);
    if (!canvas || !pack) return;
    const data = pack.data || [];
    if (!data.length) return;
    const keys = packKeys(pack);
    const names = packNames(kind, pack, keys);
    const horizontal = axis === "y";
    const colors = keys.map((key, index) => colorFor(kind, key, index));
    const category = {
      grid: { display: false },
      border: { color: line },
      ticks: { color: ink, autoSkip: false },
    };
    if (horizontal) {
      category.afterFit = function afterFit(scale) {
        scale.width = Math.max(scale.width, 120);
      };
    }
    const value = {
      beginAtZero: true,
      border: { display: false },
      grid: { color: line },
      ticks: { color: ink, precision: 0 },
    };
    new Chart(canvas, {
      type: "bar",
      data: {
        labels: names,
        datasets: [
          {
            data,
            backgroundColor: colors,
            borderRadius: 2,
            maxBarThickness: horizontal ? 18 : 22,
          },
        ],
      },
      options: {
        indexAxis: horizontal ? "y" : "x",
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: horizontal
          ? { x: value, y: category }
          : { x: category, y: value },
      },
    });
    paintRank(canvas, names, colors);
  }

  bars("chart-faculty", "faculty", stats.faculty, "y");
  bars("chart-cohort", "cohort", stats.cohort);
  doughnut("chart-status", "status", stats.status);
  doughnut("chart-office", "office", stats.office);
  paintList(".rank-city");
  paintList(".rank-offices");
  }
}
