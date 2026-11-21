"""Image storage (ADR-009), the public media mount and the upload size limit (module 7)."""

import asyncio
import io
import json
import os
import re
import uuid
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import upload_limit
from app.core.upload_limit import UploadSizeLimitMiddleware
from app.integrations.media import (
    INCOMING_KEY_PATTERN,
    KEY_PATTERN,
    LocalMediaStorage,
    MediaStorage,
    PublicMediaFiles,
    StorageError,
    get_media_storage,
    incoming_key,
    new_key,
)

OWNER = uuid.UUID("1a2b3c4d-5e6f-4a8b-9c0d-1e2f3a4b5c6d")
MODULE_7_KEY = "products/" + "a" * 32 + ".jpg"  # the pre-ADR-009 layout, no longer served


@pytest.fixture
def storage(tmp_path) -> LocalMediaStorage:
    return LocalMediaStorage(tmp_path / "media", "http://cdn.test/media/")


def key(extension: str = "jpg", owner: str = "products", content: bytes = b"x") -> str:
    return new_key(owner, OWNER, extension, content)  # type: ignore[arg-type]


def put(storage, k, data=b"x", visibility="public"):
    storage.put(k, data, visibility=visibility, content_type="image/jpeg")


# ---- keys ----------------------------------------------------------------------------------
def test_keys_follow_owner_id_uuid_hash_and_are_new_every_time():
    first, second = key(content=b"same"), key(content=b"same")
    assert first != second  # a replacement never reuses a key
    for value in (first, second):
        assert KEY_PATTERN.fullmatch(value)
        owner, owner_id, name = value.split("/")
        assert (owner, owner_id) == ("products", str(OWNER))
        assert re.fullmatch(r"[0-9a-f]{32}-[0-9a-f]{12}\.jpg", name)
    # The short hash comes from the content: equal content, equal hash.
    assert first.rsplit("-", 1)[1] == second.rsplit("-", 1)[1]
    assert key(content=b"other").rsplit("-", 1)[1] != first.rsplit("-", 1)[1]


@pytest.mark.parametrize("owner", ["products", "categories", "brands", "banners"])
def test_every_owner_has_its_own_prefix(owner):
    assert key("png", owner).startswith(f"{owner}/{OWNER}/")


def test_incoming_keys_are_private_only():
    k = incoming_key(uuid.uuid4(), uuid.uuid4())
    assert INCOMING_KEY_PATTERN.fullmatch(k) and not KEY_PATTERN.fullmatch(k)


def test_the_local_backend_implements_the_whole_interface(storage):
    for method in ("put", "get", "exists", "delete", "public_url", "list", "free_bytes"):
        assert callable(getattr(storage, method)), method
    typed: MediaStorage = storage  # mypy checks the protocol
    assert typed is storage


# ---- put, get, exists, delete, list --------------------------------------------------------
def test_public_and_private_files_live_in_separate_folders(storage):
    k = key()
    put(storage, k, b"original", "private")
    put(storage, k, b"public", "public")
    assert storage.get(k, visibility="private") == b"original"
    assert storage.get(k, visibility="public") == b"public"
    assert (storage.private_root / k).read_bytes() == b"original"
    assert storage.private_root == storage.root / "private"
    assert storage.public_root == storage.root / "public"


def test_put_copies_a_stream_in_chunks(storage, monkeypatch):
    monkeypatch.setattr("app.integrations.media.COPY_CHUNK_BYTES", 4)
    k = incoming_key(uuid.uuid4(), uuid.uuid4())
    storage.put(k, io.BytesIO(b"0123456789"), visibility="private", content_type="image/png")
    assert storage.get(k, visibility="private") == b"0123456789"


def test_put_never_overwrites_an_existing_file(storage):
    k = key()
    put(storage, k, b"first")
    with pytest.raises(StorageError, match="already exists"):
        put(storage, k, b"second")
    assert storage.get(k, visibility="public") == b"first"


def test_put_writes_atomically_and_leaves_no_temporary_files(storage):
    k = key()
    put(storage, k, b"image-bytes")
    folder = (storage.public_root / k).parent
    assert [p.name for p in folder.iterdir()] == [k.split("/")[-1]]  # no ".upload-*.tmp" left


