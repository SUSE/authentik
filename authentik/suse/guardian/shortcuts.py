"""Convenient shortcuts to manage or check object permissions."""

from functools import lru_cache
from typing import Any

from django.contrib.contenttypes.models import ContentType
from django.db.models import CharField, Count, Q, QuerySet
from django.db.models.functions import Cast
from guardian.ctypes import get_content_type
from guardian.exceptions import (
    GuardianError,
    MixedContentTypeError,
)
from guardian.utils import (
    get_anonymous_user,
    get_role_obj_perms_model,
)


@lru_cache(None)
def _get_ct_cached(app_label: str, codename: str) -> ContentType:
    """Caches `ContentType` instances like its `QuerySet` does."""
    return ContentType.objects.get(app_label=app_label, permission__codename=codename)


def get_objects_for_user(  # noqa: PLR0912 PLR0915
    user: Any,
    perms: str | list[str],
    queryset: QuerySet | None = None,
) -> QuerySet:
    """Get objects that a user has *all* the supplied permissions for.

    Parameters:
        user (User | AnonymousUser): user to check for permissions.
        perms (str | list[str]): permission(s) to be checked.
            These should be full permission names rather than only codenames
            (i.e. `auth.change_user`).
            If more than one permission is present within sequence, their content type **must** be
            the same or `MixedContentTypeError` exception would be raised.
        queryset (QuerySet): a queryset from which to filter objects.
            If not present, the base queryset will just be all objects for the given `perms`.

    Raises:
        MixedContentTypeError: when computed content type for `perms` clashes.

    Example:
        ```shell
        >>> from django.contrib.auth.models import User
        >>> from guardian.shortcuts import get_objects_for_user
        >>> joe = User.objects.get(username='joe')
        >>> get_objects_for_user(joe, 'auth.change_group')
        []
        >>> from guardian.shortcuts import assign_perm
        >>> group = Group.objects.create('some group')
        >>> assign_perm('auth.change_group', joe, group)
        >>> get_objects_for_user(joe, 'auth.change_group')
        [<Group some group>]

        # The permission string can also be an iterable. Continuing with the previous example:

        >>> get_objects_for_user(joe, ['auth.change_group', 'auth.delete_group'])
        []
        >>> get_objects_for_user(joe, ['auth.change_group', 'auth.delete_group'], any_perm=True)
        [<Group some group>]
        >>> assign_perm('auth.delete_group', joe, group)
        >>> get_objects_for_user(joe, ['auth.change_group', 'auth.delete_group'])
        [<Group some group>]
    """
    if isinstance(perms, str):
        perms = [perms]
    ctype = None
    app_label = None
    codenames = set()
    pk_field = "object_pk"

    # Compute codenames, app_label, ctype
    for perm in perms:
        if "." not in perm:
            raise GuardianError(f"Cannot determine app label and content type from {perm}")
        new_app_label, new_codename = perm.split(".", 1)
        if not new_app_label or not new_codename:
            raise GuardianError(f"Cannot determine app label and content type from {perm}")

        if app_label is not None and app_label != new_app_label:
            raise MixedContentTypeError(
                f"Given perms must have same app label ({app_label} != {new_app_label})"
            )

        new_ctype = _get_ct_cached(new_app_label, new_codename)
        if ctype is not None and ctype != new_ctype:
            raise MixedContentTypeError(
                f"ContentType was once computed to be {ctype} and another one {new_ctype}"
            )

        ctype = new_ctype
        app_label = new_app_label
        codenames.add(new_codename)

    if queryset is None:
        queryset = ctype.model_class()._default_manager.all()
    elif ctype != get_content_type(queryset.model):
        raise MixedContentTypeError("Content type for given perms and queryset differs")

    # Superuser has access to all objects
    if user.is_superuser:
        return queryset

    # The anonymous user can have permissions
    if user.is_anonymous:
        user = get_anonymous_user()

    # If the user has a model-level permission, we don't need to filter on it
    model_perms = {code for code in codenames if user.has_perm(ctype.app_label + "." + code)}
    for code in model_perms:
        codenames.discard(code)
    # We may be done
    if len(codenames) == 0:
        return queryset

    # Now we should extract the list of pk values for which we would filter the queryset
    role_model = get_role_obj_perms_model(queryset.model)
    perms_queryset = (
        role_model.objects.filter(role__in=user.all_roles())
        .filter(permission__content_type=ctype)
        .filter(permission__codename__in=codenames)
    )

    if len(codenames) > 1:
        perms_queryset = (
            perms_queryset.values(pk_field)
            .annotate(object_pk_count=Count(pk_field))
            .filter(object_pk_count__gte=len(codenames))
        )

    # pk is either UUID or an integer type, while object_pk is a varchar
    pk = queryset.model._meta.pk

    # From here on, we'll play a type normalization game. Postgresql has strict
    # type matching for types varchars can't be implicitly coerced into uuids
    # and vice versa, same with integers.

    # thus comparing uuid/int with varchar fails on query execution.
    normalized_pk_field = f"t__normalized_{pk.name}"
    normalized_pk_field_lookup = f"{normalized_pk_field}__in"

    perms_queryset = perms_queryset.annotate(
        **{normalized_pk_field: Cast(pk_field, CharField())}
    ).values_list(normalized_pk_field, flat=True)

    if getattr(queryset.model, "parents", None) is not None:
        # here, we play the same game pretty much, this time we extend the
        # subject part of the permissions to include group children.
        #
        # Meaning: granting view permissions on a group parent, gives you view
        # permissions on the children.

        normalized_parents_field = f"t__normalized_{queryset.model.parents.field.name}"
        normalized_parents_field_lookup = f"{normalized_parents_field}__in"

        # Pull now groups matching the current pks returned by the original
        # query _and_ matching the parents.
        values_list = perms_queryset.values_list(normalized_pk_field, flat=True)
        perms_queryset = (
            queryset.model.objects.annotate(
                **{
                    normalized_pk_field: Cast(pk.name, CharField()),
                    normalized_parents_field: Cast(queryset.model.parents.field.name, CharField()),
                }
            ).filter(
                Q(**{normalized_pk_field_lookup: values_list})
                | Q(**{normalized_parents_field_lookup: values_list})
            )
        ).values_list(normalized_pk_field, flat=True)

    # at this point now the `normalized_pk_field` field in the `perms_queryset` is
    # guaranteed to be varchar.
    queryset = queryset.annotate(**{normalized_pk_field: Cast(pk.name, CharField())})

    # Now at this point `normalized_pk_field` in the `queryset` is guaranteed to
    # be a varchar.

    # Now both sides of the comparison are homogeneus, the query planner can
    # take _any_ decision with regards to evaluating these conditions.
    # and still no type mismatch will happen.

    return queryset.filter(**{normalized_pk_field_lookup: perms_queryset})
