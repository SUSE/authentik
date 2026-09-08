from django.db.utils import IntegrityError
from rest_framework import serializers, mixins
from rest_framework.exceptions import ValidationError
from rest_framework.fields import CharField, EmailField
from rest_framework.status import HTTP_409_CONFLICT
from rest_framework.validators import UniqueValidator
from rest_framework.viewsets import ReadOnlyModelViewSet

from authentik.core.models import User
from authentik.lib.merge import MERGE_LIST_UNIQUE


class ConflictError(ValidationError):
    status_code = HTTP_409_CONFLICT

    def __init__(self, detail: str):
        super().__init__(
            detail
        )

class AddressSerializer(serializers.Serializer):

    state = CharField(
        max_length=150,
        required=True,
    )

    street = CharField(
        max_length=150,
        required=True,
    )

    country = CharField(
        max_length=2,
        min_length=2,
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
        return {
            "state": instance.get('state'),
            "street": instance.get('street'),
            "country": instance.get('country'),
            "locality": instance.get('locality'),
            "postalCode": instance.get('postalCode'),
        }

    def update(self, instance: dict, validated_data):
        if validated_data is None:
            return instance

        return {
            "state": validated_data.get('state', instance.get('state')),
            "street": validated_data.get('street', instance.get('street')),
            "country": validated_data.get('country', instance.get('country')),
            "locality": validated_data.get('locality', instance.get('locality')),
            "postalCode": validated_data.get('postalCode', instance.get('postalCode')),
        }

class CustomerSerializer(serializers.Serializer):
    email = EmailField(
        read_only=True,
    )

    first_name = CharField(
        max_length=150,
        required=True,
    )

    last_name = CharField(
        max_length=150,
        required=True,
    )

    phone = CharField(
        max_length=30,
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

    address = AddressSerializer()

    def to_representation(self, instance):
        """Convert `username` to lowercase."""
        ret = {
            'email': instance.email.lower(),
            'first_name': instance.attributes.get('givenName'),
            'last_name': instance.attributes.get('sn'),
            'phone': instance.attributes.get('telephoneNumber'),
            'title': instance.attributes.get('title'),
            'company': instance.attributes.get('organization'),
            'address': AddressSerializer().to_representation(instance.attributes.get('address', {})),
        }
        return ret

    def to_internal_value(self, instance):
        ret = super().to_internal_value(instance)
        return ret


    def update(self, instance: User, validated_data):
        # This is called for patch as well as put. So allow partial updates.
        first_name = validated_data.get('first_name', instance.attributes.get('givenName'))
        last_name = validated_data.get('last_name', instance.attributes.get('sn'))
        full_name = first_name + " " + last_name

        MERGE_LIST_UNIQUE.merge(instance.attributes, {
            "cn": full_name,
            'givenName': first_name,
            'sn': last_name,
            'telephoneNumber': validated_data.get('phone', instance.attributes.get('telephoneNumber')),
            'title': validated_data.get('title', instance.attributes.get('title')),
            'organization': validated_data.get('company', instance.attributes.get('organization')),
            'address': AddressSerializer().update(instance.attributes.get('address'), validated_data.get('address')),
        })

        instance.name = full_name

        instance.save()
        return instance

    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'phone', 'title', 'company']

class CreateCustomerSerializer(CustomerSerializer):
    email = EmailField(
        required=True,
        validators=[UniqueValidator(queryset=User.objects.all())],
    )


    def create(self, validated_data: dict) -> User:
        # TODO Check that there is no conflict with existing communityUids? Same for workday script...

        try:
            email = validated_data['email'].lower()
            full_name = validated_data['first_name'] + " " + validated_data['last_name']
            attributes = {
                "cn": full_name,
                "sn": validated_data['last_name'],
                "uid": email,
                "upn": email,
                "mail": [
                    email,
                ],
                "givenName": validated_data['first_name'],
                "telephoneNumber": validated_data['phone'],
                "organization": validated_data['company'],
                "title": validated_data['title'],
                'address': AddressSerializer().to_internal_value(validated_data['address']),
                # TODO uuid?
            }

            instance: User = User.objects.create_user(
                username=email,
                email=email,
                name=full_name,
                path="SUSE/People/Customers",
                attributes=attributes,
            )
        except IntegrityError as ex:
            raise ConflictError("Duplicate username") from ex

        return instance

class SUSECustomersViewSet(
    ReadOnlyModelViewSet, mixins.CreateModelMixin, mixins.UpdateModelMixin,
):
    """
    API endpoint that allows customers to be viewed or edited.
    """
    basename = "suse-customers"
    queryset = User.objects.filter(path="SUSE/People/Customers").all()
    serializer_class = CustomerSerializer
    lookup_field = 'username'
    lookup_url_kwarg = 'email'

    # Dots are not allowed by default. So allow everything that is not a slash.
    lookup_value_regex = r'[^\/]+'

    def get_serializer_class(self):
        serializer_class = self.serializer_class
        if self.request.method == 'POST':
            serializer_class = CreateCustomerSerializer
        return serializer_class

    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    # TODO
    #permission_classes = [permissions.IsAuthenticated]
