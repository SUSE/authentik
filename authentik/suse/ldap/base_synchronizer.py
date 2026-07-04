"""Sync LDAP Users and groups into authentik"""

from itertools import batched

from ldap3 import ALL_ATTRIBUTES, ALL_OPERATIONAL_ATTRIBUTES, DEREF_ALWAYS, SUBTREE
from ldap3.utils.conv import escape_filter_chars

from authentik.lib.config import CONFIG


class BaseSynchronizer:
    def add_modify_timestamp_filter(self, search_filter, since):
        dt_since = since.strftime("%Y%m%d%H%M%SZ")
        return f"(&{search_filter}(modifyTimestamp>={dt_since}))"

    def get_ldap_attributes(self):
        return [
            ALL_ATTRIBUTES,
            ALL_OPERATIONAL_ATTRIBUTES,
            self._source.object_uniqueness_field,
        ]

    def get_filter_and_base(self, search_base, attribute_name=None, attribute_value=None, dn=None):
        if dn:
            # DN wins over everything, dn's are assumed to be escaped
            rdns = dn.split(",", 1)
            first_dn_component = rdns[0]
            search_base = rdns[1]
            return f"({first_dn_component})", search_base

        if not (attribute_name or attribute_value):
            raise ValueError("Neither attribute_name, nor attribute_value were provided")

        escaped = escape_filter_chars(attribute_value)
        return f"(&{self._source.user_object_filter}({attribute_name}={escaped}))", search_base

    def search_generator(  # noqa: PLR0913
        self,
        search_base,
        search_filter,
        search_scope=SUBTREE,
        dereference_aliases=DEREF_ALWAYS,
        attributes=None,
        size_limit=0,
        time_limit=0,
        types_only=False,
        get_operational_attributes=False,
        controls=None,
        paged_size=None,
        paged_criticality=False,
    ):
        yield from self._connection.extend.standard.paged_search(
            search_base=search_base,
            search_filter=search_filter,
            search_scope=search_scope,
            dereference_aliases=dereference_aliases,
            attributes=attributes,
            size_limit=size_limit,
            time_limit=time_limit,
            types_only=types_only,
            get_operational_attributes=get_operational_attributes,
            controls=controls,
            paged_size=paged_size,
            paged_criticality=paged_criticality,
            generator=True,
        )

    def search_paginator(  # noqa: PLR0913
        self,
        search_base,
        search_filter,
        search_scope=SUBTREE,
        dereference_aliases=DEREF_ALWAYS,
        attributes=None,
        size_limit=0,
        time_limit=0,
        types_only=False,
        get_operational_attributes=False,
        controls=None,
        paged_size=None,
        chunk_size=None,
        paged_criticality=False,
    ):
        """Search in pages, returns each page"""
        if not paged_size:
            paged_size = CONFIG.get_int("ldap.page_size", 50)

        if not chunk_size:
            chunk_size = paged_size

        generator = self.search_generator(
            search_base=search_base,
            search_filter=search_filter,
            search_scope=search_scope,
            dereference_aliases=dereference_aliases,
            attributes=attributes,
            size_limit=size_limit,
            time_limit=time_limit,
            types_only=types_only,
            get_operational_attributes=get_operational_attributes,
            controls=controls,
            paged_size=paged_size,
            paged_criticality=paged_criticality,
        )

        yield from batched(generator, chunk_size, strict=False)
