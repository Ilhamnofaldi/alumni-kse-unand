// Konfirmasi hapus tanpa handler sebaris, supaya lolos CSP script-src 'self'.
document.addEventListener("submit", function (event) {
  var form = event.target;
  if (!form || form.tagName !== "FORM") return;
  var message = form.getAttribute("data-confirm");
  if (!message) return;
  if (!window.confirm(message)) event.preventDefault();
});
