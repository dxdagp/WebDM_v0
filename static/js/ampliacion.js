/*
 * Tabla tipo Excel de AMPL_ZRA (ampliación de material a Centro).
 *
 * Igual que captura.js (AMAT), pero con las columnas de Dave:
 *   Material | Centro nuevo | Almacén nuevo | Centro modelo | Almacén modelo | Planificador | Grupo de compras
 *
 * Lo que hace en el navegador:
 *   1. Al escribir o pegar el Material, pregunta al servidor su descripción y en qué Centros
 *      existe, y propone el primero como Centro modelo (y su almacén predeterminado).
 *   2. Al elegir el Centro nuevo, propone su almacén, planificador y grupo de compras, y muestra el CeBe.
 *   3. Pegado de bloques desde Excel, agregar y quitar renglones, aviso de cambios sin guardar.
 *
 * Es solo ayuda visual: al guardar, el servidor valida y propone todo de nuevo.
 */
(function () {
  "use strict";

  var form = document.getElementById("form-captura");
  if (!form) return;
  var cuerpo = document.getElementById("filas");
  var plantilla = document.getElementById("fila-vacia");
  var total = form.querySelector('input[name$="-TOTAL_FORMS"]');
  var datos = JSON.parse(document.getElementById("datos-automaticos").textContent);

  // Columnas que se pegan, en orden. Descripción, CeBe y Estado son automáticas: no se pegan.
  var COLUMNAS = ["codigo_sap", "centro", "almacen_destino", "centro_origen", "almacen_modelo", "planificador", "grupo_compras"];
  // Catálogos que dependen de un Centro y de cuál: el nuevo (destino) o el modelo (origen).
  var DEPENDE_DE = { almacen_destino: "centro", planificador: "centro", grupo_compras: "centro", almacen_modelo: "centro_origen" };

  function filas() { return Array.prototype.slice.call(cuerpo.querySelectorAll("tr.wd-fila")); }
  function campo(fila, nombre) { return fila.querySelector('[name$="-' + nombre + '"]'); }
  function textoCentro(select) { return select && select.selectedIndex > 0 ? select.options[select.selectedIndex].text : ""; }

  // ---- 2. Propuestas por Centro --------------------------------------------------
  function proponer(fila, nombre, mapa, centro) {
    var el = campo(fila, nombre);
    if (el && !el.value && mapa[centro]) el.value = mapa[centro];
  }
  function alCambiarDestino(fila) {
    var centro = campo(fila, "centro").value;
    proponer(fila, "almacen_destino", datos.almacen, centro);
    proponer(fila, "planificador", datos.planificador, centro);
    proponer(fila, "grupo_compras", datos.grupo, centro);
    fila.querySelector('[data-auto="cebe"]').textContent = datos.cebe[centro] || "—";
  }
  function alCambiarOrigen(fila) {
    proponer(fila, "almacen_modelo", datos.almacen, campo(fila, "centro_origen").value);
  }

  // ---- 1. Material: descripción y Centro modelo ------------------------------------
  function consultarMaterial(fila) {
    var codigo = campo(fila, "codigo_sap").value.trim();
    var celda = fila.querySelector('[data-auto="descripcion"]');
    if (!/^\d{6}$/.test(codigo)) { celda.textContent = codigo ? "Debe tener 6 dígitos" : "—"; return; }
    fetch(datos.urlMaterial + "?codigo=" + encodeURIComponent(codigo), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (m) {
        if (!m.existe) { celda.textContent = "No existe en el catálogo"; return; }
        celda.textContent = m.descripcion;
        var origen = campo(fila, "centro_origen");
        var destino = campo(fila, "centro").value;
        if (!origen.value) {
          var primero = m.centros.filter(function (c) { return String(c.id) !== destino; })[0];
          if (primero) { origen.value = String(primero.id); alCambiarOrigen(fila); }
        }
        origen.title = "El material existe en: " + m.centros.map(function (c) { return c.codigo; }).join(", ");
      })
      .catch(function () { celda.textContent = "—"; });
  }

  // ---- 3. Renglones y pegado ------------------------------------------------------
  function siguienteNumero() {
    var mayor = 0;
    filas().forEach(function (f) { mayor = Math.max(mayor, parseInt(campo(f, "numero").value, 10) || 0); });
    return mayor + 10;
  }
  function agregarFila() {
    if (!plantilla) return null; // en la corrección no se agregan partidas
    var indice = parseInt(total.value, 10);
    cuerpo.insertAdjacentHTML("beforeend", plantilla.innerHTML.replace(/__prefix__/g, String(indice)));
    total.value = indice + 1;
    var fila = filas()[filas().length - 1];
    campo(fila, "numero").value = siguienteNumero();
    return fila;
  }
  function quitarFila(fila) {
    fila.querySelectorAll("input, select").forEach(function (el) { el.value = ""; });
    fila.hidden = true;
  }

  function elegirOpcion(select, texto, fila) {
    var buscado = texto.trim().toUpperCase();
    if (!buscado) { select.value = ""; return; }
    var nombre = select.name.split("-").pop();
    var centroTexto = DEPENDE_DE[nombre] ? textoCentro(campo(fila, DEPENDE_DE[nombre])) : "";
    var candidatos = Array.prototype.filter.call(select.options, function (op) {
      if (!op.value) return false;
      var partes = op.text.toUpperCase().split(" · "); // "MTTU · RC01"
      return op.text.toUpperCase() === buscado || partes.indexOf(buscado) !== -1;
    });
    // El mismo almacén (RC01) existe en varios Centros: se prefiere el del Centro que le toca.
    var elegido = candidatos.filter(function (op) { return !centroTexto || op.text.indexOf(centroTexto + " · ") === 0; })[0]
      || candidatos[0];
    select.value = elegido ? elegido.value : "";
    if (!elegido) select.closest("td").classList.add("con-error");
  }

  function pegar(evento) {
    var celda = evento.target;
    var fila = celda.closest("tr.wd-fila");
    var inicial = COLUMNAS.indexOf((celda.name || "").split("-").pop());
    var texto = (evento.clipboardData || window.clipboardData).getData("text");
    if (!fila || inicial === -1 || !/[\t\n]/.test(texto)) return; // una sola celda: pegado normal
    evento.preventDefault();
    var renglones = texto.replace(/\r/g, "").replace(/\n$/, "").split("\n");
    var visibles = filas().filter(function (f) { return !f.hidden; });
    var inicio = visibles.indexOf(fila);
    renglones.forEach(function (renglon, i) {
      var destino = visibles[inicio + i] || agregarFila();
      if (!destino) return;
      // Primero los Centros (las demás columnas dependen de ellos), luego el resto.
      var valores = renglon.split("\t");
      var orden = valores.map(function (_, j) { return j; }).sort(function (a, b) {
        var ca = /centro/.test(COLUMNAS[inicial + a] || "") ? 0 : 1, cb = /centro/.test(COLUMNAS[inicial + b] || "") ? 0 : 1;
        return ca - cb || a - b;
      });
      orden.forEach(function (j) {
        var nombre = COLUMNAS[inicial + j];
        if (!nombre) return;
        var el = campo(destino, nombre);
        if (el.tagName === "SELECT") elegirOpcion(el, valores[j], destino);
        else el.value = valores[j].trim();
      });
      alCambiarDestino(destino);
      alCambiarOrigen(destino);
      consultarMaterial(destino);
    });
    hayCambios = true;
  }

  var hayCambios = false;
  window.addEventListener("beforeunload", function (e) { if (hayCambios) { e.preventDefault(); e.returnValue = ""; } });
  form.addEventListener("submit", function () { hayCambios = false; });

  cuerpo.addEventListener("paste", pegar);
  cuerpo.addEventListener("input", function () { hayCambios = true; });
  cuerpo.addEventListener("change", function (e) {
    hayCambios = true;
    var fila = e.target.closest("tr.wd-fila");
    var nombre = e.target.name.split("-").pop();
    if (nombre === "codigo_sap") consultarMaterial(fila);
    else if (nombre === "centro") alCambiarDestino(fila);
    else if (nombre === "centro_origen") alCambiarOrigen(fila);
  });
  cuerpo.addEventListener("click", function (e) {
    if (e.target.matches("[data-quitar]")) { quitarFila(e.target.closest("tr.wd-fila")); hayCambios = true; }
  });
  var botonAgregar = document.getElementById("agregar");
  if (botonAgregar) botonAgregar.addEventListener("click", function () { agregarFila(); });

  // Al abrir un borrador: mostrar descripción y CeBe de lo que ya está capturado.
  filas().forEach(function (f) {
    var centro = campo(f, "centro").value;
    f.querySelector('[data-auto="cebe"]').textContent = datos.cebe[centro] || "—";
    if (campo(f, "codigo_sap").value) consultarMaterial(f);
  });
})();
