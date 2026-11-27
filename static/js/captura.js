/*
 * Tabla tipo Excel de WebDM (Revisión 3, sección 6).
 *
 * Hace cuatro cosas en el navegador:
 *   1. Pegado masivo desde Excel a partir de la celda seleccionada.
 *   2. Agregar y quitar renglones (actualizando el conteo del formset).
 *   3. Llenar las columnas automáticas: CeBe, Tipo de Material, Almacén y el
 *      Grupo de compras predeterminado del Centro.
 *   4. Avisar si sales de la página con cambios sin guardar.
 *
 * Todo esto es comodidad: el servidor vuelve a validar y calcular todo al guardar.
 */
(function () {
  "use strict";

  var form = document.getElementById("form-captura");
  if (!form) return;

  var cuerpo = document.getElementById("filas");
  var plantilla = document.getElementById("fila-vacia");
  var total = form.querySelector('input[name$="-TOTAL_FORMS"]');
  var prefijo = total.name.replace("-TOTAL_FORMS", ""); // normalmente "form"
  var datos = JSON.parse(document.getElementById("datos-automaticos").textContent);

  // Columnas que se pueden pegar, en el orden visual de la Revisión 3.
  // Partida y las columnas automáticas no forman parte del pegado.
  var COLUMNAS = [
    "centro", "descripcion", "ubicacion", "no_parte_original", "tipo_unidad", "marca", "version",
    "anio_modelo", "compatibilidad", "umb", "grupo_articulos", "categoria_valoracion", "grupo_compras",
  ];

  function filas() { return Array.prototype.slice.call(cuerpo.querySelectorAll("tr.wd-fila")); }
  function campo(fila, nombre) { return fila.querySelector('[name$="-' + nombre + '"]'); }

  // ---- 3. Columnas automáticas ------------------------------------------------
  function actualizarAutomaticos(fila) {
    var centro = campo(fila, "centro").value;
    var categoria = campo(fila, "categoria_valoracion").value;
    fila.querySelector('[data-auto="cebe"]').textContent = datos.cebe[centro] || "—";
    fila.querySelector('[data-auto="almacen"]').textContent = datos.almacen[centro] || "—";
    fila.querySelector('[data-auto="tipo"]').textContent = datos.tipoMaterial[categoria] || "—";
  }

  function alCambiarCentro(fila) {
    var centro = campo(fila, "centro").value;
    var grupo = campo(fila, "grupo_compras");
    // Propone el grupo predeterminado del Centro si el usuario aún no eligió uno.
    if (!grupo.value && datos.grupoPredeterminado[centro]) grupo.value = datos.grupoPredeterminado[centro];
    actualizarAutomaticos(fila);
  }

  // ---- 2. Agregar y quitar renglones ------------------------------------------
  function siguienteNumero() {
    var mayor = 0;
    filas().forEach(function (f) { mayor = Math.max(mayor, parseInt(campo(f, "numero").value, 10) || 0); });
    return mayor + 10; // partidas de 10 en 10: 10, 20, 30…
  }

  function agregarFila() {
    var indice = parseInt(total.value, 10);
    // El formset nombra cada campo "form-<renglón>-<campo>"; la plantilla trae "__prefix__".
    var html = plantilla.innerHTML.replace(/__prefix__/g, String(indice));
    cuerpo.insertAdjacentHTML("beforeend", html);
    total.value = indice + 1;
    var fila = filas()[filas().length - 1];
    campo(fila, "numero").value = siguienteNumero();
    return fila;
  }

  function quitarFila(fila) {
    // No borramos el <tr> para no desordenar la numeración del formset: lo vaciamos y ocultamos.
    // Un renglón vacío se ignora al guardar.
    fila.querySelectorAll("input, select").forEach(function (el) { el.value = ""; });
    fila.hidden = true;
  }

  // ---- 1. Pegado desde Excel --------------------------------------------------
  // Excel copia las celdas como texto: columnas separadas por tabulador (\t)
  // y renglones por salto de línea (\n o \r\n).
  function elegirOpcion(select, texto, fila) {
    var buscado = texto.trim().toUpperCase();
    if (!buscado) { select.value = ""; return; }
    var centro = select.name.endsWith("grupo_compras") ? campo(fila, "centro") : null;
    var centroTexto = centro && centro.selectedIndex > 0 ? centro.options[centro.selectedIndex].text : "";
    var candidatos = Array.prototype.filter.call(select.options, function (op) {
      if (!op.value) return false;
      var partes = op.text.toUpperCase().split(" · "); // las opciones se ven como "CODIGO · DESCRIPCIÓN"
      return op.text.toUpperCase() === buscado || partes.indexOf(buscado) !== -1;
    });
    // En Grupo de compras el mismo código puede existir en varios Centros: preferimos el del renglón.
    var elegido = candidatos.filter(function (op) { return !centroTexto || op.text.indexOf(centroTexto + " · ") === 0; })[0]
      || candidatos[0];
    select.value = elegido ? elegido.value : "";
    if (!elegido) select.closest("td").classList.add("con-error");
  }

  function pegar(evento) {
    var celda = evento.target;
    var fila = celda.closest("tr.wd-fila");
    var nombre = (celda.name || "").split("-").pop();
    var columnaInicial = COLUMNAS.indexOf(nombre);
    var texto = (evento.clipboardData || window.clipboardData).getData("text");
    if (!fila || columnaInicial === -1 || !/[\t\n]/.test(texto)) return; // una sola celda: pegado normal

    evento.preventDefault();
    var renglones = texto.replace(/\r/g, "").replace(/\n$/, "").split("\n");
    var visibles = filas().filter(function (f) { return !f.hidden; });
    var inicio = visibles.indexOf(fila);

    renglones.forEach(function (renglon, i) {
      var destino = visibles[inicio + i] || agregarFila();
      renglon.split("\t").forEach(function (valor, j) {
        var nombreCol = COLUMNAS[columnaInicial + j];
        if (!nombreCol) return; // sobran columnas a la derecha: se ignoran
        var el = campo(destino, nombreCol);
        if (el.tagName === "SELECT") elegirOpcion(el, valor, destino);
        else el.value = valor.trim();
      });
      alCambiarCentro(destino);
    });
    hayCambios = true;
  }

  // ---- 4. Aviso de cambios sin guardar ----------------------------------------
  var hayCambios = false;
  window.addEventListener("beforeunload", function (e) {
    if (hayCambios) { e.preventDefault(); e.returnValue = ""; }
  });
  form.addEventListener("submit", function () { hayCambios = false; });

  // ---- Conexión de eventos ----------------------------------------------------
  // "Delegación de eventos": escuchamos en la tabla completa en vez de en cada
  // celda, así también funciona con renglones agregados después.
  cuerpo.addEventListener("paste", pegar);
  cuerpo.addEventListener("input", function () { hayCambios = true; });
  cuerpo.addEventListener("change", function (e) {
    hayCambios = true;
    var fila = e.target.closest("tr.wd-fila");
    if (e.target.name.endsWith("-centro")) alCambiarCentro(fila);
    else actualizarAutomaticos(fila);
  });
  cuerpo.addEventListener("click", function (e) {
    if (e.target.matches("[data-quitar]")) { quitarFila(e.target.closest("tr.wd-fila")); hayCambios = true; }
  });
  document.getElementById("agregar").addEventListener("click", function () { agregarFila(); });

  filas().forEach(actualizarAutomaticos);
})();
