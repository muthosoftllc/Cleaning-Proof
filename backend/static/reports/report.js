// Progressive enhancement for public report pages. Served as a static file so
// the Content-Security-Policy can forbid inline scripts entirely.
(function () {
  "use strict";

  // Render ISO timestamps in the viewer's locale and timezone.
  document.querySelectorAll("[data-ts]").forEach(function (el) {
    var value = el.getAttribute("data-ts");
    if (!value || value === "None") return;
    var date = new Date(value);
    if (!isNaN(date)) el.textContent = date.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  });

  // Optional signature pad on the approval form.
  var canvas = document.getElementById("sig");
  var form = document.getElementById("approve-form");
  if (!canvas || !form) return;
  var ctx = canvas.getContext("2d");
  var drawing = false;
  var dirty = false;

  function resize() {
    var rect = canvas.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    dirty = false;
  }
  function point(e) {
    var rect = canvas.getBoundingClientRect();
    return [e.clientX - rect.left, e.clientY - rect.top];
  }

  resize();
  window.addEventListener("resize", resize);
  canvas.addEventListener("pointerdown", function (e) {
    drawing = true;
    var p = point(e);
    ctx.beginPath();
    ctx.moveTo(p[0], p[1]);
  });
  canvas.addEventListener("pointermove", function (e) {
    if (!drawing) return;
    var p = point(e);
    ctx.lineTo(p[0], p[1]);
    ctx.stroke();
    dirty = true;
  });
  ["pointerup", "pointerleave", "pointercancel"].forEach(function (type) {
    canvas.addEventListener(type, function () { drawing = false; });
  });
  document.getElementById("sig-clear").addEventListener("click", function () {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    dirty = false;
  });
  form.addEventListener("submit", function () {
    if (dirty) document.getElementById("sig-data").value = canvas.toDataURL("image/png");
  });
})();
