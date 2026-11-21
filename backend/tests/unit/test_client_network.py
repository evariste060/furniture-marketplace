"""Client buckets for the cart rate limits (module 11, ADR-008 S1/S3)."""

import pytest

from app.core.rate_limit import client_network


@pytest.mark.parametrize(
    ("mapped", "expected"),
    [
        ("::ffff:203.0.113.7", "203.0.113.7"),
        ("::ffff:198.51.100.9", "198.51.100.9"),
        ("::FFFF:192.0.2.1", "192.0.2.1"),
        ("::ffff:cb00:7107", "203.0.113.7"),  # the same address in hexadecimal form
    ],
)
def test_ipv4_mapped_ipv6_addresses_use_their_ipv4_bucket(mapped, expected):
    assert client_network(mapped) == expected


def test_different_mapped_clients_get_different_buckets():
    first, second = client_network("::ffff:203.0.113.7"), client_network("::ffff:198.51.100.9")
    assert first != second
    assert first == client_network("203.0.113.7")  # same bucket as the plain IPv4 peer


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("2001:db8:1:1::5", "2001:db8:1:1::/64"),
        ("2001:db8:1:1:ffff:ffff:ffff:ffff", "2001:db8:1:1::/64"),
        ("2001:db8:1:2::5", "2001:db8:1:2::/64"),
        ("::1", "::/64"),  # genuine IPv6 loopback stays IPv6
        ("64:ff9b::cb00:7107", "64:ff9b::/64"),  # NAT64 is not IPv4-mapped
    ],
)
def test_genuine_ipv6_addresses_use_their_slash_64(address, expected):
    assert client_network(address) == expected


def test_ipv4_addresses_are_their_own_bucket():
    assert client_network("203.0.113.7") == "203.0.113.7"
    assert client_network("203.0.113.8") != client_network("203.0.113.7")
