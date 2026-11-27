/*
 * Bandeja "Pendientes de mi atención".
 *   1. "Seleccionar todas" marca o desmarca todas las casillas.
 *   2. Antes de aplicar una acción, pide confirmación con el número de partidas y folios.
 *      Si la acción pide motivo y está vacío, avisa sin enviar.
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
    if (boton.hasAttribute("data-motivo") && !document.getElementById("motivo").value.trim()) {
      e.preventDefault(); window.alert("Escribe el motivo."); document.getElementById("motivo").focus(); return;
    }
    // Cuenta los folios distintos (cada casilla trae su folio en data-folio).
    var folios = {};
    marcadas.forEach(function (c) { folios[c.dataset.folio] = true; });
    var texto = "Vas a " + boton.getAttribute("data-verbo") + " " + marcadas.length + " partida(s) de " +
      Object.keys(folios).length + " folio(s). ¿Continuar?";
    if (!window.confirm(texto)) e.preventDefault();
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
