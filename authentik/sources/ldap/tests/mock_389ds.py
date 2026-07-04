"""ldap testing utils"""

import datetime

from ldap3 import MOCK_SYNC, Connection, Server
from ldap3.protocol.rfc4512 import DsaInfo, SchemaInfo
from ldap3.protocol.schemas.ds389 import ds389_1_3_3_dsa_info, ds389_1_3_3_schema

# The mock modifies these in place, so we have to define them per string
user_in_389ds_dn = "cn=user_in_389ds_cn,ou=users,dc=goauthentik,dc=io"
user_in_389ds_cn = "user_in_389ds_cn"
user_in_389ds_uid = "user_in_389ds_uid"
user_in_389ds_object_class = "person"
user_in_389ds = {
    "dn": user_in_389ds_dn,
    "attributes": {
        "cn": user_in_389ds_cn,
        "uid": user_in_389ds_uid,
        "objectClass": user_in_389ds_object_class,
    },
}
group_in_389ds_dn = "cn=user_in_389ds_cn,ou=groups,dc=goauthentik,dc=io"
group_in_389ds_cn = "group_in_389ds_cn"
group_in_389ds_uid = "group_in_389ds_uid"
group_in_389ds_object_class = "groupOfNames"
group_in_389ds = {
    "dn": group_in_389ds_dn,
    "attributes": {
        "cn": group_in_389ds_cn,
        "uid": group_in_389ds_uid,
        "objectClass": group_in_389ds_object_class,
        "member": [user_in_389ds["dn"]],
    },
}


def dt_delta(days):
    return datetime.timedelta(days=days)


def ldap_ts_format(dt):
    return dt.strftime("%Y%m%d%H%M%SZ")


def mock_389ds_connection(password: str) -> Connection:
    """Create mock 389ds connection"""

    start_date = datetime.datetime.now(datetime.UTC)

    server = Server("my_fake_server")
    server.attach_schema_info(SchemaInfo.from_json(ds389_1_3_3_schema))
    server.attach_dsa_info(DsaInfo.from_json(ds389_1_3_3_dsa_info))

    _pass = "foo"  # noqa # nosec
    connection = Connection(
        server,
        user="cn=my_user,dc=goauthentik,dc=io",
        password=_pass,
        client_strategy=MOCK_SYNC,
    )
    # Entry for password checking
    connection.strategy.add_entry(
        "cn=user,ou=users,dc=goauthentik,dc=io",
        {
            "name": "test-user",
            "uid": "unique-test-username",
            "objectClass": "person",
            "displayName": "Erin M. Hagens",
            "modifyTimestamp": ldap_ts_format(start_date - dt_delta(1)),
            "createTimestamp": ldap_ts_format(start_date - dt_delta(2)),
        },
    )
    connection.strategy.add_entry(
        "cn=group1,ou=groups,dc=goauthentik,dc=io",
        {
            "cn": "group1",
            "uid": "unique-test-username",
            "objectClass": "groupOfNames",
            "member": ["cn=user0,ou=users,dc=goauthentik,dc=io"],
            "memberUid": ["user0"],
            "modifyTimestamp": ldap_ts_format(start_date),
            "createTimestamp": ldap_ts_format(start_date - dt_delta(2)),
        },
    )
    # Group without SID
    connection.strategy.add_entry(
        "cn=group2,ou=groups,dc=goauthentik,dc=io",
        {
            "cn": "group2",
            "objectClass": "groupOfNames",
            "modifyTimestamp": ldap_ts_format(start_date - dt_delta(1)),
            "createTimestamp": ldap_ts_format(start_date - dt_delta(2)),
        },
    )
    connection.strategy.add_entry(
        "cn=user0,ou=users,dc=goauthentik,dc=io",
        {
            "userPassword": password,
            "name": "user0_sn",
            "uid": "user0_sn",
            "objectClass": "person",
            "modifyTimestamp": ldap_ts_format(start_date - dt_delta(1)),
            "createTimestamp": ldap_ts_format(start_date - dt_delta(2)),
        },
    )
    # User without SID
    connection.strategy.add_entry(
        "cn=user1,ou=users,dc=goauthentik,dc=io",
        {
            "userPassword": "test1111",
            "name": "user1_sn",
            "objectClass": "person",
            "modifyTimestamp": ldap_ts_format(start_date - dt_delta(1)),
            "createTimestamp": ldap_ts_format(start_date - dt_delta(2)),
        },
    )
    # Duplicate users
    connection.strategy.add_entry(
        "cn=user2,ou=users,dc=goauthentik,dc=io",
        {
            "userPassword": "test2222",
            "name": "user2_sn",
            "uid": "unique-test2222",
            "objectClass": "person",
            "modifyTimestamp": ldap_ts_format(start_date),
            "createTimestamp": ldap_ts_format(start_date - dt_delta(2)),
        },
    )
    connection.strategy.add_entry(
        "cn=user3,ou=users,dc=goauthentik,dc=io",
        {
            "userPassword": "test2222",
            "name": "user2_sn",
            "uid": "unique-test2222",
            "objectClass": "person",
            "modifyTimestamp": ldap_ts_format(start_date - dt_delta(0.5)),
            "createTimestamp": ldap_ts_format(start_date - dt_delta(1)),
        },
    )
    # Group with posixGroup and memberUid
    connection.strategy.add_entry(
        "cn=group-posix,ou=groups,dc=goauthentik,dc=io",
        {
            "cn": "group-posix",
            "objectClass": "posixGroup",
            "memberUid": ["user-posix"],
            "modifyTimestamp": ldap_ts_format(start_date),
            "createTimestamp": ldap_ts_format(start_date - dt_delta(2)),
        },
    )
    # User with posixAccount
    connection.strategy.add_entry(
        "cn=user-posix,ou=users,dc=goauthentik,dc=io",
        {
            "userPassword": password,
            "uid": "user-posix",
            "cn": "user-posix",
            "objectClass": "posixAccount",
            "modifyTimestamp": ldap_ts_format(start_date - dt_delta(1)),
            "createTimestamp": ldap_ts_format(start_date - dt_delta(2)),
        },
    )
    # Known user and group
    connection.strategy.add_entry(
        user_in_389ds["dn"],
        user_in_389ds["attributes"],
    )
    connection.strategy.add_entry(
        group_in_389ds["dn"],
        group_in_389ds["attributes"],
    )
    connection.bind()
    return connection
