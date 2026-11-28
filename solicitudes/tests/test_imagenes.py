"""Fase 4: imágenes de las partidas (Revisión 3, sección 7.3)."""

from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from solicitudes import flujo, imagenes
from solicitudes.models import ImagenPartida, Partida

from .datos import crear_catalogos, crear_enviada, crear_usuario, imagen_png

E = Partida.Estado


def subida(nombre="foto.png", contenido=None, tipo="image/png"):
    """Lo que Django entrega en request.FILES, pero hecho a mano."""
    return SimpleUploadedFile(nombre, contenido if contenido is not None else imagen_png(), content_type=tipo)


class ConversionTests(TestCase):
    def test_png_grande_queda_webp_de_1920_sin_exif(self):
        grande = BytesIO()
        Image.new("RGB", (4000, 3000), (10, 120, 200)).save(grande, format="PNG")
        webp = imagenes.convertir_a_webp(subida(contenido=grande.getvalue()))
        img = Image.open(BytesIO(webp.read()))
        self.assertEqual(img.format, "WEBP")
        self.assertEqual(img.size, (1920, 1440))  # mismo aspecto 4:3
        self.assertNotIn("exif", img.info)

    def test_respeta_la_orientacion_del_celular(self):
        # Foto 400x200 marcada en el EXIF con orientación 6 (girada 90°): al enderezarla mide 200x400.
        foto = Image.new("RGB", (400, 200))
        exif = foto.getexif()
        exif[0x0112] = 6
        salida = BytesIO()
        foto.save(salida, format="JPEG", exif=exif)
        webp = imagenes.convertir_a_webp(subida("foto.jpg", salida.getvalue(), "image/jpeg"))
        self.assertEqual(Image.open(BytesIO(webp.read())).size, (200, 400))

    def test_rechaza_lo_que_no_es_imagen(self):
        with self.assertRaisesMessage(flujo.AccionNoPermitida, "no es una imagen válida"):
            imagenes.convertir_a_webp(subida("virus.jpg", b"MZ esto no es una foto"))

    def test_rechaza_formato_no_permitido(self):
        gif = BytesIO()
        Image.new("RGB", (10, 10)).save(gif, format="GIF")
        with self.assertRaisesMessage(flujo.AccionNoPermitida, "solo se aceptan JPG, PNG o WebP"):
            imagenes.convertir_a_webp(subida("a.gif", gif.getvalue(), "image/gif"))

    def test_rechaza_mas_de_10_mb(self):
        archivo = subida(contenido=b"0" * (imagenes.MAX_BYTES + 1))
        with self.assertRaisesMessage(flujo.AccionNoPermitida, "más de 10 MB"):
            imagenes.convertir_a_webp(archivo)


class PermisosYPantallaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = crear_catalogos()
        cls.sol = crear_usuario("sol", "SOL_MAT", centros=[cls.c["mttu"]])
        cls.val = crear_usuario("val", "VAL_MAT", centros=[cls.c["mttu"]])
        cls.dm = crear_usuario("dm", "DM", centros=[cls.c["mttu"]])
        cls.extrano = crear_usuario("otro", "SOL_MAT", centros=[cls.c["meix"]])

    def setUp(self):
        self.solicitud = crear_enviada(self.c, self.sol, n=1)  # EN_VALIDACION, con 1 imagen
        self.p = self.solicitud.partidas.get()

    def test_quien_puede_editar_segun_estado(self):
        self.assertTrue(imagenes.puede_editar(self.val, self.p))  # VAL_MAT en EN_VALIDACION
        self.assertFalse(imagenes.puede_editar(self.sol, self.p))  # el solicitante ya no
        self.p.estado = E.DEVUELTA_SOL
        self.assertTrue(imagenes.puede_editar(self.sol, self.p))
        self.assertFalse(imagenes.puede_editar(self.val, self.p))
        self.p.estado = E.EN_DM
        self.assertFalse(any(imagenes.puede_editar(u, self.p) for u in (self.sol, self.val, self.dm)))

    def test_subir_desde_la_ficha_y_maximo_3(self):
        self.client.force_login(self.val)
        url = reverse("solicitudes:subir_imagenes", args=[self.p.pk])
        self.client.post(url, {"imagenes": [subida("a.png"), subida("b.png")]})
        self.assertEqual(sorted(self.p.imagenes.values_list("orden", flat=True)), [1, 2, 3])
        self.assertTrue(self.p.imagenes.get(orden=3).archivo.name.endswith(".webp"))
        r = self.client.post(url, {"imagenes": [subida("c.png")]}, follow=True)
        self.assertContains(r, "Máximo 3 imágenes")
        self.assertEqual(self.p.imagenes.count(), 3)

    def test_si_una_falla_no_se_guarda_ninguna(self):
        with self.assertRaises(flujo.AccionNoPermitida):
            imagenes.agregar(self.val, self.p, [subida("buena.png"), subida("mala.png", b"basura")])
        self.assertEqual(self.p.imagenes.count(), 1)

    def test_quitar_borra_el_archivo_y_deja_historia(self):
        imagen = self.p.imagenes.get()
        storage, nombre = imagen.archivo.storage, imagen.archivo.name
        # captureOnCommitCallbacks ejecuta los on_commit que en una prueba normal nunca corren.
        with self.captureOnCommitCallbacks(execute=True):
            imagenes.quitar(self.val, imagen)
        self.assertFalse(storage.exists(nombre))
        self.assertTrue(self.p.eventos.filter(detalle__campo="imagenes").exists())

    def test_ver_imagen_solo_quien_ve_la_solicitud(self):
        imagen = self.p.imagenes.get()
        url = reverse("solicitudes:ver_imagen", args=[imagen.pk])
        self.client.force_login(self.dm)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/webp")
        self.client.force_login(self.extrano)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_sin_imagen_no_se_aprueba(self):
        for imagen in ImagenPartida.objects.all():
            imagen.delete()
        with self.assertRaisesMessage(flujo.AccionNoPermitida, "al menos 1 imagen"):
            flujo.aplicar(self.val, "aprobar", [self.p.pk])

    def test_dm_no_termina_sin_imagen(self):
        # Una partida que llegó a DM antes de la fase 4, sin imágenes.
        self.p.imagenes.all().delete()
        self.p.estado = E.EN_DM
        self.p.save()
        with self.assertRaises(flujo.ErroresCodigo) as e:
            flujo.terminar_con_codigos(self.dm, {self.p.pk: "555555"})
        self.assertIn("no tiene imágenes", e.exception.errores[self.p.pk])
        self.p.refresh_from_db()
        self.assertEqual(self.p.estado, E.EN_DM)

    def test_bandeja_no_aprueba_sin_imagen(self):
        """Aprobar desde la bandeja tampoco deja pasar una partida sin imágenes."""
        self.p.imagenes.all().delete()
        self.client.force_login(self.val)
        r = self.client.post(reverse("solicitudes:accion"), {"accion": "aprobar", "partidas": [self.p.pk]}, follow=True)
        self.assertContains(r, "al menos 1 imagen")
        self.p.refresh_from_db()
        self.assertEqual(self.p.estado, E.EN_VALIDACION)


class FlechasFichaTests(TestCase):
    def test_flechas_entre_partidas_de_la_misma_solicitud(self):
        c = crear_catalogos()
        sol = crear_usuario("sol", "SOL_MAT", centros=[c["mttu"]])
        solicitud = crear_enviada(c, sol, n=3)
        p10, p20, p30 = solicitud.partidas.order_by("numero")
        self.client.force_login(sol)
        r = self.client.get(reverse("solicitudes:partida", args=[p20.pk]))
        self.assertEqual((r.context["anterior"], r.context["siguiente"]), (p10, p30))
        self.assertContains(r, "Partida 2 de 3")
        r = self.client.get(reverse("solicitudes:partida", args=[p10.pk]))
        self.assertIsNone(r.context["anterior"])
