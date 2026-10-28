// Apply the saved theme before first paint (no flash). A file, not an inline script, so the
// Content-Security-Policy can forbid inline scripts.
try {
  var t = localStorage.getItem("wtpdm.theme");
  if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
} catch (_) {
  /* storage blocked: follow the OS setting */
}
