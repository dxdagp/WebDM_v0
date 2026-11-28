/*
 * Tabla tipo Excel de ASER_ZSA (alta de servicios): Tipo de servicio | Descripción | UMB | Grupo de artículos.
 *
 *   1. Agregar y quitar renglones; si hay un solo tipo de servicio, cada renglón nuevo ya lo trae con su UMB. Al cambiar el tipo,
 *      se propone la UMB predeterminada del tipo nuevo (si la UMB estaba vacía o era la del tipo anterior).
 *   2. Pegado de bloques desde Excel, empezando en la columna donde se pega. En las listas
 *      (UMB, Grupo de artículos) se acepta el código ("SER") o el texto completo de la opción.
 *   3. Aviso de cambios sin guardar.
 * Es solo ayuda visual: el servidor vuelve a validar todo.
 */
(function () {
  "use strict";

  var form = document.getElementById("form-captura");
  if (!form) return;
  var cuerpo = document.getElementById("filas");
  var plantilla = document.getElementById("fila-vacia");
  var total = form.querySelector('input[name$="-TOTAL_FORMS"]');
  var datos = JSON.parse(document.getElementById("datos-automaticos").textContent);
  var COLUMNAS = ["tipo_servicio", "descripcion", "umb", "grupo_articulos"];

  function filas() { return Array.prototype.slice.call(cuerpo.querySelectorAll("tr.wd-fila")); }
  function campo(fila, nombre) { return fila.querySelector('[name$="-' + nombre + '"]'); }

  function siguienteNumero() {
    var mayor = 0;
    filas().forEach(function (f) { mayor = Math.max(mayor, parseInt(campo(f, "numero").value, 10) || 0); });
    return mayor + 10;
  }
  function agregarFila() {
    if (!plantilla) return null;
    var indice = parseInt(total.value, 10);
    cuerpo.insertAdjacentHTML("beforeend", plantilla.innerHTML.replace(/__prefix__/g, String(indice)));
    total.value = indice + 1;
    var fila = filas()[filas().length - 1];
    campo(fila, "numero").value = siguienteNumero();
    if (datos.tipo) { campo(fila, "tipo_servicio").value = datos.tipo; proponerUmb(fila, ""); }
    return fila;
  }
  // UMB según el tipo: se cambia solo si estaba vacía o era la propuesta del tipo anterior (no pisa lo que eligió el usuario).
  function proponerUmb(fila, tipoAnterior) {
    var umb = campo(fila, "umb");
    var nueva = datos.umbPorTipo[campo(fila, "tipo_servicio").value];
    if (nueva && (!umb.value || umb.value === datos.umbPorTipo[tipoAnterior])) umb.value = nueva;
  }
  function quitarFila(fila) {
    fila.querySelectorAll("input, select").forEach(function (el) { el.value = ""; });
    fila.hidden = true;
  }

  function elegirOpcion(select, texto) {
    var buscado = texto.trim().toUpperCase();
    if (!buscado) return; // celda vacía: se queda lo propuesto
    var op = Array.prototype.filter.call(select.options, function (o) {
      var t = o.text.toUpperCase();
      return o.value && (t === buscado || t.split(" · ")[0] === buscado);
    })[0];
    select.value = op ? op.value : "";
    if (!op) select.closest("td").classList.add("con-error");
  }

  function pegar(evento) {
    var celda = evento.target;
    var fila = celda.closest("tr.wd-fila");
    var inicial = COLUMNAS.indexOf((celda.name || "").split("-").pop());
    var texto = (evento.clipboardData || window.clipboardData).getData("text");
    if (!fila || inicial === -1 || !/[\t\n]/.test(texto)) return;
    evento.preventDefault();
    var renglones = texto.replace(/\r/g, "").replace(/\n$/, "").split("\n");
    var visibles = filas().filter(function (f) { return !f.hidden; });
    var inicio = visibles.indexOf(fila);
    renglones.forEach(function (renglon, i) {
      var destino = visibles[inicio + i] || agregarFila();
      if (!destino) return;
      var tipoAntes = campo(destino, "tipo_servicio").value;
      renglon.split("\t").forEach(function (valor, j) {
        var nombre = COLUMNAS[inicial + j];
        if (!nombre) return;
        var el = campo(destino, nombre);
        if (el.tagName === "SELECT") elegirOpcion(el, valor);
        else el.value = valor.trim();
      });
      proponerUmb(destino, tipoAntes);
    });
    hayCambios = true;
  }

  var hayCambios = false;
  window.addEventListener("beforeunload", function (e) { if (hayCambios) { e.preventDefault(); e.returnValue = ""; } });
  form.addEventListener("submit", function () { hayCambios = false; });
  cuerpo.addEventListener("paste", pegar);
  cuerpo.addEventListener("input", function () { hayCambios = true; });
  // El tipo que tenía cada lista antes del cambio (para saber si la UMB era la propuesta).
  var tipoPrevio = new WeakMap();
  cuerpo.addEventListener("focusin", function (e) {
    if ((e.target.name || "").slice(-14) === "-tipo_servicio") tipoPrevio.set(e.target, e.target.value);
  });
  cuerpo.addEventListener("change", function (e) {
    hayCambios = true;
    if ((e.target.name || "").slice(-14) === "-tipo_servicio") {
      proponerUmb(e.target.closest("tr.wd-fila"), tipoPrevio.get(e.target) || "");
      tipoPrevio.set(e.target, e.target.value);
    }
  });
  cuerpo.addEventListener("click", function (e) {
    if (e.target.matches("[data-quitar]")) { quitarFila(e.target.closest("tr.wd-fila")); hayCambios = true; }
  });
  var botonAgregar = document.getElementById("agregar");
  if (botonAgregar) botonAgregar.addEventListener("click", function () { agregarFila(); });
})();
