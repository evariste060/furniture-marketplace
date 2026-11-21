"""Cloudflare R2 storage (STORAGE_BACKEND=r2): request signing, the MediaStorage behaviour against
an in-memory stand-in for the S3 API, and the settings that select it."""

import uuid
from datetime import UTC, datetime
from io import BytesIO
from urllib.parse import parse_qsl, urlsplit

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.integrations.media import StorageError, get_media_storage, incoming_key, new_key
from app.integrations.media.r2 import S3_NS, R2MediaStorage, Response

OWNER = uuid.UUID("1a2b3c4d-5e6f-4a8b-9c0d-1e2f3a4b5c6d")
KEY = new_key("products", OWNER, "jpg", b"photo")


class FakeR2(R2MediaStorage):
    """The S3 calls answered from a dict: {bucket: {key: (body, headers)}}."""

    def __init__(self, page_size: int = 1000) -> None:
        super().__init__(
            endpoint="https://acct.r2.cloudflarestorage.com",
            access_key_id="test-key-id",
            secret_access_key="test-secret",
            public_bucket="shop-public",
            private_bucket="shop-private",
            public_base_url="https://pub-1.r2.dev/",
        )
        self.objects: dict[str, dict[str, tuple[bytes, dict[str, str]]]] = {
            "shop-public": {},
            "shop-private": {},
        }
        self.page_size = page_size
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def _send(self, method, url, headers, body):
        self.calls.append((method, url, headers))
        assert headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=test-key-id/")
        assert "test-secret" not in str(headers)
        parts = urlsplit(url)
        bucket, _, key = parts.path.lstrip("/").partition("/")
        store = self.objects.get(bucket)
        if store is None:
            return Response(404, b"")
        if not key and method == "HEAD":
            return Response(200, b"")
        if not key:
            return self._list(store, dict(parse_qsl(parts.query)))
        if method == "PUT":
            if headers.get("if-none-match") == "*" and key in store:
                return Response(412, b"")
            store[key] = (body, headers)
            return Response(200, b"")
        if key not in store:
            return Response(404, b"")
        if method == "DELETE":
            del store[key]
            return Response(204, b"")
        return Response(200, b"" if method == "HEAD" else store[key][0])

    def _list(self, store, query):
        keys = sorted(k for k in store if k.startswith(query.get("prefix", "")))
        start = int(query.get("continuation-token", "0"))
        page = keys[start : start + self.page_size]
        more = start + self.page_size < len(keys)
        ns = S3_NS.strip("{}")
        xml = f'<ListBucketResult xmlns="{ns}"><IsTruncated>{str(more).lower()}</IsTruncated>'
        xml += "".join(f"<Contents><Key>{k}</Key></Contents>" for k in page)
        if more:
            xml += f"<NextContinuationToken>{start + self.page_size}</NextContinuationToken>"
        return Response(200, (xml + "</ListBucketResult>").encode())


@pytest.fixture
def r2() -> FakeR2:
    return FakeR2()


