/*
 * Bandeja "Pendientes de mi atención".
 *   1. "Seleccionar todas" marca o desmarca todas las casillas.
 *   2. Antes de aplicar una acción, pide confirmación con el número de partidas y folios.
 *      Si la acción pide motivo, revisa que CADA partida marcada tenga el suyo.
 *      Al escribir un motivo, el renglón se marca solo.
 *   3. DM: pegar una columna de Excel en Código SAP llena las celdas hacia abajo.
 * El servidor vuelve a revisar todo; esto solo evita errores de dedo.
 */
(function () {
  "use strict";
  var form = document.getElementById("form-bandeja");
  if (!form) return;
  var casillas = function () { return Array.prototype.slice.call(form.querySelectorAll('input[name="partidas"]')); };

  var todas = document.getElementById("todas");
  if (todas) todas.addEventListener("change", function () {
    casillas().forEach(function (c) { c.checked = todas.checked; });
  });

  form.addEventListener("submit", function (e) {
    var boton = e.submitter;
    if (!boton || boton.hasAttribute("data-codigos")) return; // Terminar: no usa las casillas
    var marcadas = casillas().filter(function (c) { return c.checked; });
    if (!marcadas.length) { e.preventDefault(); window.alert("Selecciona al menos una partida."); return; }
    if (boton.hasAttribute("data-motivo")) {
      var vacios = marcadas.map(function (c) { return c.closest("tr").querySelector(".wd-motivo"); })
        .filter(function (m) { return !m.value.trim(); });
      form.querySelectorAll(".wd-motivo").forEach(function (m) { m.classList.remove("is-invalid"); });
      if (vacios.length) {
        e.preventDefault();
        vacios.forEach(function (m) { m.classList.add("is-invalid"); });
        window.alert("Escribe el motivo de cada partida marcada (" + vacios.length + " sin motivo).");
        vacios[0].focus();
        return;
      }
    }
    // Cuenta los folios distintos (cada casilla trae su folio en data-folio).
    var folios = {};
    marcadas.forEach(function (c) { folios[c.dataset.folio] = true; });
    if (boton.hasAttribute("data-exportar")) return; // exportar no cambia nada: sin confirmación
    var texto = "Vas a " + boton.getAttribute("data-verbo") + " " + marcadas.length + " partida(s) de " +
      Object.keys(folios).length + " folio(s). ¿Continuar?";
    if (!window.confirm(texto)) e.preventDefault();
  });

  // Escribir un motivo marca su renglón: es casi seguro que quieres actuar sobre esa partida.
  form.addEventListener("input", function (e) {
    if (!e.target.classList.contains("wd-motivo")) return;
    var casilla = e.target.closest("tr").querySelector('input[name="partidas"]');
    if (e.target.value.trim()) casilla.checked = true;
    e.target.classList.remove("is-invalid");
  });

  // Enter dentro del motivo o de un código NO envía el formulario. Sin esto, el navegador
  // "presiona" el primer botón (Aprobar o Terminar) y parece que el campo no acepta texto.
  form.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && e.target.matches('input[type="text"], input:not([type]), input[inputmode]')) e.preventDefault();
  });

  // Pegado de una columna de códigos: renglones separados por salto de línea.
  var codigos = Array.prototype.slice.call(form.querySelectorAll(".wd-codigo"));
  codigos.forEach(function (input, i) {
    input.addEventListener("paste", function (e) {
      var texto = (e.clipboardData || window.clipboardData).getData("text");
      if (!/\n/.test(texto.trim())) return; // un solo valor: pegado normal
      e.preventDefault();
      texto.replace(/\r/g, "").trim().split("\n").forEach(function (valor, j) {
        if (codigos[i + j]) codigos[i + j].value = valor.split("\t")[0].trim();
      });
    });
  });
})();
