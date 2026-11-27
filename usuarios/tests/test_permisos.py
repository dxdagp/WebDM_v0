"""El rol ADMIN da acceso al panel con permisos fijos (usuarios/permisos.py)."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse


class RolAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin_rol = User.objects.create_user("lucia", password="clave-segura-123")
        cls.root = User.objects.create_superuser("root", password="clave-root-123")
        cls.otro = User.objects.create_user("pepe", password="clave-segura-123")

    def test_rol_admin_da_y_quita_acceso_al_panel(self):
        grupo = Group.objects.get(name="ADMIN")
        self.admin_rol.groups.add(grupo)
        self.admin_rol.refresh_from_db()
        self.assertTrue(self.admin_rol.is_staff)
        self.admin_rol.groups.remove(grupo)
        self.admin_rol.refresh_from_db()
        self.assertFalse(self.admin_rol.is_staff)
        # También funciona desde el lado del grupo.
        grupo.user_set.add(self.otro)
        self.otro.refresh_from_db()
        self.assertTrue(self.otro.is_staff)

    def test_permisos_del_rol(self):
        self.admin_rol.groups.add(Group.objects.get(name="ADMIN"))
        u = get_user_model().objects.get(pk=self.admin_rol.pk)  # sin la caché de permisos
        self.assertTrue(u.has_perm("usuarios.change_usuario"))
        self.assertTrue(u.has_perm("catalogos.add_centro"))
        self.assertFalse(u.has_perm("catalogos.delete_centro"))  # se desactiva, no se borra
        self.assertFalse(u.has_perm("usuarios.delete_usuario"))
        self.assertTrue(u.has_perm("solicitudes.view_solicitud"))
        self.assertFalse(u.has_perm("solicitudes.change_partida"))

    def test_admin_edita_usuarios_pero_no_superusuarios(self):
        self.admin_rol.groups.add(Group.objects.get(name="ADMIN"))
        self.client.force_login(self.admin_rol)
        r = self.client.get(reverse("admin:usuarios_usuario_change", args=[self.otro.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'name="is_superuser"')
        self.assertNotContains(r, 'name="user_permissions"')
        self.assertNotContains(r, 'name="is_staff"')
        lista = self.client.get(reverse("admin:usuarios_usuario_changelist"))
        self.assertNotContains(lista, "root")

    def test_superusuario_si_ve_la_casilla(self):
        self.client.force_login(self.root)
        r = self.client.get(reverse("admin:usuarios_usuario_change", args=[self.otro.pk]))
        self.assertContains(r, 'name="is_superuser"')
