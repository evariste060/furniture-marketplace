"""Cloudflare R2 storage (STORAGE_BACKEND=r2; ADR-009), through R2's S3-compatible API.

Two buckets, one per visibility: the public bucket is served at IMAGE_PUBLIC_BASE_URL, the private
bucket is never public. Requests are signed with AWS Signature Version 4 (region "auto") using the
standard library only, so no SDK is needed for the six calls used: PutObject, GetObject,
HeadObject, DeleteObject, ListObjectsV2 and HeadBucket.

Same rules as the local backend: only managed keys are accepted, and an existing object is never
overwritten (a HEAD first, and If-None-Match: * on the PUT so a race is refused by R2 itself).
Error messages never contain credentials, signatures or file contents.
"""

import hashlib
import hmac
import shutil
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from typing import BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from app.integrations.media import (
    COPY_CHUNK_BYTES,
    INCOMING_KEY_PATTERN,
    KEY_PATTERN,
    StorageError,
    Visibility,
)

REGION = "auto"
SERVICE = "s3"
TIMEOUT_SECONDS = 30
S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes


def _encode(value: str, safe: str = "-_.~") -> str:
    return quote(value, safe=safe)


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode(), hashlib.sha256).digest()


class R2MediaStorage:
    """Objects in two R2 buckets (path-style URLs: <endpoint>/<bucket>/<key>)."""

    def __init__(
        self,
        *,
        endpoint: str,
        access_key_id: str,
        secret_access_key: str,
        public_bucket: str,
        private_bucket: str,
        public_base_url: str,
        region: str = REGION,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.host = urlsplit(self.endpoint).netloc
        self.access_key_id = access_key_id
        self._secret = secret_access_key
        self.buckets: dict[Visibility, str] = {"public": public_bucket, "private": private_bucket}
        self.public_base_url = public_base_url.rstrip("/")
        self.region = region

    # ---- signing and transport -------------------------------------------------------------
    def _signed_headers(
        self,
        method: str,
        path: str,
        query: dict[str, str],
        payload_hash: str,
        now: datetime,
        extra: dict[str, str],
    ) -> dict[str, str]:
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        day = amz_date[:8]
        headers = {
            "host": self.host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
            **{name.lower(): value.strip() for name, value in extra.items()},
        }
        names = sorted(headers)
        canonical_query = "&".join(
            f"{_encode(name)}={_encode(value)}" for name, value in sorted(query.items())
        )
        canonical = "\n".join(
            [
                method,
                path,
                canonical_query,
                "".join(f"{name}:{headers[name]}\n" for name in names),
                ";".join(names),
                payload_hash,
            ]
        )
        scope = f"{day}/{self.region}/{SERVICE}/aws4_request"
        to_sign = "\n".join(
            ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()]
        )
        key = _hmac(("AWS4" + self._secret).encode(), day)
        for part in (self.region, SERVICE, "aws4_request"):
            key = _hmac(key, part)
        signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
        headers["authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self.access_key_id}/{scope}, "
            f"SignedHeaders={';'.join(names)}, Signature={signature}"
        )
        return headers

    def _send(self, method: str, url: str, headers: dict[str, str], body: bytes) -> Response:
        """One HTTP request; any HTTP status comes back as a Response (tests replace this)."""
        request = Request(url, data=body or None, headers=headers, method=method)
        try:
            with urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - https only
                return Response(response.status, response.read())
        except HTTPError as exc:
            return Response(exc.code, exc.read())

    def _request(
        self,
        method: str,
        bucket: str,
        key: str = "",
        *,
        query: dict[str, str] | None = None,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> Response:
        query = query or {}
        path = "/" + _encode(bucket) + ("/" + _encode(key, safe="-_.~/") if key else "")
        payload_hash = hashlib.sha256(body).hexdigest() if body else EMPTY_SHA256
        signed = self._signed_headers(
            method, path, query, payload_hash, datetime.now(UTC), headers or {}
        )
        url = self.endpoint + path
        if query:
            url += "?" + "&".join(f"{_encode(k)}={_encode(v)}" for k, v in sorted(query.items()))
        del signed["host"]  # urllib sets it from the URL
        try:
            return self._send(method, url, signed, body)
        except (URLError, OSError, TimeoutError) as exc:
            raise StorageError(f"Cannot reach the storage ({type(exc).__name__}).") from None

    # ---- MediaStorage ----------------------------------------------------------------------
    def _bucket(self, key: str, visibility: Visibility) -> str:
        managed = KEY_PATTERN.fullmatch(key) or (
            visibility == "private" and INCOMING_KEY_PATTERN.fullmatch(key)
        )
        if not managed:
            raise StorageError("Not a media key.")
        return self.buckets[visibility]

    def put(
        self,
        key: str,
        data: bytes | BinaryIO,
        *,
        visibility: Visibility,
        content_type: str,
        cache_control: str | None = None,
    ) -> None:
        bucket = self._bucket(key, visibility)
        if self.exists(key, visibility=visibility):
            raise StorageError("A file already exists under this key.")
        if isinstance(data, bytes | bytearray):
            body = bytes(data)
        else:
            # Uploads are size-limited before they get here (5 MB images, bulk items likewise).
            buffer = BytesIO()
            shutil.copyfileobj(data, buffer, COPY_CHUNK_BYTES)
            body = buffer.getvalue()
        headers = {"Content-Type": content_type, "If-None-Match": "*"}
        if cache_control:
            headers["Cache-Control"] = cache_control
        response = self._request("PUT", bucket, key, body=body, headers=headers)
        if response.status == 412:
            raise StorageError("A file already exists under this key.")
        if response.status != 200:
            raise StorageError(f"Cannot write the file (HTTP {response.status}).")

    def get(self, key: str, *, visibility: Visibility) -> bytes:
        response = self._request("GET", self._bucket(key, visibility), key)
        if response.status != 200:
            raise StorageError(f"Cannot read the file (HTTP {response.status}).")
        return response.body

    def exists(self, key: str, *, visibility: Visibility) -> bool:
        response = self._request("HEAD", self._bucket(key, visibility), key)
        if response.status == 404:
            return False
        if response.status != 200:
            raise StorageError(f"Cannot check the file (HTTP {response.status}).")
        return True

    def delete(self, key: str, *, visibility: Visibility) -> None:
        response = self._request("DELETE", self._bucket(key, visibility), key)
        if response.status not in (200, 204, 404):
            raise StorageError(f"Cannot delete the file (HTTP {response.status}).")

    def public_url(self, key: str) -> str:
        return f"{self.public_base_url}/{quote(key, safe='/')}"

    def list(self, prefix: str, *, visibility: Visibility) -> Iterator[str]:
        token: str | None = None
        while True:
            query = {"list-type": "2", "prefix": prefix}
            if token:
                query["continuation-token"] = token
            response = self._request("GET", self.buckets[visibility], query=query)
            if response.status != 200:
                raise StorageError(f"Cannot list the files (HTTP {response.status}).")
            root = ET.fromstring(response.body)  # noqa: S314 - from our own bucket over https
            for item in root.iter(f"{S3_NS}Contents"):
                key = item.findtext(f"{S3_NS}Key")
                if key:
                    yield key
            token = root.findtext(f"{S3_NS}NextContinuationToken")
            if root.findtext(f"{S3_NS}IsTruncated") != "true" or not token:
                return

    def free_bytes(self) -> int | None:
        """Object storage has no free-space limit: None. Both buckets are checked to exist and be
        reachable (HeadBucket), so the health check reports a broken setup as degraded."""
        for bucket in self.buckets.values():
            response = self._request("HEAD", bucket)
            if response.status != 200:
                raise StorageError(f"Cannot reach the storage (HTTP {response.status}).")
        return None