def test_a_failed_write_removes_its_temporary_file_and_raises_a_storage_error(storage, monkeypatch):
    k = key()

    def broken_replace(src, dst):
        raise OSError("disk full at /secret/path")

    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(StorageError) as raised:
        put(storage, k)
    assert "/secret/path" not in str(raised.value)
    assert list((storage.public_root / k).parent.iterdir()) == []


@pytest.mark.parametrize(
    "bad",
    [
        "../secrets.txt",
        "products/../../escape.jpg",
        "/etc/passwd",
        "C:\\Windows\\win.ini",
        f"products/{OWNER}/" + "a" * 32 + "-" + "b" * 12 + ".exe",
        f"products/{OWNER}/" + "a" * 31 + "-" + "b" * 12 + ".jpg",
        f"orders/{OWNER}/" + "a" * 32 + "-" + "b" * 12 + ".jpg",
        f"products/../{OWNER}/" + "a" * 32 + "-" + "b" * 12 + ".jpg",
        "product/first.jpg",  # a key this storage did not create
        MODULE_7_KEY,  # the legacy layout is gone (2026-10-26)
    ],
)
@pytest.mark.parametrize("visibility", ["public", "private"])
def test_only_managed_keys_inside_their_folder_are_accepted(storage, bad, visibility):
    with pytest.raises(StorageError):
        put(storage, bad, b"x", visibility)
    with pytest.raises(StorageError):
        storage.delete(bad, visibility=visibility)
    with pytest.raises(StorageError):
        storage.get(bad, visibility=visibility)


def test_paths_are_checked_without_touching_the_filesystem(storage, monkeypatch):
    # Path.resolve() on Windows can return a differently normalised path while another process
    # creates the same folder, which failed concurrent uploads; containment is lexical now.
    def no_resolve(self, strict=False):
        raise AssertionError("resolve() must not be called")

    monkeypatch.setattr(type(storage.root), "resolve", no_resolve)
    k = key()
    assert storage.path(k, "private") == storage.private_root / k
    with pytest.raises(ValueError):
        storage.path("products/../../escape.jpg", "public")


def test_incoming_keys_are_refused_in_public_storage(storage):
    with pytest.raises(StorageError):
        put(storage, incoming_key(uuid.uuid4(), uuid.uuid4()), b"x", "public")


def test_delete_removes_files_and_a_missing_file_is_success(storage):
    k = key("webp")
    put(storage, k, b"a")
    storage.delete(k, visibility="public")
    assert not storage.exists(k, visibility="public")
    storage.delete(k, visibility="public")  # already gone: idempotent
    storage.delete(k, visibility="private")  # never existed


def test_delete_failures_raise_without_paths(storage, monkeypatch):
    k = key("png")
    put(storage, k, b"a")

    def locked(self, missing_ok=False):
        raise PermissionError("file in use: " + str(self))

    monkeypatch.setattr(type(storage.root), "unlink", locked)
    with pytest.raises(StorageError) as raised:
        storage.delete(k, visibility="public")
    assert "PermissionError" in str(raised.value)
    assert str(storage.root) not in str(raised.value)


def test_get_of_a_missing_file_raises(storage):
    with pytest.raises(StorageError):
        storage.get(key(), visibility="public")


def test_list_returns_keys_by_prefix_and_visibility(storage):
    a, b = key(owner="products"), key(owner="brands")
    put(storage, a)
    put(storage, b)
    put(storage, a, b"orig", "private")
    assert sorted(storage.list("", visibility="public")) == sorted([a, b])
    assert list(storage.list("brands/", visibility="public")) == [b]
    assert list(storage.list("", visibility="private")) == [a]


def test_free_bytes_reports_the_disk(storage):
    free = storage.free_bytes()
    assert isinstance(free, int) and free > 0


def test_public_urls_use_the_base_url_and_never_a_hard_coded_host(storage):
    k = key()
    assert storage.public_url(k) == f"http://cdn.test/media/{k}"
    assert storage.public_url("dir/a b.jpg") == "http://cdn.test/media/dir/a%20b.jpg"


