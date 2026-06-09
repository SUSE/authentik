"""template function tests"""

from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings

from authentik.stages.email.templatetags.authentik_stages_email import inline_static_binary


@override_settings(STATICFILES_DIRS=[settings.BASE_DIR / Path("web")])
class TestTemplateTags(TestCase):
    """Template tag tests"""

    def test_inline_static_binary_does_not_exist(self):
        """Test inlining binary file"""
        filename = "this_file_should_not_exist.png"
        result = inline_static_binary(filename)
        self.assertEqual(result, filename)

    def test_inline_png(self):
        """Test inlining png"""
        result = inline_static_binary("src/assets/images/user_default.png")
        self.assertEqual(
            result,
            "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGP6zwAAAgcBApocMXEAAAAASUVORK5CYII=",
        )

    def test_inline_textfile(self):
        """Test inlining binary textfile"""
        result = inline_static_binary("robots.txt")
        self.assertEqual(result, "data:text/plain;base64,VXNlci1hZ2VudDogKgpEaXNhbGxvdzogLwo=")
