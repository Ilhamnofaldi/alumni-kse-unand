// Setelah menyunting bagan, halaman di-muat ulang. Berkas ini mengembalikan
// posisi gulir dan panel yang terbuka supaya pengurus tidak jatuh ke puncak.

(function () {
  var KEY = "kse-org-editor";
  var root = document.querySelector("[data-org-editor]");
  if (!root) return;

  if ("scrollRestoration" in history) {
    history.scrollRestoration = "manual";
  }

  function pack() {
    var open = [];
    root.querySelectorAll("details[open][id]").forEach(function (el) {
      open.push(el.id);
    });
    sessionStorage.setItem(
      KEY,
      JSON.stringify({
        path: location.pathname,
        y: window.scrollY,
        open: open,
      })
    );
  }

  root.addEventListener("submit", function (event) {
    if (event.target && event.target.tagName === "FORM") pack();
  });

  var raw = sessionStorage.getItem(KEY);
  if (!raw) return;
  var data;
  try {
    data = JSON.parse(raw);
  } catch (err) {
    sessionStorage.removeItem(KEY);
    return;
  }
  var savedPath = ((data && data.path) || "").split("?")[0];
  if (!data || savedPath !== location.pathname) {
    sessionStorage.removeItem(KEY);
    return;
  }
  sessionStorage.removeItem(KEY);

  function restore() {
    (data.open || []).forEach(function (id) {
      var el = document.getElementById(id);
      if (el && el.tagName === "DETAILS") el.open = true;
    });
    var hash = (location.hash || "").replace(/^#/, "");
    if (hash) {
      var target = document.getElementById(hash);
      if (target && target.scrollIntoView) {
        target.scrollIntoView();
        return;
      }
    }
    if (typeof data.y === "number") window.scrollTo(0, data.y);
  }

  if (document.readyState === "complete") {
    restore();
    return;
  }
  window.addEventListener("load", function () {
    restore();
    requestAnimationFrame(restore);
  });
})();
