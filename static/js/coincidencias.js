/*
 * Fase 4: coincidencias con el Catálogo SAP (Revisión 3, sección 8).
 *
 * - Mientras escribes la Descripción o el No. Parte, 400 ms después de la última tecla
 *   pregunta al servidor y muestra lo que encuentre para ESE renglón. Es solo informativo.
 * - El botón "Buscar coincidencias" revisa todos los renglones a la vez.
 * - La validación que cuenta es la del servidor al Enviar: esto solo ayuda a verla antes.
 *
 * Todo se pinta con textContent (nunca innerHTML con datos), así una descripción con
 * "<script>" se ve como texto y no se ejecuta.
 */
(function () {
  "use strict";

  var panel = document.getElementById("wd-coincidencias");
  if (!panel) return;
  var url = panel.dataset.url;
  var espera = null;

  function contenedor(el) { return el.closest("tr.wd-fila") || el.closest("form"); }
  function valor(caja, nombre) {
    var el = caja.querySelector('[name$="' + nombre + '"]');
    return el ? el.value.trim() : "";
  }
  function numero(caja) { var el = caja.querySelector('[name$="numero"]'); return el ? el.value : ""; }

  function consultar(caja) {
    var desc = valor(caja, "descripcion"), parte = valor(caja, "no_parte_original");
    if (desc.length < 3 && !parte) return Promise.resolve({ caja: caja, lista: [] });
    var q = new URLSearchParams({ descripcion: desc, no_parte: parte });
    return fetch(url + "?" + q.toString(), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) { return { caja: caja, lista: d.coincidencias }; });
  }

  function pintar(resultados) {
    panel.textContent = "";
    var conAlgo = resultados.filter(function (r) { return r.lista.length; });
    if (!conAlgo.length) {
      panel.textContent = "Sin coincidencias en el Catálogo SAP.";
      return;
    }
    conAlgo.forEach(function (r) {
      var titulo = document.createElement("div");
      titulo.className = "fw-semibold mt-1";
      titulo.textContent = numero(r.caja) ? "Partida " + numero(r.caja) : "Esta partida";
      panel.appendChild(titulo);
      var ul = document.createElement("ul");
      ul.className = "mb-1 small";
      r.lista.forEach(function (c) {
        var li = document.createElement("li");
        if (c.bloquea) li.className = "bloquea";
        li.textContent = c.tipo + " · " + c.codigo + " «" + c.descripcion + "» · No. Parte " + (c.no_parte || "—") +
          " · UMB " + (c.umb || "—") + " — " + c.motivo;
        ul.appendChild(li);
      });
      panel.appendChild(ul);
    });
  }

  document.addEventListener("input", function (e) {
    var n = e.target.name || "";
    if (!/(descripcion|no_parte_original)$/.test(n)) return;
    var caja = contenedor(e.target);
    clearTimeout(espera); // "debounce": solo se consulta cuando dejas de teclear
    espera = setTimeout(function () { consultar(caja).then(function (r) { pintar([r]); }); }, 400);
  });

  var boton = document.getElementById("buscar-coincidencias");
  if (boton) {
    boton.addEventListener("click", function () {
      var cajas = Array.prototype.slice.call(document.querySelectorAll("#filas tr.wd-fila"))
        .filter(function (f) { return !f.hidden; });
      panel.textContent = "Buscando…";
      Promise.all(cajas.map(consultar)).then(pintar);
    });
  }
})();
