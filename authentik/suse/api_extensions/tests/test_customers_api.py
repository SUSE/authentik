"""Test Customers API"""

import json
from unittest.mock import PropertyMock, patch

import email_validator
from django.core import mail
from django.core.mail.backends.locmem import EmailBackend
from django.test.utils import override_settings
from django.urls.base import reverse
from rest_framework.test import APITestCase

from authentik.core.models import (
    User,
)
from authentik.core.tests.utils import (
    create_test_admin_user,
    create_test_flow,
)
from authentik.lib.generators import generate_id

email_validator.TEST_ENVIRONMENT = True


def create_test_customer(name: str | None = None) -> User:
    """Generate a test customer"""
    uid = generate_id(20) if not name else name

    user: User = User.objects.create(
        name=uid,
        email=f"{uid}@goauthentik.io",
        username=f"{uid}@goauthentik.io",
        path="SUSE/People/Customers",
        attributes={
            "cn": "Customer One",
            "givenName": "Customer",
            "organization": "Buyer",
            "sn": "One",
            "telephoneNumber": "02364 28 83 1211",
            "title": "Procurement",
        },
    )
    user.set_password(uid)
    user.save()
    return user


def create_test_community(name: str | None = None) -> User:
    """Generate a community user"""
    uid = generate_id(20) if not name else name

    user: User = User.objects.create(
        name=uid,
        email=f"{uid}@goauthentik.io",
        username=f"{uid}@goauthentik.io",
        path="SUSE/People/Community",
        attributes={
            "cn": "Community User",
            "givenName": "Community",
            "organization": "openSUSE",
            "sn": "User",
            "telephoneNumber": "02364 28 83 123",
            "title": "Developer",
            "communityUid": "communityUsername",
        },
    )
    user.set_password(uid)
    user.save()
    return user


def create_service_account(name: str | None = None) -> User:
    """Generate the service account calling this api"""
    uid = generate_id(20) if not name else name

    user: User = User.objects.create(
        name=uid,
        email=f"{uid}@goauthentik.io",
        username=f"{uid}@goauthentik.io",
        path="SUSE/ServiceAccounts",
    )
    user.set_password(uid)
    user.assign_perms_to_managed_role(
        [
            "authentik_suse_api.view_susecustomer",
            "authentik_suse_api.add_susecustomer",
            "authentik_suse_api.change_susecustomer",
        ]
    )
    user.save()

    return user


