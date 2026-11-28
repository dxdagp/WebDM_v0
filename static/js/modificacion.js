/*
 * Tabla tipo Excel de MOD_ZRA / MOD_ZSA (modificación de materiales o servicios).
 *
 * Un renglón = un dato de un material:  Material | Centro | Dato | Valor nuevo
 *
 * Lo que hace en el navegador (ayuda visual; el servidor vuelve a validar todo):
 *   1. Al escribir el Material, trae su descripción y los valores actuales de cada dato.
 *   2. Al elegir el Dato (y el Centro, si el dato es por Centro), muestra el valor actual
 *      y sugiere valores del catálogo (grupo de artículos, ubicación, almacén, grupo de compras).
 *   3. Pegado desde Excel, de dos formas:
 *      a) Material, Centro, Dato, Valor nuevo (un dato por renglón, como la tabla).
 *      b) Con encabezados: Material, Centro y una columna por dato ("Marca", "Año Modelo"…).
 *         Pedido de Dave: cada renglón se separa en un renglón por cada dato con valor.
 */
(function () {
  "use strict";

  var form = document.getElementById("form-captura");
  if (!form) return;
  var cuerpo = document.getElementById("filas");
  var plantilla = document.getElementById("fila-vacia");
  var total = form.querySelector('input[name$="-TOTAL_FORMS"]');
  var datos = JSON.parse(document.getElementById("datos-automaticos").textContent);
  var materiales = {}; // código -> respuesta del servidor
  var pedidos = {};    // código -> promesa de esa respuesta (se pide una sola vez por código)

  var COLUMNAS = datos.servicio ? ["codigo_sap", "campo", "valor_nuevo"] : ["codigo_sap", "centro", "campo", "valor_nuevo"];
  var porCentro = {};
  datos.campos.forEach(function (c) { porCentro[c.valor] = c.porCentro; });

  function filas() { return Array.prototype.slice.call(cuerpo.querySelectorAll("tr.wd-fila")); }
  function campo(fila, nombre) { return fila.querySelector('[name$="-' + nombre + '"]'); }
  function normal(texto) { return (texto || "").normalize("NFD").replace(/[̀-ͯ]/g, "").trim().toUpperCase(); }

  // ---- Listas de sugerencias (datalist) por dato y Centro ----------------------------
  function lista(id, valores) {
    var dl = document.getElementById(id);
    if (!dl) {
      dl = document.createElement("datalist");
      dl.id = id;
      dl.innerHTML = (valores || []).map(function (v) { return '<option value="' + v.replace(/"/g, "&quot;") + '">'; }).join("");
      document.body.appendChild(dl);
    }
    return id;
  }
  function sugerencias(fila) {
    var dato = campo(fila, "campo").value, centro = campo(fila, "centro") ? campo(fila, "centro").value : "";
    var nuevo = campo(fila, "valor_nuevo");
    if (datos.catalogos[dato]) nuevo.setAttribute("list", lista("dl-" + dato, datos.catalogos[dato]));
    else if (datos.porCentro[dato] && centro) nuevo.setAttribute("list", lista("dl-" + dato + "-" + centro, datos.porCentro[dato][centro]));
    else nuevo.removeAttribute("list");
  }

  // ---- 1 y 2. Descripción y valor actual -------------------------------------------------
  function mostrarActual(fila) {
    var codigo = campo(fila, "codigo_sap").value.trim();
    var m = materiales[codigo];
    var dato = campo(fila, "campo").value;
    var celda = fila.querySelector('[data-auto="actual"]');
    var centroSel = campo(fila, "centro");
    if (centroSel) {
      // El Centro solo aplica a los datos por Centro: en los demás se deshabilita y se vacía.
      var aplica = !dato || porCentro[dato];
      centroSel.disabled = !aplica;
      if (!aplica) centroSel.value = "";
    }
    sugerencias(fila);
    if (!m || !m.existe || !dato) { celda.textContent = "—"; return; }
    var valor = porCentro[dato] ? ((m.porCentro[centroSel && centroSel.value] || {})[dato]) : m.valores[dato];
    if (porCentro[dato] && centroSel && centroSel.value && !m.porCentro[centroSel.value]) { celda.textContent = "No existe en ese Centro"; return; }
    celda.textContent = valor || (porCentro[dato] && !(centroSel && centroSel.value) ? "Elige el Centro" : "(vacío)");
  }
  function consultarMaterial(fila) {
    var codigo = campo(fila, "codigo_sap").value.trim();
    var celda = fila.querySelector('[data-auto="descripcion"]');
    if (!/^\d{6}$/.test(codigo)) { celda.textContent = codigo ? "Debe tener 6 dígitos" : "—"; mostrarActual(fila); return; }
    // Se guarda la PROMESA, no la respuesta: si 20 renglones piden el mismo código, sale una sola petición.
    if (!pedidos[codigo]) {
      pedidos[codigo] = fetch(datos.urlMaterial + "&codigo=" + encodeURIComponent(codigo), { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (m) { materiales[codigo] = m; return m; });
    }
    pedidos[codigo].then(function (m) {
      celda.textContent = m.existe ? m.descripcion : "No existe en el catálogo";
      mostrarActual(fila);
    }).catch(function () { celda.textContent = "—"; });
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
  function libres() { return filas().filter(function (f) { return !f.hidden && !campo(f, "codigo_sap").value && !campo(f, "campo").value; }); }

  // Un "Dato" escrito o pegado: acepta el código (MARCA) o el nombre ("Marca", "Año modelo").
  function datoDe(texto) {
    var buscado = normal(texto);
    var hallado = datos.campos.filter(function (c) { return c.valor === buscado || normal(c.texto) === buscado; })[0];
    return hallado ? hallado.valor : null;
  }
  function centroDe(texto) { return datos.centros[normal(texto)] || ""; }

  function llenar(fila, valores) {
    campo(fila, "codigo_sap").value = valores.codigo || "";
    if (campo(fila, "centro")) campo(fila, "centro").value = valores.centro || "";
    campo(fila, "campo").value = valores.dato || "";
    campo(fila, "valor_nuevo").value = valores.nuevo || "";
    if (valores.dato === null) campo(fila, "campo").closest("td").classList.add("con-error");
    consultarMaterial(fila);
  }

  function pegar(evento) {
    var celda = evento.target;
    var fila = celda.closest("tr.wd-fila");
    var texto = (evento.clipboardData || window.clipboardData).getData("text");
    if (!fila || !/[\t\n]/.test(texto)) return; // una sola celda: pegado normal
    evento.preventDefault();
    var renglones = texto.replace(/\r/g, "").replace(/\n$/, "").split("\n").map(function (r) { return r.split("\t"); });
    var nuevos = [];

    // ¿La primera línea son encabezados con nombres de datos? Entonces es un renglón por material.
    var encabezado = renglones[0];
    var columnasDato = encabezado.map(datoDe);
    if (columnasDato.filter(Boolean).length >= 1 && !/^\d{6}$/.test((encabezado[0] || "").trim())) {
      var iCentro = encabezado.map(normal).indexOf("CENTRO");
      renglones.slice(1).forEach(function (r) {
        columnasDato.forEach(function (dato, j) {
          var valor = (r[j] || "").trim();
          if (dato && valor) nuevos.push({ codigo: (r[0] || "").trim(), centro: porCentro[dato] && iCentro >= 0 ? centroDe(r[iCentro]) : "", dato: dato, nuevo: valor });
        });
      });
    } else {
      // Como la tabla, empezando en la columna donde se pegó.
      var inicial = Math.max(0, COLUMNAS.indexOf((celda.name || "").split("-").pop()));
      renglones.forEach(function (r) {
        var v = {};
        r.forEach(function (valor, j) { v[COLUMNAS[inicial + j]] = (valor || "").trim(); });
        nuevos.push({ codigo: v.codigo_sap, centro: v.centro ? centroDe(v.centro) : "", dato: v.campo ? datoDe(v.campo) : "", nuevo: v.valor_nuevo });
      });
    }
    var disponibles = libres();
    if (disponibles.indexOf(fila) === -1 && nuevos.length) disponibles.unshift(fila);
    nuevos.forEach(function (v) { llenar(disponibles.shift() || agregarFila(), v); });
    hayCambios = true;
  }

  var hayCambios = false;
  window.addEventListener("beforeunload", function (e) { if (hayCambios) { e.preventDefault(); e.returnValue = ""; } });
  form.addEventListener("submit", function () {
    hayCambios = false;
    // Un <select disabled> no se envía: se habilita al guardar para que el servidor reciba el vacío.
    form.querySelectorAll("select:disabled").forEach(function (s) { s.disabled = false; });
  });

  cuerpo.addEventListener("paste", pegar);
  cuerpo.addEventListener("input", function () { hayCambios = true; });
  cuerpo.addEventListener("change", function (e) {
    hayCambios = true;
    var fila = e.target.closest("tr.wd-fila");
    var nombre = e.target.name.split("-").pop();
    if (nombre === "codigo_sap") consultarMaterial(fila);
    else if (nombre === "campo" || nombre === "centro") mostrarActual(fila);
  });
  cuerpo.addEventListener("click", function (e) {
    if (e.target.matches("[data-quitar]")) { quitarFila(e.target.closest("tr.wd-fila")); hayCambios = true; }
  });
  var botonAgregar = document.getElementById("agregar");
  if (botonAgregar) botonAgregar.addEventListener("click", function () { agregarFila(); });

  // Al abrir un borrador: descripción y valor actual de lo ya capturado.
  filas().forEach(function (f) { if (campo(f, "codigo_sap").value) consultarMaterial(f); else mostrarActual(f); });
})();
