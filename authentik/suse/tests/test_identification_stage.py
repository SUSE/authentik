"""Test identification stage extensions"""

import importlib

from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse

import authentik.suse.settings as suse_settings
from authentik.core.models import User
from authentik.core.tests.utils import create_test_flow
from authentik.flows.models import FlowDesignation, FlowStageBinding
from authentik.flows.tests import FlowTestCase
from authentik.lib.avatars import get_avatar
from authentik.lib.config import CONFIG
from authentik.lib.generators import generate_id
from authentik.stages.identification.models import IdentificationStage, UserFields
from authentik.stages.password import BACKEND_INBUILT
from authentik.stages.password.models import PasswordStage


def create_community_user(community_uid: str = "communityUsername") -> User:
    """Create a test user with a communityUid attribute."""
    uid = generate_id(20)
    user = User.objects.create(
        name=uid,
        email=f"{uid}@example.com",
        username=f"{uid}@example.com",
        path="SUSE/People/Community",
        attributes={
            "communityUid": community_uid,
        },
    )
    user.set_password(uid)
    user.save()
    return user


class TestIdentificationExtraUserAttributesSettings(TestCase):
    """Test parsing of suse.identification.extra_user_attributes configuration"""

    def tearDown(self) -> None:
        importlib.reload(suse_settings)
        super().tearDown()

    def test_extra_user_attributes_unset(self):
        self.assertListEqual(
            suse_settings.SUSE_IDENTIFICATION_EXTRA_USER_ATTRIBUTES,
            [],
        )

    def test_extra_user_attributes_empty(self):
        with CONFIG.patch("suse.identification.extra_user_attributes", ""):
            importlib.reload(suse_settings)
            self.assertListEqual(
                suse_settings.SUSE_IDENTIFICATION_EXTRA_USER_ATTRIBUTES,
                [],
            )

    def test_extra_user_attributes_comma_separated(self):
        with CONFIG.patch("suse.identification.extra_user_attributes", "communityUid,altUid"):
            importlib.reload(suse_settings)
            self.assertListEqual(
                suse_settings.SUSE_IDENTIFICATION_EXTRA_USER_ATTRIBUTES,
                ["communityUid", "altUid"],
            )


