"""Ejecutor de pruebas de WebDM.

Igual que el de Django, pero las imágenes que suben las pruebas van a una carpeta
temporal que se borra al terminar: así `manage.py test` nunca ensucia tu MEDIA_ROOT real.
"""

import shutil
import tempfile

from django.conf import settings
from django.test.runner import DiscoverRunner


class Runner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._media = tempfile.mkdtemp(prefix="webdm-test-media-")
        settings.MEDIA_ROOT = self._media

    def teardown_test_environment(self, **kwargs):
        shutil.rmtree(self._media, ignore_errors=True)
        super().teardown_test_environment(**kwargs)
