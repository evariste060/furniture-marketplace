"""Test-only database URL helpers."""

from urllib.parse import urlsplit, urlunsplit


def prefer_ipv4_loopback(url: str | None) -> str | None:
    """Point a 'localhost' database URL at 127.0.0.1; leave every other part byte-for-byte.

    On Windows 'localhost' resolves to ::1 first. docker-compose.yml publishes PostgreSQL on
    127.0.0.1 only, and libpq there waits the whole connect_timeout on ::1 before trying IPv4, so
    every new test connection cost seconds. URLs for any other host are returned unchanged.
    """
    if not url:
        return url
    parts = urlsplit(url)
    if (parts.hostname or "").lower() != "localhost":
        return url
    userinfo, at, hostport = parts.netloc.rpartition("@")
    _, colon, port = hostport.partition(":")
    return urlunsplit(parts._replace(netloc=f"{userinfo}{at}127.0.0.1{colon}{port}"))