@override_settings(
    SUSE_CUSTOMER_ALLOWED_PATHS="SUSE/People/Partners|SUSE/People/Customers|SUSE/People/Community".split(
        "|"
    ),
    SUSE_CUSTOMER_CREATE_PATH="SUSE/People/Customers",
)
@patch(
    "authentik.stages.email.models.EmailStage.backend_class",
    PropertyMock(return_value=EmailBackend),
)
class TestUsersAPI(APITestCase):
    """Test Customers API"""

    def setUp(self) -> None:
        self.admin = create_test_admin_user()
        self.user = create_test_customer()
        self.service_account = create_service_account()
        self.community = create_test_community()

        self.flow = create_test_flow()

    def test_list(self):
        """Test listing when logged in"""
        self.client.force_login(self.service_account)
        response = self.client.get(reverse("authentik_api:suse_customers-list"))
        self.assertEqual(response.status_code, 200)

    def test_list_anon(self):
        """Test listing without a login"""
        response = self.client.get(reverse("authentik_api:suse_customers-list"))
        self.assertEqual(response.status_code, 403)

        self.client.force_login(self.user)
        response = self.client.get(reverse("authentik_api:suse_customers-list"))
        self.assertEqual(response.status_code, 403)

    def test_create_full_and_read(self):
        """Create a user with all attributes filled and read it back"""
        self.client.force_login(self.service_account)

        user_data = {
            "firstName": "Katja",
            "lastName": "Biermann",
            "phone": "0345 80 53 45",
            "title": "Drilling and boring machine tool setter",
            "company": "AdventureSports!",
            "partnerId": "NEW-PARTNER-1",
            "address": {
                "state": "Sachsen-Anhalt",
                "street": "Messedamm 74",
                "country": "DE",
                "locality": "Halle",
                "postalCode": "06122",
            },
        }

        with self.settings(SUSE_WELCOME_FLOW=self.flow.slug):
            response = self.client.post(
                reverse("authentik_api:suse_customers-list"),
                data={"email": "KatjaBiermann@example.com", **user_data},
            )
        self.assertEqual(response.status_code, 201)

        pk = json.loads(response.content)["pk"]

        self.assertJSONEqual(
            response.content, {"email": "katjabiermann@example.com", "pk": pk, **user_data}
        )

        response = self.client.get(
            reverse("authentik_api:suse_customers-detail", kwargs={"pk": pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content, {"email": "katjabiermann@example.com", "pk": pk, **user_data}
        )

    def test_create_duplicate_with_different_casing(self):
        """Create a user with required attributes only and confirm by reading back"""
        self.client.force_login(self.service_account)

        user: User = User.objects.create(
            name="Brian Glaspie",
            email="BrianNGlaspie@dayrep.com",
            username="BrianNGlaspie@dayrep.com",
            path="SUSE/People/Customers",
            attributes={
                "cn": "Brian Glaspie",
                "givenName": "Brian",
                "organization": "Buyer",
                "sn": "Glaspie",
                "telephoneNumber": "863-665-5408",
                "title": "Ultrasonographer",
            },
        )
        user.save()

        user_data = {
            "email": "briannglaspie@dayrep.com",
            "firstName": "Brian",
            "lastName": "Glaspie",
            "phone": "863-665-5408",
            "title": "Ultrasonographer",
            "address": {
                "state": "Michigan",
                "street": "2009 Wood Duck Drive",
                "country": "US",
                "locality": "Lakeland",
            },
        }

        response = self.client.post(reverse("authentik_api:suse_customers-list"), data=user_data)
        self.assertEqual(response.status_code, 400)

    def test_update_when_duplicate_exists(self):
        """Update user should still work even if duplicates exist"""
        self.client.force_login(self.service_account)

        user1: User = User.objects.create(
            name="Brian Glaspie",
            email="BrianNGlaspie@dayrep.com",
            username="BrianNGlaspie@dayrep.com",
            path="SUSE/People/Customers",
            attributes={
                "cn": "Brian Glaspie",
                "givenName": "Brian",
                "organization": "Buyer",
                "sn": "Glaspie",
                "telephoneNumber": "863-665-5408",
                "title": "Ultrasonographer",
            },
        )
        user1.save()

        user2: User = User.objects.create(
            name="Brian Glaspie",
            email="briannglaspie@dayrep.com",
            username="briannglaspie@dayrep.co",
            path="SUSE/People/Customers",
            attributes={
                "cn": "Brian Glaspie",
                "givenName": "Brian",
                "organization": "Buyer",
                "sn": "Glaspie",
                "telephoneNumber": "863-665-5408",
                "title": "Ultrasonographer",
            },
        )
        user2.save()

        user_data = {
            "firstName": "Brian",
            "lastName": "Glaspie",
            "phone": "863-665-5408",
            "title": "Ultrasonographer",
            "company": "AdventureSports!",
            "partnerId": "PID-4242",
            "address": {
                "state": "Michigan",
                "street": "2009 Wood Duck Drive",
                "country": "US",
                "locality": "Lakeland",
                "postalCode": "06122",
            },
        }

        response = self.client.put(
            reverse("authentik_api:suse_customers-detail", kwargs={"pk": user2.pk}),
            data=user_data,
        )
        self.assertEqual(response.status_code, 200)

        self.assertJSONEqual(
            response.content,
            {
                "pk": user2.pk,
                "email": user2.email.lower(),
                "partnerId": "PID-4242",
                **user_data,
            },
        )

        # Check that we only updated user2
        self.assertEqual(User.objects.get(pk=user1.pk).attributes["organization"], "Buyer")
        self.assertEqual(
            User.objects.get(pk=user2.pk).attributes["organization"], "AdventureSports!"
        )

    def test_create_required_and_read(self):
        """Create a user with required attributes only and confirm by reading back"""
        self.client.force_login(self.service_account)

        user_data = {
            "email": "melissaamos@armyspy.com",
            "firstName": "Melissa",
            "lastName": "Amos",
            "phone": "906-343-0104",
            "title": "Tax assessor",
            "address": {
                "state": "Michigan",
                "street": "2009 Wood Duck Drive",
                "country": "US",
                "locality": "Sand River",
            },
        }

        with self.settings(SUSE_WELCOME_FLOW=self.flow.slug):
            response = self.client.post(
                reverse("authentik_api:suse_customers-list"), data=user_data
            )
        self.assertEqual(response.status_code, 201)

        pk = json.loads(response.content)["pk"]

        expected = {
            "pk": pk,
            "email": "melissaamos@armyspy.com",
            "firstName": "Melissa",
            "lastName": "Amos",
            "phone": "906-343-0104",
            "title": "Tax assessor",
            "partnerId": None,
            "company": None,
            "address": {
                "state": "Michigan",
                "street": "2009 Wood Duck Drive",
                "country": "US",
                "locality": "Sand River",
                "postalCode": None,
            },
        }

        self.assertJSONEqual(response.content, expected, "Create did not return the expected value")

        response = self.client.get(
            reverse("authentik_api:suse_customers-detail", kwargs={"pk": pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, expected, "Read did not return expected value")

        user = User.objects.get(pk=pk)
        self.assertEqual(user.username, "melissaamos@armyspy.com")
        self.assertFalse(user.is_active)

        self.assertEqual(len(mail.outbox), 1)
        sent_mail = mail.outbox[0]
        self.assertEqual(sent_mail.subject, "Welcome to SUSEID")
        self.assertEqual(sent_mail.to, ["Melissa Amos <melissaamos@armyspy.com>"])

    def test_update_customer(self):
        """Test full update of a customer"""
        self.client.force_login(self.service_account)

        user_data = {
            "firstName": "First",
            "lastName": "Last",
            "phone": "561621 545",
            "title": "Law clerk",
            "company": "Mission Realty",
            "partnerId": "PID-1234",
            "address": {
                "state": "Bavaria",
                "street": "Frankenstraße",
                "country": "DE",
                "locality": "Nürnberg",
                "postalCode": "90402",
            },
        }

        response = self.client.put(
            reverse("authentik_api:suse_customers-detail", kwargs={"pk": self.user.pk}),
            data=user_data,
        )
        self.assertEqual(response.status_code, 200)

        self.assertJSONEqual(
            response.content,
            {
                "pk": self.user.pk,
                "email": self.user.email.lower(),
                "partnerId": "PID-1234",
                **user_data,
            },
        )

        self.assertEqual(len(mail.outbox), 0)

    def test_patch_partner_id(self):
        """Test patch partnerId"""
        self.client.force_login(self.service_account)

        user_data = {
            "partnerId": "PID-1337",
        }

        response = self.client.patch(
            reverse("authentik_api:suse_customers-detail", kwargs={"pk": self.user.pk}),
            data=user_data,
        )
        self.assertEqual(response.status_code, 200)

        self.assertJSONEqual(
            response.content,
            {
                "pk": self.user.pk,
                "email": self.user.email.lower(),
                "partnerId": "PID-1337",
                "firstName": "Customer",
                "lastName": "One",
                "phone": "02364 28 83 1211",
                "company": "Buyer",
                "title": "Procurement",
                "address": {
                    "country": None,
                    "locality": None,
                    "postalCode": None,
                    "state": None,
                    "street": None,
                },
            },
        )

    def test_invalid_country(self):
        """Test that invalid country raises an error"""
        self.client.force_login(self.service_account)

        user_data = {
            "address": {
                "country": "ZZ",
            },
        }

        response = self.client.patch(
            reverse("authentik_api:suse_customers-detail", kwargs={"pk": self.user.pk}),
            data=user_data,
        )
        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(
            response.content,
            {"address": {"country": ['"ZZ" is not a valid choice.']}},
        )

    def test_partial_address(self):
        """Test partial address update"""
        self.client.force_login(self.service_account)

        user_data = {
            "address": {
                "state": "Baden-Württemberg",
                "street": "Kurfürstenstraße 53",
                "country": "DE",
                "locality": "Remshalden",
                "postalCode": "73630",
            },
        }

        response = self.client.patch(
            reverse("authentik_api:suse_customers-detail", kwargs={"pk": self.community.pk}),
            data=user_data,
        )
        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            User.objects.get(pk=self.community.pk).attributes,
            {
                "communityUid": "communityUsername",
                "cn": "Community User",
                "givenName": "Community",
                "organization": "openSUSE",
                "sn": "User",
                "telephoneNumber": "02364 28 83 123",
                "title": "Developer",
                "address": {
                    "state": "Baden-Württemberg",
                    "street": "Kurfürstenstraße 53",
                    "country": "DE",
                    "locality": "Remshalden",
                    "postalCode": "73630",
                },
                "partnerId": None,
            },
        )

    def test_update_community(self):
        """Test full update for community user keeps the communityUid"""
        self.client.force_login(self.service_account)

        user_data = {
            "firstName": "Leon",
            "lastName": "Gerber",
            "phone": "02364 28 83 88",
            "title": "Circulation assistant",
            "company": "The Flying Hippo",
            "address": {
                "state": "Niedersachsen",
                "street": "Knesebeckstraße 75",
                "country": "DE",
                "locality": "Marl",
                "postalCode": "49448",
            },
        }

        response = self.client.put(
            reverse("authentik_api:suse_customers-detail", kwargs={"pk": self.community.pk}),
            data=user_data,
        )
        self.assertEqual(response.status_code, 200)

        self.assertJSONEqual(
            response.content,
            {
                "pk": self.community.pk,
                "email": self.community.email.lower(),
                "partnerId": None,
                **user_data,
            },
        )

        # Ensure that the communityUid was not overwritten
        self.assertEqual(
            User.objects.get(pk=self.community.pk).attributes,
            {
                "cn": "Leon Gerber",
                "communityUid": "communityUsername",
                "givenName": "Leon",
                "organization": "The Flying Hippo",
                "sn": "Gerber",
                "telephoneNumber": "02364 28 83 88",
                "title": "Circulation assistant",
                "partnerId": None,
                "address": {
                    "state": "Niedersachsen",
                    "street": "Knesebeckstraße 75",
                    "country": "DE",
                    "locality": "Marl",
                    "postalCode": "49448",
                },
            },
        )

    def test_update_clears_optional(self):
        """Test update actually removes optional fields"""
        self.client.force_login(self.service_account)

        user_data = {
            "email": "GabrieleProbst@teleworm.us",
            "firstName": "Gabriele",
            "lastName": "Probst",
            "phone": "02202 42 60 15",
            "title": "Power distributor",
            "company": "Zephyr Investments",
            "address": {
                "state": "Nordrhein-Westfalen",
                "street": "Lietzenburger Strasse 32",
                "country": "DE",
                "locality": "Bergisch Gladbach Herkenrath",
                "postalCode": "51429",
            },
        }

        with self.settings(SUSE_WELCOME_FLOW=self.flow.slug):
            response = self.client.post(
                reverse("authentik_api:suse_customers-list"), data=user_data
            )

        self.assertEqual(response.status_code, 201)

        pk = json.loads(response.content)["pk"]

        user_data = {
            "email": "GabrieleProbst@teleworm.us",
            "firstName": "Gabriele",
            "lastName": "Probst",
            "phone": "02202 42 60 15",
            "title": "Power distributor",
            "address": {
                "state": "Nordrhein-Westfalen",
                "street": "Lietzenburger Strasse 32",
                "country": "DE",
                "locality": "Bergisch Gladbach Herkenrath",
            },
        }

        response = self.client.put(
            reverse("authentik_api:suse_customers-detail", kwargs={"pk": pk}), data=user_data
        )
        self.assertEqual(response.status_code, 200)

        self.assertJSONEqual(
            response.content,
            {
                "pk": pk,
                "email": "gabrieleprobst@teleworm.us",
                "firstName": "Gabriele",
                "lastName": "Probst",
                "phone": "02202 42 60 15",
                "title": "Power distributor",
                "company": None,
                "partnerId": None,
                "address": {
                    "state": "Nordrhein-Westfalen",
                    "street": "Lietzenburger Strasse 32",
                    "country": "DE",
                    "locality": "Bergisch Gladbach Herkenrath",
                    "postalCode": None,
                },
            },
        )

    def test_update_forbidden(self):
        """Test that it is not possible to update users that are in the wrong path"""
        self.client.force_login(self.service_account)

        user_data = {
            "firstName": "Paul",
            "lastName": "Bohm",
            "phone": "465 702 788",
            "title": "Business management consultant",
            "company": "Glicks Furniture",
            "address": {
                "state": "Pardubický kraj",
                "street": "Čechova 537",
                "country": "CZ",
                "locality": "Hlinsko v Cechách 1",
                "postalCode": "539 01",
            },
        }

        response = self.client.put(
            reverse("authentik_api:suse_customers-detail", kwargs={"pk": self.admin.pk}),
            data=user_data,
        )
        self.assertEqual(response.status_code, 403)

        self.assertJSONEqual(
            response.content, {"detail": "You are not allowed to update users in this path."}
        )