def test_the_configured_backend_uses_media_root_and_the_public_base_url(monkeypatch, tmp_path):
    from app.core import config

    settings = _settings(media_root=str(tmp_path), image_public_base_url="http://img.test/m")
    monkeypatch.setattr("app.integrations.media.get_settings", lambda: settings)
    configured = get_media_storage()
    assert isinstance(configured, LocalMediaStorage)
    assert configured.root == tmp_path.resolve()
    assert configured.public_url("x") == "http://img.test/m/x"
    assert config.Settings.model_fields["storage_backend"].default == "local"


# ---- the /media mount: public sources only -------------------------------------------------
@pytest.fixture
def media_client(storage) -> TestClient:
    app = FastAPI()
    app.mount("/media", PublicMediaFiles(storage), name="media")
    return TestClient(app)


def test_public_sources_are_served(storage, media_client):
    k = key()
    put(storage, k, b"public-bytes")
    res = media_client.get(f"/media/{k}")
    assert res.status_code == 200 and res.content == b"public-bytes"


def test_private_originals_are_not_reachable_over_http(storage, media_client):
    k = key()
    put(storage, k, b"original-bytes", "private")
    for path in (
        f"/media/{k}",  # same key: only the public folder is looked up
        f"/media/private/{k}",
        f"/media/../private/{k}",
        f"/media/%2e%2e/private/{k}",
        f"/media/products/..%2fprivate%2f{k}",
    ):
        res = media_client.get(path)
        assert res.status_code == 404, path
        assert b"original-bytes" not in res.content


def test_nothing_outside_the_public_folder_is_served(storage, media_client):
    # The module 7 layout (files directly under MEDIA_ROOT) is no longer served (2026-10-26).
    (storage.root / "products").mkdir(parents=True)
    (storage.root / MODULE_7_KEY).write_bytes(b"legacy")
    (storage.root / "notes.txt").write_text("not media")
    assert media_client.get(f"/media/{MODULE_7_KEY}").status_code == 404
    assert media_client.get("/media/notes.txt").status_code == 404
    assert media_client.get("/media/../notes.txt").status_code == 404


# ---- upload size limit -------------------------------------------------------------------
UPLOAD_PATH = "/api/v1/staff/products/123/images"


@dataclass
class Outcome:
    status: int
    body: bytes
    headers: dict[bytes, bytes]
    app_saw: bytes | None  # the body the wrapped app received, None if it was never called
    unread_messages: int  # body messages the middleware never read


