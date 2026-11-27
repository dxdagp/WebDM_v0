"""Pruebas de la bitácora de sesiones y del cambio obligatorio de contraseña (fase 3)."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from usuarios.models import BitacoraSesion

T = BitacoraSesion.TipoCierre


class BitacoraTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.usuario = get_user_model().objects.create_user("ana", password="clave-segura-123")

    def entrar(self):
        return self.client.post(reverse("login"), {"username": "ana", "password": "clave-segura-123"},
                                HTTP_USER_AGENT="Navegador de prueba", REMOTE_ADDR="10.0.0.7")

    def test_entrar_y_salir(self):
        self.entrar()
        registro = BitacoraSesion.objects.get()
        self.assertEqual(registro.ip, "10.0.0.7")
        self.assertEqual(registro.user_agent, "Navegador de prueba")
        self.assertIsNone(registro.fin)
        self.client.post(reverse("logout"))
        registro.refresh_from_db()
        self.assertEqual(registro.tipo_cierre, T.LOGOUT_MANUAL)
        self.assertIsNotNone(registro.fin)

    def test_sesion_vencida_se_cierra_como_timeout_al_volver(self):
        self.entrar()
        anterior = BitacoraSesion.objects.get()
        # Simulamos que pasaron más de 30 minutos: la sesión de Django venció.
        Session.objects.update(expire_date=timezone.now() - timedelta(minutes=1))
        # No hay logout: el usuario solo dejó de usar WebDM y su navegador olvidó la cookie.
        self.client.cookies.clear()
        self.entrar()
        anterior.refresh_from_db()
        self.assertEqual(anterior.tipo_cierre, T.TIMEOUT)
        self.assertEqual(anterior.fin, anterior.ultima_actividad)
        self.assertEqual(BitacoraSesion.objects.filter(fin__isnull=True).count(), 1)


class CambioObligatorioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser("admin", password="clave-admin-123")
        cls.usuario = User.objects.create_user("beto", password="clave-segura-123")

    def test_admin_restablece_y_el_usuario_debe_cambiarla(self):
        self.client.force_login(self.admin)
        url = reverse("admin:auth_user_password_change", args=[self.usuario.pk])
        r = self.client.post(url, {"password1": "temporal-2026", "password2": "temporal-2026"})
        self.assertEqual(r.status_code, 302)
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.debe_cambiar_password)

        self.client.force_login(self.usuario)
        r = self.client.get(reverse("inicio"))
        self.assertRedirects(r, reverse("cambiar_password"))
        r = self.client.post(reverse("cambiar_password"), {
            "old_password": "temporal-2026", "new_password1": "nueva-clave-2026", "new_password2": "nueva-clave-2026",
        })
        self.assertRedirects(r, reverse("inicio"))
        self.usuario.refresh_from_db()
        self.assertFalse(self.usuario.debe_cambiar_password)
        self.assertEqual(self.client.get(reverse("inicio")).status_code, 200)

    def test_restablecer_invalida_sesiones_abiertas(self):
        BitacoraSesion.objects.create(usuario=self.usuario)
        self.client.force_login(self.admin)
        self.client.post(reverse("admin:auth_user_password_change", args=[self.usuario.pk]),
                         {"password1": "temporal-2026", "password2": "temporal-2026"})
        self.assertEqual(BitacoraSesion.objects.get(usuario=self.usuario).tipo_cierre, T.SESION_INVALIDADA)
