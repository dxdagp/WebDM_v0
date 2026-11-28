/*
 * Exportar el catálogo al portapapeles (pedido de Dave): pide al servidor el texto con
 * tabuladores (todo lo que dejan los filtros) y lo copia. Al pegarlo en Excel, cada dato
 * cae en su celda. Los demás formatos (.txt, .csv, Excel) son ligas normales de descarga.
 */
(function () {
  "use strict";
  var boton = document.querySelector("[data-portapapeles]");
  if (!boton) return;

  function copiarViejo(texto) {
    // navigator.clipboard solo funciona en https o en localhost. En http dentro de la red
    // de la empresa usamos el método antiguo: un textarea oculto y execCommand("copy").
    var area = document.createElement("textarea");
    area.value = texto;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    var ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok ? Promise.resolve() : Promise.reject(new Error("execCommand"));
  }

  boton.addEventListener("click", function () {
    var original = boton.textContent;
    boton.disabled = true;
    boton.textContent = "Copiando…";
    fetch(boton.dataset.portapapeles, { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (texto) {
        var renglones = texto.split("\r\n").filter(Boolean).length - 1; // sin encabezados
        var copia = navigator.clipboard && window.isSecureContext ? navigator.clipboard.writeText(texto) : copiarViejo(texto);
        return copia.then(function () { boton.textContent = "Copiado: " + renglones + " renglón(es)"; });
      })
      .catch(function () { boton.textContent = "No se pudo copiar"; })
      .finally(function () {
        setTimeout(function () { boton.textContent = original; boton.disabled = false; }, 2500);
      });
  });
})();