# ---- signing -------------------------------------------------------------------------------
def test_signature_matches_the_aws_sigv4_example():
    # "Example: GET Object" from the Amazon S3 Signature Version 4 documentation.
    storage = R2MediaStorage(
        endpoint="https://examplebucket.s3.amazonaws.com",
        access_key_id="AKIAIOSFODNN7EXAMPLE",
        secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        public_bucket="a",
        private_bucket="b",
        public_base_url="https://cdn.test",
        region="us-east-1",
    )
    headers = storage._signed_headers(
        "GET",
        "/test.txt",
        {},
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        datetime(2013, 5, 24, tzinfo=UTC),
        {"Range": "bytes=0-9"},
    )
    assert headers["authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
        "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, "
        "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    )


# ---- storage -------------------------------------------------------------------------------
def test_put_get_exists_delete_by_visibility(r2):
    r2.put(KEY, b"public", visibility="public", content_type="image/jpeg", cache_control="max")
    r2.put(KEY, BytesIO(b"private"), visibility="private", content_type="image/jpeg")
    assert r2.get(KEY, visibility="public") == b"public"
    assert r2.get(KEY, visibility="private") == b"private"
    _, headers = r2.objects["shop-public"][KEY]
    assert headers["content-type"] == "image/jpeg" and headers["cache-control"] == "max"
    r2.delete(KEY, visibility="public")
    assert not r2.exists(KEY, visibility="public") and r2.exists(KEY, visibility="private")
    r2.delete(KEY, visibility="public")  # missing is success
    with pytest.raises(StorageError):
        r2.get(KEY, visibility="public")


def test_existing_objects_are_never_overwritten(r2):
    r2.put(KEY, b"first", visibility="public", content_type="image/jpeg")
    with pytest.raises(StorageError, match="already exists"):
        r2.put(KEY, b"second", visibility="public", content_type="image/jpeg")
    assert r2.get(KEY, visibility="public") == b"first"


def test_only_managed_keys_are_accepted(r2):
    incoming = incoming_key(uuid.uuid4(), uuid.uuid4())
    r2.put(incoming, b"x", visibility="private", content_type="application/octet-stream")
    for bad, visibility in (
        ("../secret", "public"),
        ("products/x.jpg", "public"),
        (incoming, "public"),  # incoming uploads are private only
    ):
        with pytest.raises(StorageError, match="Not a media key"):
            r2.put(bad, b"x", visibility=visibility, content_type="image/jpeg")
    assert r2.calls[-1][0] == "PUT"  # the refused keys never reached the network


def test_list_follows_continuation_tokens(r2):
    r2.page_size = 2
    keys = sorted(new_key("brands", OWNER, "png", bytes([n])) for n in range(5))
    for k in keys:
        r2.put(k, b"x", visibility="public", content_type="image/png")
    r2.put(KEY, b"x", visibility="public", content_type="image/jpeg")
    assert list(r2.list("brands/", visibility="public")) == keys
    assert list(r2.list("", visibility="private")) == []


def test_public_url_and_health(r2):
    assert r2.public_url(KEY) == f"https://pub-1.r2.dev/{KEY}"
    assert r2.free_bytes() is None
    r2.buckets["private"] = "missing-bucket"
    with pytest.raises(StorageError):
        r2.free_bytes()


def test_unreachable_storage_is_a_storage_error(r2, monkeypatch):
    def offline(*_args):
        raise OSError("down")

    monkeypatch.setattr(r2, "_send", offline)
    with pytest.raises(StorageError, match="Cannot reach the storage"):
        r2.exists(KEY, visibility="public")


# ---- settings ------------------------------------------------------------------------------
R2_ENV = {
    "STORAGE_BACKEND": "r2",
    "R2_ACCOUNT_ID": "acct",
    "R2_ACCESS_KEY_ID": "id",
    "R2_SECRET_ACCESS_KEY": "secret",
    "R2_PUBLIC_BUCKET": "shop-public",
    "R2_PRIVATE_BUCKET": "shop-private",
}


def test_r2_backend_is_selected_from_settings(monkeypatch):
    for name, value in R2_ENV.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    try:
        storage = get_media_storage()
        assert isinstance(storage, R2MediaStorage)
        assert storage.endpoint == "https://acct.r2.cloudflarestorage.com"
        assert storage.buckets == {"public": "shop-public", "private": "shop-private"}
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    ("missing", "same_buckets"),
    [
        ("R2_ACCOUNT_ID", False),
        ("R2_SECRET_ACCESS_KEY", False),
        ("R2_PRIVATE_BUCKET", False),
        (None, True),
    ],
)
def test_incomplete_r2_settings_are_refused(monkeypatch, missing, same_buckets):
    for name, value in R2_ENV.items():
        monkeypatch.setenv(name, value)
    if missing:
        monkeypatch.setenv(missing, "")
    if same_buckets:
        monkeypatch.setenv("R2_PRIVATE_BUCKET", "shop-public")
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]