class TestIdentificationStageCommunityUid(FlowTestCase):
    """Test login using custom identifiers (using communityUid as example)"""

    def setUp(self):
        super().setUp()
        self.community_uid = "communityUsername"
        self.user = create_community_user(self.community_uid)

        self.flow = create_test_flow(FlowDesignation.AUTHENTICATION)
        self.ident_stage = IdentificationStage.objects.create(
            name="identification",
            user_fields=[UserFields.USERNAME, UserFields.E_MAIL, UserFields.UPN],
            show_matched_user=False,
            pretend_user_exists=True,
        )
        self.password_stage = PasswordStage.objects.create(
            name="password",
            backends=[BACKEND_INBUILT],
        )
        FlowStageBinding.objects.create(target=self.flow, stage=self.ident_stage, order=0)
        FlowStageBinding.objects.create(target=self.flow, stage=self.password_stage, order=1)

    @override_settings(SUSE_IDENTIFICATION_EXTRA_USER_ATTRIBUTES=["communityUid"])
    def test_login_valid_communityuid_show_matched_user_false(self):
        """
        With show_matched_user=False, valid identifier echoes input and hides canonical user.
        """
        self.ident_stage.show_matched_user = False
        self.ident_stage.save()

        url = reverse("authentik_api:flow-executor", kwargs={"flow_slug": self.flow.slug})

        # different casing to verify case-insensitive match
        response = self.client.post(url, {"uid_field": "CommunityUsername"}, follow=True)
        challenge_data = self.assertStageResponse(
            response,
            self.flow,
            component="ak-stage-password",
            pending_user="CommunityUsername",
            pending_user_avatar=get_avatar(User(username="CommunityUsername")),
        )
        self.assertNotIn(self.user.username, response.content.decode())
        self.assertNotEqual(challenge_data["pending_user_avatar"], get_avatar(self.user))

        response = self.client.post(url, {"password": self.user.name})
        self.assertStageRedirects(response, reverse("authentik_core:root-redirect"))

    @override_settings(SUSE_IDENTIFICATION_EXTRA_USER_ATTRIBUTES=["communityUid"])
    def test_login_invalid_communityuid_show_matched_user_false(self):
        """
        With show_matched_user=False and pretend_user_exists=True, invalid identifier echoes input.
        """
        self.ident_stage.show_matched_user = False
        self.ident_stage.save()

        url = reverse("authentik_api:flow-executor", kwargs={"flow_slug": self.flow.slug})

        response = self.client.post(url, {"uid_field": "nonexistentCommunityUser"}, follow=True)
        self.assertStageResponse(
            response,
            self.flow,
            component="ak-stage-password",
            pending_user="nonexistentCommunityUser",
            pending_user_avatar=get_avatar(User(username="nonexistentCommunityUser")),
        )

    @override_settings(SUSE_IDENTIFICATION_EXTRA_USER_ATTRIBUTES=["communityUid"])
    def test_login_valid_communityuid_show_matched_user_true(self):
        """
        With show_matched_user=True, valid identifier resolves to canonical username and avatar.
        """
        self.ident_stage.show_matched_user = True
        self.ident_stage.save()

        url = reverse("authentik_api:flow-executor", kwargs={"flow_slug": self.flow.slug})

        response = self.client.post(url, {"uid_field": "CommunityUsername"}, follow=True)
        self.assertStageResponse(
            response,
            self.flow,
            component="ak-stage-password",
            pending_user=self.user.username,
            pending_user_avatar=get_avatar(self.user),
        )

        response = self.client.post(url, {"password": self.user.name})
        self.assertStageRedirects(response, reverse("authentik_core:root-redirect"))

    @override_settings(SUSE_IDENTIFICATION_EXTRA_USER_ATTRIBUTES=["communityUid"])
    def test_login_invalid_communityuid_show_matched_user_true(self):
        """
        With show_matched_user=True and pretend_user_exists=True, invalid identifier echoes input.
        """
        self.ident_stage.show_matched_user = True
        self.ident_stage.save()

        url = reverse("authentik_api:flow-executor", kwargs={"flow_slug": self.flow.slug})

        response = self.client.post(url, {"uid_field": "nonexistentCommunityUser"}, follow=True)
        self.assertStageResponse(
            response,
            self.flow,
            component="ak-stage-password",
            pending_user="nonexistentCommunityUser",
            pending_user_avatar=get_avatar(User(username="nonexistentCommunityUser")),
        )

    @override_settings(SUSE_IDENTIFICATION_EXTRA_USER_ATTRIBUTES=["communityUid"])
    def test_login_communityuid_case_sensitive(self):
        """With case_insensitive_matching=False, casing must match exactly."""
        self.ident_stage.case_insensitive_matching = False
        self.ident_stage.pretend_user_exists = False
        self.ident_stage.save()

        url = reverse("authentik_api:flow-executor", kwargs={"flow_slug": self.flow.slug})

        # Wrong casing
        response = self.client.post(url, {"uid_field": "communityusername"})
        self.assertStageResponse(
            response,
            self.flow,
            component="ak-stage-identification",
            response_errors={
                "non_field_errors": [{"code": "invalid", "string": "Failed to authenticate."}]
            },
        )

        # Exact casing
        response = self.client.post(url, {"uid_field": self.community_uid}, follow=True)
        self.assertStageResponse(
            response,
            self.flow,
            component="ak-stage-password",
            pending_user=self.community_uid,
            pending_user_avatar=get_avatar(User(username=self.community_uid)),
        )

    @override_settings(SUSE_IDENTIFICATION_EXTRA_USER_ATTRIBUTES=["communityUid"])
    def test_community_uid_not_used_when_username_field_disabled(self):
        """
        Flows with only email enabled (e.g. recovery) do not match the custom identifier.
        """
        self.ident_stage.user_fields = [UserFields.E_MAIL]
        self.ident_stage.pretend_user_exists = False
        self.ident_stage.save()

        url = reverse("authentik_api:flow-executor", kwargs={"flow_slug": self.flow.slug})
        response = self.client.post(url, {"uid_field": self.community_uid})
        self.assertStageResponse(
            response,
            self.flow,
            component="ak-stage-identification",
            response_errors={
                "non_field_errors": [{"code": "invalid", "string": "Failed to authenticate."}]
            },
        )

    @override_settings(SUSE_IDENTIFICATION_EXTRA_USER_ATTRIBUTES=[])
    def test_community_uid_not_used_when_setting_empty(self):
        """
        With SUSE_IDENTIFICATION_EXTRA_USER_ATTRIBUTES not set / empty,
        custom identifiers are ignored.
        """
        self.ident_stage.pretend_user_exists = False
        self.ident_stage.save()

        url = reverse("authentik_api:flow-executor", kwargs={"flow_slug": self.flow.slug})
        response = self.client.post(url, {"uid_field": self.community_uid})
        self.assertStageResponse(
            response,
            self.flow,
            component="ak-stage-identification",
            response_errors={
                "non_field_errors": [{"code": "invalid", "string": "Failed to authenticate."}]
            },
        )
