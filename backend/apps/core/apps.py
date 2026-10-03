from django.apps import AppConfig
from django.conf import settings


class CoreConfig(AppConfig):
    name = "apps.core"

    def ready(self):
        # Guard every Pillow decode in the process against decompression bombs.
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = settings.MAX_IMAGE_PIXELS