def run_middleware(
    path: str, chunks: list[bytes], content_length: int | None, max_body: int = 10
) -> Outcome:
    """Drive the middleware with a body split into chunks."""
    app_saw: list[bytes] = []

    async def app(scope, receive, send):
        app_saw.append((await receive())["body"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = UploadSizeLimitMiddleware(
        app, path_pattern=r"/api/v1/staff/products/[^/]+/images/?", max_body=max_body
    )
    headers = [] if content_length is None else [(b"content-length", str(content_length).encode())]
    scope = {"type": "http", "method": "POST", "path": path, "headers": headers}
    messages = [
        {"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1}
        for i, chunk in enumerate(chunks)
    ]
    sent: list = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    asyncio.run(middleware(scope, receive, send))
    return Outcome(
        status=sent[0]["status"],
        body=b"".join(m.get("body", b"") for m in sent[1:]),
        headers=dict(sent[0]["headers"]),
        app_saw=app_saw[0] if app_saw else None,
        unread_messages=len(messages),
    )


def test_a_declared_oversized_body_never_reaches_the_app():
    out = run_middleware(UPLOAD_PATH, [b"x" * 20], content_length=20)
    assert out.status == 413 and out.app_saw is None
    assert json.loads(out.body)["error"]["code"] == "file_too_large"


def test_an_oversized_body_without_content_length_is_refused_while_reading():
    out = run_middleware(UPLOAD_PATH, [b"x" * 6, b"x" * 6], content_length=None)
    assert out.status == 413 and out.app_saw is None
    assert json.loads(out.body)["error"]["code"] == "file_too_large"


def test_a_false_small_content_length_does_not_get_past_the_limit():
    out = run_middleware(UPLOAD_PATH, [b"x" * 6, b"x" * 6], content_length=5)
    assert out.status == 413 and out.app_saw is None


def test_a_body_within_the_limit_reaches_the_app_unchanged():
    out = run_middleware(UPLOAD_PATH, [b"abc", b"de"], content_length=5)
    assert (out.status, out.body, out.app_saw) == (200, b"ok", b"abcde")


def test_other_routes_are_not_limited():
    out = run_middleware("/api/v1/auth/login", [b"x" * 50], content_length=50)
    assert out.status == 200 and out.app_saw == b"x" * 50


def test_an_oversized_body_is_drained_so_the_client_can_read_the_413():
    out = run_middleware(UPLOAD_PATH, [b"x" * 6] * 5, content_length=30)
    assert out.status == 413 and out.app_saw is None
    assert out.unread_messages == 0  # the whole body was read and discarded
    assert b"connection" not in out.headers  # the connection can stay open


def test_a_body_beyond_the_drain_limit_gets_413_and_a_closed_connection(monkeypatch):
    monkeypatch.setattr(upload_limit, "DRAIN_LIMIT_BYTES", 20)
    streamed = run_middleware(UPLOAD_PATH, [b"x" * 6] * 5, content_length=None)
    assert streamed.status == 413 and streamed.headers[b"connection"] == b"close"
    declared = run_middleware(UPLOAD_PATH, [b"x" * 30], content_length=30)
    assert declared.status == 413 and declared.headers[b"connection"] == b"close"
    assert declared.unread_messages == 1  # beyond the drain limit: not read at all


# ---- IMAGE_PUBLIC_BASE_URL outside development -------------------------------------------
def _settings(**overrides):
    from app.core.config import Settings

    base = {
        "database_url": "postgresql+psycopg://x:y@127.0.0.1:1/x",
        "audit_hmac_key": "k" * 40,
        # tests/conftest.py configures the mock payment secret, which production refuses
        "payment_mock_webhook_secret": None,
    }
    return Settings(_env_file=None, **{**base, **overrides})


@pytest.mark.parametrize("env", ["staging", "production"])
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/media",  # the development default
        "http://127.0.0.1:8000/media",
        "http://media.example.rw",  # not HTTPS
        "https://localhost/media",
        "https://cdn.localhost/media",
        "https://127.0.0.1/media",
        "https://[::1]/media",
        "/media",  # relative: not usable by API clients
        "https:///media",
    ],
)
def test_outside_development_the_public_image_url_must_be_public_https(env, url):
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="IMAGE_PUBLIC_BASE_URL must be a public https"):
        _settings(app_env=env, image_public_base_url=url)


def test_public_https_image_urls_are_accepted_and_development_keeps_the_default():
    production = _settings(app_env="production", image_public_base_url="https://img.example.rw/p/")
    assert production.image_public_base_url == "https://img.example.rw/p/"
    assert _settings(app_env="staging", image_public_base_url="https://staging.example.rw/media")
    development = _settings(app_env="development")
    assert development.image_public_base_url == "http://localhost:8000/media"
    assert development.storage_backend == "local"


def test_the_module_7_name_media_base_url_is_still_accepted(monkeypatch):
    monkeypatch.setenv("MEDIA_BASE_URL", "https://old-name.example.rw/media")
    assert _settings(app_env="production").image_public_base_url == (
        "https://old-name.example.rw/media"
    )


def test_the_upload_limit_covers_category_images_and_brand_logos():
    from app.main import app

    limited = [m for m in app.user_middleware if m.cls is UploadSizeLimitMiddleware]
    patterns = [re.compile(m.kwargs["path_pattern"]) for m in limited]
    for path in (
        f"/api/v1/staff/products/{OWNER}/images",
        f"/api/v1/staff/categories/{OWNER}/image",
        f"/api/v1/staff/brands/{OWNER}/logo",
        f"/api/v1/staff/banners/{OWNER}/image",
        "/api/v1/staff/products/bulk-images",
    ):
        assert any(p.fullmatch(path) for p in patterns), path
