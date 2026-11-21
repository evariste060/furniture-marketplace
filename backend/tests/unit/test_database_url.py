import pytest

from tests.support.database_url import prefer_ipv4_loopback


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "postgresql+psycopg://owner:p%40ss:w%2Frd@localhost:5432/app_test",
            "postgresql+psycopg://owner:p%40ss:w%2Frd@127.0.0.1:5432/app_test",
        ),
        (
            "postgresql+psycopg://owner:pw@LOCALHOST/app_test?sslmode=disable",
            "postgresql+psycopg://owner:pw@127.0.0.1/app_test?sslmode=disable",
        ),
        ("postgresql://localhost:5432/app_test", "postgresql://127.0.0.1:5432/app_test"),
    ],
)
def test_localhost_becomes_ipv4_loopback_and_the_rest_is_unchanged(url: str, expected: str):
    assert prefer_ipv4_loopback(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "postgresql+psycopg://owner:pw@127.0.0.1:55432/app_test",
        "postgresql+psycopg://owner:pw@[::1]:5432/app_test",
        "postgresql+psycopg://owner:pw@db.internal:5432/app_test",
        "postgresql+psycopg://owner:pw@localhost.example.com:5432/app_test",
    ],
)
def test_other_hosts_are_returned_unchanged(url: str | None):
    assert prefer_ipv4_loopback(url) == url
