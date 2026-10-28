import uuid

from django.conf import settings
from django.db.utils import IntegrityError
from django_countries.serializer_fields import CountryField
from email_validator import (
    EmailNotValidError,
    caching_resolver,
    validate_email,
)
from rest_framework import mixins, permissions, serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.fields import CharField, EmailField, IntegerField
from rest_framework.status import HTTP_409_CONFLICT
from rest_framework.validators import UniqueValidator
from rest_framework.viewsets import ReadOnlyModelViewSet

from authentik.core.models import User
from authentik.rbac.decorators import permission_required
from authentik.suse.api_extensions.utils import DjangoResolverCache


class ConflictError(ValidationError):
    status_code = HTTP_409_CONFLICT


class AddressSerializer(serializers.Serializer):
    state = CharField(
        max_length=150,
        required=True,
    )

    street = CharField(
        max_length=150,
        required=True,
    )

    country = CountryField(
        required=True,
    )

    locality = CharField(
        max_length=150,
        required=True,
    )

    postalCode = CharField(
        max_length=10,
        required=False,
    )

    def to_representation(self, instance):
        return {k: instance.get(k) for k in self.fields.keys()}

    def update(self, instance: dict | None, validated_data: dict | None):
        if instance is None or not self.partial:
            instance = dict()

        if validated_data is None:
            return instance

        return {k: validated_data.get(k, instance.get(k)) for k in self.fields.keys()}


class CustomerSerializer(serializers.Serializer):
    email = EmailField(
        read_only=True,
    )

    pk = IntegerField(
        read_only=True,
    )

    firstName = CharField(
        min_length=1,
        max_length=150,
        required=True,
    )

    lastName = CharField(
        min_length=1,
        max_length=150,
        required=True,
    )

    phone = CharField(
        max_length=30,
        min_length=1,
        required=True,
    )

    title = CharField(
        max_length=150,
        required=True,
    )

    company = CharField(
        max_length=150,
        required=False,
    )

    partnerId = CharField(
        max_length=150,
        required=False,
    )

    address = AddressSerializer()

    def to_representation(self, instance):
        ret = {
            "pk": instance.pk,
            "email": instance.email.lower(),
            "firstName": instance.attributes.get("givenName"),
            "lastName": instance.attributes.get("sn"),
            "phone": instance.attributes.get("telephoneNumber"),
            "title": instance.attributes.get("title"),
            "company": instance.attributes.get("organization"),
            "address": AddressSerializer().to_representation(
                instance.attributes.get("address", {})
            ),
            # Some external system decided to write this with different casing....
            # The fallback can be removed once this is cleaned up.
            "partnerId": instance.attributes.get("partnerId", instance.attributes.get("partnerID")),
        }
        return ret

    def to_internal_value(self, instance):
        ret = super().to_internal_value(instance)
        return ret

    def update(
        self,
        instance: User,
        validated_data,
    ):
        if instance.path not in settings.SUSE_CUSTOMER_ALLOWED_PATHS:
            raise PermissionDenied("You are not allowed to update users in this path.")

        old_attrs = instance.attributes
        if not self.partial:
            old_attrs = dict()

        # This is called for patch as well as put. So allow partial updates.
        first_name = validated_data.get("firstName", old_attrs.get("givenName"))
        last_name = validated_data.get("lastName", old_attrs.get("sn"))
        full_name = f"{first_name} {last_name}"

        fallback = None
        if self.partial:
            fallback = old_attrs.get("organization")

        company = validated_data.get("company", fallback)

        address_serializer = AddressSerializer(partial=self.partial)

        new_attrs = {
            "cn": full_name,
            "givenName": first_name,
            "sn": last_name,
            "telephoneNumber": validated_data.get("phone", old_attrs.get("telephoneNumber")),
            "title": validated_data.get("title", old_attrs.get("title")),
            "organization": company,
            "address": address_serializer.update(
                old_attrs.get("address"), validated_data.get("address")
            ),
            "partnerId": validated_data.get("partnerId", old_attrs.get("partnerId")),
        }

        for k, v in new_attrs.items():
            instance.attributes[k] = v

        instance.name = full_name
        instance.save()
        return instance

    class Meta:
        model = User
        fields = ["pk", "email", "firstName", "lastName", "phone", "title", "company", "partnerId"]


CACHING_RESOLVER = caching_resolver(timeout=10, cache=DjangoResolverCache())


class CreateCustomerSerializer(CustomerSerializer):
    email = EmailField(
        required=True,
        validators=[UniqueValidator(queryset=User.objects.all())],
    )

    def create(self, validated_data: dict) -> User:
        user_uuid = uuid.uuid4()
        try:
            # Additional e-mail validation to check MX record and normalize e-mail address
            validated_mail = validate_email(
                validated_data["email"], check_deliverability=True, dns_resolver=CACHING_RESOLVER
            )
            email = validated_mail.normalized

            full_name = validated_data["firstName"] + " " + validated_data["lastName"]
            attributes = {
                "cn": full_name,
                "sn": validated_data["lastName"],
                "uid": email,
                "upn": email,
                "mail": [
                    email,
                ],
                "givenName": validated_data["firstName"],
                "telephoneNumber": validated_data["phone"],
                "organization": validated_data.get("company"),
                "partnerId": validated_data.get("partnerId"),
                "title": validated_data["title"],
                "address": AddressSerializer().to_internal_value(validated_data["address"]),
                "uuid": str(user_uuid),
            }

            instance: User = User.objects.create_user(
                uuid=user_uuid,
                username=email,
                email=email,
                name=full_name,
                path=settings.SUSE_CUSTOMER_CREATE_PATH,
                attributes=attributes,
            )
        except IntegrityError as ex:
            raise ConflictError("Duplicate username") from ex
        except EmailNotValidError as ex:
            raise ValidationError("Invalid e-mail") from ex

        return instance


class SUSECustomersViewSet(
    ReadOnlyModelViewSet,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
):
    """
    API endpoint that allows customers to be viewed or edited.
    """

    basename = "suse-customers"
    # Must include employees and community users as well as customers.
    # Just don't allow updates to employees.
    queryset = User.objects.all()
    serializer_class = CustomerSerializer

    # Need to drop authentik.rbac.filters.ObjectFilter
    # because we don't care about the permissions on the actual queryset
    filter_backends = []
    permission_classes = [permissions.IsAuthenticated]

    search_fields = ["name", "path", "username", "uuid", "email"]
    filterset_fields = ["name", "path", "username", "uuid", "email"]
    ordering = ["username", "date_joined", "last_updated"]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return CreateCustomerSerializer
        return super().get_serializer_class()

    @permission_required(None, ["authentik_suse_api.add_susecustomer"])
    def create(self, *args, **kwargs):
        return super().create(*args, **kwargs)

    @permission_required(None, ["authentik_suse_api.view_susecustomer"])
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @permission_required(None, ["authentik_suse_api.view_susecustomer"])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @permission_required(None, ["authentik_suse_api.change_susecustomer"])
    def update(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)
