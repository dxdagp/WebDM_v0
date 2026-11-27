"""Pruebas de la fase 0: confirman que el login protege el portal."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class InicioTests(TestCase):
    def setUp(self):
        # Cada prueba corre en una base de datos temporal y vacía.
        self.usuario = get_user_model().objects.create_user(
            username="ana", password="clave-segura-123", first_name="Ana"
        )

    def test_sin_sesion_redirige_al_login(self):
        respuesta = self.client.get(reverse("inicio"))
        self.assertRedirects(respuesta, f"{reverse('login')}?next=/")

    def test_con_sesion_muestra_el_saludo(self):
        self.client.login(username="ana", password="clave-segura-123")
        respuesta = self.client.get(reverse("inicio"))
        self.assertContains(respuesta, "Hola, Ana")

    def test_usa_el_modelo_de_usuario_propio(self):
        self.assertEqual(get_user_model()._meta.label, "usuarios.Usuario")
