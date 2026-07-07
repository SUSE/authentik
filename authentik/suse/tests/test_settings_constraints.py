"""Test CONSTRAINTS Settings Logic"""

import importlib
from unittest.mock import patch

from django.test import TestCase

import authentik.suse.settings as suse_settings
from authentik.lib.config import CONFIG


class TestSettingsConstraints(TestCase):
    """Test the module-level construction of the CONSTRAINTS dictionary."""

    def test_constraints_parsing_valid_config(self):
        """Test that a valid JSON config is correctly parsed into the CONSTRAINTS dictionary."""
        mock_config = {
            "test-role-allow-corp-create": {"allow": ["corp.example.com"]},
            "another-role": {"allow": ["suse.com", "rancher.com"]},
        }

        with patch.object(CONFIG, "get_dict_from_b64_json", return_value=mock_config):
            importlib.reload(suse_settings)

            constraints = suse_settings.CONSTRAINTS

            self.assertIn("email", constraints)

            self.assertListEqual(
                constraints["email"]["restricted_domains"],
                ["corp.example.com", "suse.com", "rancher.com"],
            )

            self.assertDictEqual(constraints["email"]["roles_domains"], mock_config)

    def test_constraints_parsing_empty_config(self):
        """Test that missing or empty configuration defaults gracefully."""
        # Simulate the key missing from the environment
        with patch.object(CONFIG, "get_dict_from_b64_json", return_value={}):
            importlib.reload(suse_settings)

            constraints = suse_settings.CONSTRAINTS

            self.assertIn("email", constraints)
            self.assertListEqual(constraints["email"]["restricted_domains"], [])
            self.assertDictEqual(constraints["email"]["roles_domains"], {})
