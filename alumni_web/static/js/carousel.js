// Kesan dan pesan bergeser pelan terus-menerus, seperti teks berjalan.
// Petaknya tetap bisa digeser dengan jari tanpa JavaScript; berkas ini
// menggandakan isi supaya putarannya mulus tanpa ujung, menambah titik
// navigasi dan tombol jeda, serta berhenti saat dibaca (disentuh/diarahkan/
// difokus), saat tab tersembunyi, atau saat pengguna meminta gerakan minimal.

const SPEED = 34; // piksel per detik — pelan, masih bisa dibaca sambil berjalan
const RESUME_AFTER_JUMP = 1400; // jeda singkat sesudah lompat lewat titik

function setup(root) {
  const track = root.querySelector(".carousel-track");
  const slides = Array.from(root.querySelectorAll(".carousel-slide"));
  if (!track || slides.length < 2) return;

  // Gandakan isi supaya putaran tak berujung: saat salinan pertama lewat,
  // posisi geser diputar ke awal tanpa terlihat. Salinan disembunyikan dari
  // pembaca layar dan tidak bisa difokus, supaya tidak terbaca dua kali.
  const clones = slides.map((slide) => {
    const clone = slide.cloneNode(true);
    clone.setAttribute("aria-hidden", "true");
    clone.querySelectorAll("a, button").forEach((el) => el.setAttribute("tabindex", "-1"));
    track.append(clone);
    return clone;
  });

  // Gerakan per bingkai menulis scrollLeft terus-menerus; snap dan smooth
  // bawaan CSS akan melawannya, jadi dimatikan lewat CSSOM (aman dari CSP).
  track.style.scrollSnapType = "none";
  track.style.scrollBehavior = "auto";

  let raf = null;
  let pos = track.scrollLeft;
  let last = 0;
  let stride = 1; // lebar satu slide berikut jaraknya
  let setWidth = 1; // lebar satu set slide asli
  let resumeAt = 0;
  let active = -1;
  // Pengguna yang minta gerakan minimal tidak dijalankan otomatis sama sekali.
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)");
  let wanted = !calm.matches;

  const nav = document.createElement("div");
  nav.className = "carousel-nav";

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "carousel-toggle";

  const dots = document.createElement("div");
  dots.className = "carousel-dots";
  const buttons = slides.map((_, i) => {
    const dot = document.createElement("button");
    dot.type = "button";
    dot.className = "carousel-dot";
    dot.setAttribute("aria-label", `Kutipan ${i + 1}`);
    dot.addEventListener("click", () => go(i));
    dots.append(dot);
    return dot;
  });

  nav.append(dots, toggle);
  root.append(nav);

  function measure() {
    // Jarak dari slide pertama ke salinannya = lebar satu set penuh. Selisih
    // rect kebal terhadap posisi gulir, jadi aman diukur kapan saja.
    setWidth = clones[0].getBoundingClientRect().left - slides[0].getBoundingClientRect().left;
    stride = setWidth / slides.length;
  }

  function mark() {
    const now = Math.round(pos / stride) % slides.length;
    if (now === active) return;
    active = now;
    buttons.forEach((dot, i) => {
      dot.setAttribute("aria-current", i === active ? "true" : "false");
    });
  }

  function tick(time) {
    if (raf === null) return;
    const dt = Math.min((time - last) / 1000, 0.1);
    last = time;
    // Kalau posisi berubah di luar kendali kita (digeser jari, misalnya),
    // lanjutkan bergeser dari sana.
    if (Math.abs(track.scrollLeft - pos) > 2) pos = track.scrollLeft;
    if (time >= resumeAt) {
      pos += SPEED * dt;
      if (pos >= setWidth) pos -= setWidth;
      track.scrollLeft = pos;
      mark();
    }
    raf = requestAnimationFrame(tick);
  }

  function start() {
    if (raf || !wanted) return;
    last = performance.now();
    raf = requestAnimationFrame(tick);
    toggle.textContent = "Jeda";
    toggle.setAttribute("aria-label", "Jeda gerakan kutipan");
  }

  function stop() {
    if (raf) {
      cancelAnimationFrame(raf);
      raf = null;
    }
    toggle.textContent = "Jalan";
    toggle.setAttribute("aria-label", "Jalankan gerakan kutipan");
  }

  // Lompat ke kutipan lewat arah terdekat (bisa melalui salinannya), lalu
  // gerakan pelan berlanjut setelah lompatan selesai.
  function go(target) {
    const n = slides.length;
    let delta = (target - (Math.round(pos / stride) % n) + n) % n;
    if (delta > n / 2) delta -= n;
    let goal = pos + delta * stride;
    if (goal < 0) goal += setWidth;
    resumeAt = performance.now() + RESUME_AFTER_JUMP;
    track.scrollTo({ left: goal, behavior: calm.matches ? "auto" : "smooth" });
    pos = goal;
    mark();
  }

  toggle.addEventListener("click", () => {
    wanted = !raf;
    if (wanted) start();
    else stop();
  });

  // Berhenti saat sedang dibaca atau dijelajah dengan papan ketik, dan saat
  // tabnya tidak terlihat supaya tidak berputar sia-sia.
  root.addEventListener("pointerenter", stop);
  root.addEventListener("pointerleave", () => wanted && start());
  root.addEventListener("focusin", stop);
  root.addEventListener("focusout", () => {
    if (!root.contains(document.activeElement) && wanted) start();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stop();
    else if (wanted) start();
  });
  calm.addEventListener("change", (event) => {
    wanted = !event.matches;
    if (wanted) start();
    else stop();
  });
  window.addEventListener("resize", () => {
    measure();
    pos = track.scrollLeft;
  });

  measure();
  mark();
  if (wanted) start();
  else stop();
}

document.querySelectorAll("[data-carousel]").forEach(setup);
