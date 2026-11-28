/*
 * Ficha de una partida (pedido de Dave, 28-nov-2026):
 *   1. Visor de imágenes: clic en la miniatura la muestra grande en el centro de la
 *      pantalla (ajustada a la ventana, no a su tamaño real). Se cierra con el tache,
 *      con un clic fuera de la imagen o con Esc. Un clic SOBRE la imagen la abre completa
 *      en otra pestaña.
 *   2. Lupa: al pasar el cursor sobre la imagen ampliada, un círculo muestra esa zona
 *      2.5 veces más grande.
 *   3. Flechas entre partidas: si cambiaste datos y no los guardaste, pregunta antes de salir.
 */
(function () {
  "use strict";

  // ---- 1. Visor -----------------------------------------------------------------
  var visor = document.getElementById("visor");
  if (visor) {
    var img = visor.querySelector("img");
    var lupa = visor.querySelector(".wd-lupa");
    var ZOOM = 2.5;

    function abrir(url, texto) {
      img.src = url;
      img.alt = texto;
      visor.hidden = false;
      document.body.style.overflow = "hidden"; // que la página de atrás no se desplace
    }
    function cerrar() {
      visor.hidden = true;
      lupa.style.display = "none";
      img.removeAttribute("src");
      document.body.style.overflow = "";
    }

    document.querySelectorAll("a[data-visor]").forEach(function (a) {
      a.addEventListener("click", function (e) {
        e.preventDefault(); // en vez de abrir otra pestaña, abre el visor
        abrir(a.href, a.querySelector("img").alt);
      });
    });

    visor.querySelector(".wd-visor-cerrar").addEventListener("click", cerrar);
    // Clic en el fondo oscuro (fuera de la imagen) = cerrar.
    visor.addEventListener("click", function (e) { if (e.target === visor) cerrar(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !visor.hidden) cerrar(); });
    // Clic en la imagen = tamaño completo en otra pestaña.
    img.addEventListener("click", function () { window.open(img.src, "_blank", "noopener"); });

    // ---- 2. Lupa ------------------------------------------------------------------
    // La lupa es un círculo cuyo FONDO es la misma imagen, pero 2.5 veces más grande.
    // Al mover el cursor recorremos ese fondo para que el centro del círculo muestre
    // justo lo que está bajo el cursor.
    img.addEventListener("mousemove", function (e) {
      var caja = img.getBoundingClientRect();
      var x = e.clientX - caja.left, y = e.clientY - caja.top; // posición dentro de la imagen
      var r = lupa.offsetWidth / 2 || 90;
      lupa.style.display = "block";
      lupa.style.left = (img.offsetLeft + x - r) + "px";
      lupa.style.top = (img.offsetTop + y - r) + "px";
      lupa.style.backgroundImage = 'url("' + img.src + '")';
      lupa.style.backgroundSize = (caja.width * ZOOM) + "px " + (caja.height * ZOOM) + "px";
      lupa.style.backgroundPosition = (r - x * ZOOM) + "px " + (r - y * ZOOM) + "px";
    });
    img.addEventListener("mouseleave", function () { lupa.style.display = "none"; });
  }

  // ---- 3. Flechas con cambios sin guardar ---------------------------------------------
  var datos = document.querySelector("form[method=post] .wd-campos");
  var cambiado = false;
  if (datos) datos.addEventListener("input", function () { cambiado = true; });
  document.querySelectorAll("a[data-navegar]").forEach(function (a) {
    a.addEventListener("click", function (e) {
      if (cambiado && !confirm("Tienes cambios sin guardar en esta partida. ¿Salir sin guardarlos?")) e.preventDefault();
    });
  });
})();
