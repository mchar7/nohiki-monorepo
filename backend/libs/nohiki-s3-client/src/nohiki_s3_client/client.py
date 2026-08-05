"""Async S3 client implementation."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, NoReturn, Protocol, cast
from urllib.parse import quote, urlsplit

from nohiki_s3_client.exceptions import (
    S3ConnectionError,
    S3ObjectNotFoundError,
    S3ObjectTooLargeError,
    S3PermissionError,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from azure.core.exceptions import AzureError
    from azure.storage.blob.aio import BlobServiceClient
    from types_aiobotocore_s3 import S3Client as S3ClientType
    from types_aiobotocore_s3.type_defs import GetObjectOutputTypeDef

    from nohiki_s3_client.settings import S3Settings


class _BoundedAsyncReader(Protocol):
    async def read(self, amount: int = -1) -> bytes: ...


_MAX_S3_KEY_BYTES = 1024
_MAX_SINGLE_PUT_BYTES = 5 * 1024**3
_MAX_LIST_KEYS = 1000
_MAX_PRESIGNED_EXPIRY_SECONDS = 604800
_HTTP_NOT_FOUND = 404
_HTTP_FORBIDDEN = 403


def _validate_key(key: str) -> None:
    """Validate an object key before passing it to the S3 SDK."""
    if not key or len(key.encode("utf-8")) > _MAX_S3_KEY_BYTES or "\x00" in key:
        msg = "S3 object key must be non-empty, NUL-free, and at most 1,024 UTF-8 bytes"
        raise ValueError(msg)


async def _read_bounded_body(response: GetObjectOutputTypeDef, key: str, max_bytes: int) -> bytes:
    """Read at most max_bytes plus one sentinel byte from an S3 response."""
    content_length = response.get("ContentLength")
    if content_length is not None and content_length > max_bytes:
        raise S3ObjectTooLargeError(key, max_bytes, content_length)
    async with response["Body"] as stream:
        # aiobotocore may expose either StreamingBody.read(amt) or the
        # underlying aiohttp response, whose bounded reader lives on content.
        reader = cast("_BoundedAsyncReader", getattr(stream, "content", stream))
        data = bytearray()
        capacity = max_bytes + 1
        while remaining := capacity - len(data):
            chunk = await reader.read(remaining)
            if not chunk:
                break
            data.extend(chunk[:remaining])
    if len(data) > max_bytes:
        raise S3ObjectTooLargeError(key, max_bytes, len(data))
    return bytes(data)


@dataclass(frozen=True, slots=True)
class S3ObjectMetadata:
    """Metadata returned by an S3 HEAD request without downloading the body."""

    content_length: int
    content_type: str | None
    etag: str | None
    metadata: dict[str, str]
    checksum_sha256: str | None


@dataclass(frozen=True, slots=True)
class S3PresignedPutConstraints:
    """Expected PUT properties, signed when the configured provider supports it.

    S3 binds these values into its presigned request. Azure Blob SAS accepts
    them for caller-compatible expectation handling, but completion must
    validate the stored object because Azure does not bind them into the SAS.
    """

    content_type: str | None = None
    content_length: int | None = None
    checksum_sha256: str | None = None


def _build_presigned_params(
    key: str,
    http_method: str,
    constraints: S3PresignedPutConstraints | None,
) -> dict[str, Any]:
    if http_method == "GET" and constraints is not None:
        msg = "content constraints are only valid for presigned PUT requests"
        raise ValueError(msg)
    params: dict[str, Any] = {"Key": key}
    if constraints is None:
        return params
    if constraints.content_type is not None and not constraints.content_type.strip():
        msg = "content_type must not be empty"
        raise ValueError(msg)
    if constraints.content_length is not None and constraints.content_length < 0:
        msg = "content_length must not be negative"
        raise ValueError(msg)
    if constraints.content_type is not None:
        params["ContentType"] = constraints.content_type
    if constraints.content_length is not None:
        params["ContentLength"] = constraints.content_length
    if constraints.checksum_sha256 is not None:
        params["ChecksumSHA256"] = constraints.checksum_sha256
    return params


class _S3Backend:
    """S3-protocol object storage backend."""

    def __init__(self, settings: S3Settings) -> None:
        """Initialize the S3 client with settings."""
        from aiobotocore.session import get_session  # noqa: PLC0415 -- Load AWS SDK on first S3 use.

        if bool(settings.access_key) != bool(settings.secret_key):
            msg = "access_key and secret_key must either both be set or both be omitted"
            raise ValueError(msg)
        self._settings = settings
        self._session = get_session()

    @asynccontextmanager
    async def _get_client(self, endpoint_override: str | None = None) -> AsyncIterator[S3ClientType]:
        """Get an S3 client context manager."""
        from botocore.config import Config  # noqa: PLC0415 -- Load AWS SDK on first S3 use.

        botocore_config = Config(
            connect_timeout=self._settings.connect_timeout,
            read_timeout=self._settings.read_timeout,
            retries={"mode": "standard", "total_max_attempts": 3},
            signature_version="s3v4",
        )

        client_kwargs: dict[str, Any] = {
            "region_name": self._settings.region,
            "config": botocore_config,
        }

        if self._settings.access_key and self._settings.secret_key:
            client_kwargs["aws_access_key_id"] = self._settings.access_key.get_secret_value()
            client_kwargs["aws_secret_access_key"] = self._settings.secret_key.get_secret_value()

        effective_endpoint = endpoint_override or self._settings.endpoint
        if effective_endpoint:
            client_kwargs["endpoint_url"] = effective_endpoint

        async with self._session.create_client("s3", **client_kwargs) as client:
            yield client

    async def get_object(self, key: str, *, max_bytes: int | None = None) -> bytes:
        """Get an object while enforcing a hard download limit.

        Args:
            key: S3 object key.
            max_bytes: Hard byte limit. When omitted, uses the configured
                ``max_download_bytes`` default; downloads are never unbounded.

        Returns:
            Object content as bytes.

        Raises:
            S3ObjectNotFoundError: If the object does not exist.
            S3ObjectTooLargeError: If the object exceeds the byte limit.
            S3PermissionError: If access is denied.
            S3ConnectionError: If connection fails.

        """
        from botocore.exceptions import ClientError  # noqa: PLC0415 -- Load AWS SDK on first S3 use.

        _validate_key(key)
        effective_max_bytes = max_bytes if max_bytes is not None else self._settings.max_download_bytes
        if effective_max_bytes <= 0:
            msg = "max_bytes must be greater than zero"
            raise ValueError(msg)
        try:
            async with self._get_client() as client:
                response = await client.get_object(Bucket=self._settings.bucket, Key=key)
                return await _read_bounded_body(response, key, effective_max_bytes)
        except S3ObjectTooLargeError, ValueError:
            raise
        except ClientError as e:
            if (error_code := e.response.get("Error", {}).get("Code", "")) in ("NoSuchKey", "404"):
                raise S3ObjectNotFoundError(key) from e
            if error_code in ("AccessDenied", "403"):
                raise S3PermissionError(key) from e
            raise S3ConnectionError(str(e)) from e
        except Exception as e:
            raise S3ConnectionError(str(e)) from e

    async def head_object(self, key: str) -> S3ObjectMetadata:
        """Return object metadata without downloading its body."""
        from botocore.exceptions import ClientError  # noqa: PLC0415 -- Load AWS SDK on first S3 use.

        _validate_key(key)
        try:
            async with self._get_client() as client:
                response = await client.head_object(Bucket=self._settings.bucket, Key=key)
                return S3ObjectMetadata(
                    content_length=int(response["ContentLength"]),
                    content_type=response.get("ContentType"),
                    etag=response.get("ETag"),
                    metadata=dict(response.get("Metadata", {})),
                    checksum_sha256=response.get("ChecksumSHA256"),
                )
        except ClientError as e:
            if (error_code := e.response.get("Error", {}).get("Code", "")) in ("NoSuchKey", "404"):
                raise S3ObjectNotFoundError(key) from e
            if error_code in ("AccessDenied", "403"):
                raise S3PermissionError(key) from e
            raise S3ConnectionError(str(e)) from e
        except Exception as e:
            raise S3ConnectionError(str(e)) from e

    async def put_object(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> None:
        """Put an object to S3.

        Args:
            key: S3 object key.
            data: Object content as bytes.
            content_type: MIME type of the content.
            metadata: Optional metadata to attach to the object.

        Raises:
            S3PermissionError: If access is denied.
            S3ConnectionError: If connection fails.

        """
        from botocore.exceptions import ClientError  # noqa: PLC0415 -- Load AWS SDK on first S3 use.

        _validate_key(key)
        if len(data) > _MAX_SINGLE_PUT_BYTES:
            msg = "put_object supports at most 5 GiB; use multipart upload for larger objects"
            raise ValueError(msg)
        try:
            async with self._get_client() as client:
                await client.put_object(
                    Bucket=self._settings.bucket,
                    Key=key,
                    Body=data,
                    ContentType=content_type,
                    Metadata=metadata or {},
                )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code", "") in ("AccessDenied", "403"):
                raise S3PermissionError(key) from e
            raise S3ConnectionError(str(e)) from e
        except Exception as e:
            raise S3ConnectionError(str(e)) from e

    async def delete_object(self, key: str) -> None:
        """Delete an object from S3.

        Args:
            key: S3 object key.

        Raises:
            S3PermissionError: If access is denied.
            S3ConnectionError: If connection fails.

        """
        from botocore.exceptions import ClientError  # noqa: PLC0415 -- Load AWS SDK on first S3 use.

        _validate_key(key)
        try:
            async with self._get_client() as client:
                await client.delete_object(
                    Bucket=self._settings.bucket,
                    Key=key,
                )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code", "") in ("AccessDenied", "403"):
                raise S3PermissionError(key) from e
            raise S3ConnectionError(str(e)) from e
        except Exception as e:
            raise S3ConnectionError(str(e)) from e

    async def object_exists(self, key: str) -> bool:
        """Check if an object exists in S3.

        Args:
            key: S3 object key.

        Returns:
            True if the object exists, False otherwise.

        Raises:
            S3PermissionError: If access is denied.
            S3ConnectionError: If connection fails.

        """
        from botocore.exceptions import ClientError  # noqa: PLC0415 -- Load AWS SDK on first S3 use.

        _validate_key(key)
        try:
            async with self._get_client() as client:
                await client.head_object(
                    Bucket=self._settings.bucket,
                    Key=key,
                )
                return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ("NoSuchKey", "404"):
                return False
            if error_code in ("AccessDenied", "403"):
                raise S3PermissionError(key) from e
            raise S3ConnectionError(str(e)) from e
        except Exception as e:
            raise S3ConnectionError(str(e)) from e

    async def check_bucket_access(self) -> bool:
        """Check if the bucket is accessible.

        Returns:
            True if bucket is accessible.

        Raises:
            S3PermissionError: If access is denied.
            S3ConnectionError: If connection fails.

        """
        from botocore.exceptions import ClientError  # noqa: PLC0415 -- Load AWS SDK on first S3 use.

        if not self._settings.bucket.strip():
            msg = "S3 bucket must not be empty"
            raise ValueError(msg)
        try:
            async with self._get_client() as client:
                await client.head_bucket(Bucket=self._settings.bucket)
                return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ("AccessDenied", "403"):
                raise S3PermissionError(self._settings.bucket) from e
            raise S3ConnectionError(str(e)) from e
        except Exception as e:
            raise S3ConnectionError(str(e)) from e

    async def list_objects_sample(self, max_keys: int = 1) -> list[str]:
        """List a sample of object keys from the bucket.

        Args:
            max_keys: Maximum number of keys to return.

        Returns:
            List of object keys (may be empty if bucket is empty).

        Raises:
            S3PermissionError: If access is denied.
            S3ConnectionError: If connection fails.

        """
        from botocore.exceptions import ClientError  # noqa: PLC0415 -- Load AWS SDK on first S3 use.

        if not 1 <= max_keys <= _MAX_LIST_KEYS:
            msg = f"max_keys must be between 1 and {_MAX_LIST_KEYS}"
            raise ValueError(msg)
        try:
            async with self._get_client() as client:
                response = await client.list_objects_v2(
                    Bucket=self._settings.bucket,
                    MaxKeys=max_keys,
                )
                contents = response.get("Contents", [])
                return [obj["Key"] for obj in contents]
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ("AccessDenied", "403"):
                raise S3PermissionError(self._settings.bucket) from e
            raise S3ConnectionError(str(e)) from e
        except Exception as e:
            raise S3ConnectionError(str(e)) from e

    async def generate_presigned_url(
        self,
        key: str,
        expires_in: int = 3600,
        http_method: str = "GET",
        *,
        put_constraints: S3PresignedPutConstraints | None = None,
    ) -> str:
        """Generate a presigned GET or constrained PUT URL.

        PUT constraints become signed request headers and must be sent exactly
        by the uploading client. Checksum is optional because callers may not
        know it before upload.
        """
        _validate_key(key)
        if not 1 <= expires_in <= _MAX_PRESIGNED_EXPIRY_SECONDS:
            msg = f"expires_in must be between 1 and {_MAX_PRESIGNED_EXPIRY_SECONDS} seconds"
            raise ValueError(msg)
        if http_method not in {"GET", "PUT"}:
            msg = "http_method must be GET or PUT"
            raise ValueError(msg)
        params = _build_presigned_params(key, http_method, put_constraints)
        params["Bucket"] = self._settings.bucket
        params["Key"] = key

        endpoint_override = self._settings.public_url or None
        try:
            async with self._get_client(endpoint_override=endpoint_override) as client:
                client_method = "get_object" if http_method == "GET" else "put_object"
                url: str = await client.generate_presigned_url(
                    ClientMethod=client_method,
                    Params=params,
                    ExpiresIn=expires_in,
                )
                return url
        except Exception as e:
            raise S3ConnectionError(str(e)) from e


class _AzureBlobBackend:
    """Azure Blob Storage backend using workload identity credentials."""

    def __init__(self, settings: S3Settings) -> None:
        endpoint = settings.endpoint.rstrip("/")
        if not endpoint.startswith("https://"):
            msg = "azure_blob endpoint must use HTTPS"
            raise ValueError(msg)
        if settings.public_url and not settings.public_url.startswith("https://"):
            msg = "azure_blob public_url must use HTTPS"
            raise ValueError(msg)
        hostname = urlsplit(endpoint).hostname
        if not hostname:
            msg = "azure_blob endpoint must include an account hostname"
            raise ValueError(msg)
        self._settings = settings
        self._endpoint = endpoint
        self._account_name = (
            settings.access_key.get_secret_value() if settings.access_key is not None else hostname.split(".", 1)[0]
        )
        self._account_key = (
            settings.secret_key.get_secret_value()
            if settings.access_key is not None and settings.secret_key is not None
            else None
        )

    @asynccontextmanager
    async def _get_service(self) -> AsyncIterator[BlobServiceClient]:
        from azure.identity.aio import DefaultAzureCredential  # noqa: PLC0415 -- Load Azure SDK on first use.
        from azure.storage.blob.aio import BlobServiceClient  # noqa: PLC0415 -- Load Azure SDK on first use.

        workload_credential = DefaultAzureCredential() if self._account_key is None else None
        credential = workload_credential or self._account_key
        service = BlobServiceClient(account_url=self._endpoint, credential=credential)
        try:
            yield service
        finally:
            await service.close()
            if workload_credential is not None:
                await workload_credential.close()

    @staticmethod
    def _raise(error: AzureError, key: str) -> NoReturn:
        from azure.core.exceptions import ResourceNotFoundError  # noqa: PLC0415 -- Load Azure SDK on first use.

        status_code = getattr(error, "status_code", None)
        if isinstance(error, ResourceNotFoundError) or status_code == _HTTP_NOT_FOUND:
            raise S3ObjectNotFoundError(key) from error
        if status_code == _HTTP_FORBIDDEN:
            raise S3PermissionError(key) from error
        raise S3ConnectionError(str(error)) from error

    async def get_object(self, key: str, *, max_bytes: int | None = None) -> bytes:
        from azure.core.exceptions import AzureError  # noqa: PLC0415 -- Load Azure SDK on first use.

        _validate_key(key)
        limit = max_bytes if max_bytes is not None else self._settings.max_download_bytes
        if limit <= 0:
            msg = "max_bytes must be greater than zero"
            raise ValueError(msg)
        try:
            async with self._get_service() as service:
                blob = service.get_blob_client(self._settings.bucket, key)
                properties = await blob.get_blob_properties()
                if properties.size > limit:
                    raise S3ObjectTooLargeError(key, limit, properties.size)  # noqa: TRY301
                data = cast("bytes", await (await blob.download_blob(offset=0, length=limit + 1)).readall())
            if len(data) > limit:
                raise S3ObjectTooLargeError(key, limit, len(data))  # noqa: TRY301
            return data  # noqa: TRY300
        except S3ObjectTooLargeError, ValueError:
            raise
        except AzureError as error:
            self._raise(error, key)

    async def head_object(self, key: str) -> S3ObjectMetadata:
        _validate_key(key)
        from azure.core.exceptions import AzureError  # noqa: PLC0415 -- Load Azure SDK on first use.

        try:
            async with self._get_service() as service:
                properties = await service.get_blob_client(self._settings.bucket, key).get_blob_properties()
            content_type = properties.content_settings.content_type if properties.content_settings else None
            return S3ObjectMetadata(
                content_length=properties.size,
                content_type=content_type,
                etag=properties.etag,
                metadata={str(name).lower(): str(value) for name, value in properties.metadata.items()},
                checksum_sha256=None,
            )
        except AzureError as error:
            self._raise(error, key)

    async def put_object(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> None:
        from azure.core.exceptions import AzureError  # noqa: PLC0415 -- Load Azure SDK on first use.
        from azure.storage.blob import ContentSettings  # noqa: PLC0415 -- Load Azure SDK on first use.

        _validate_key(key)
        if len(data) > _MAX_SINGLE_PUT_BYTES:
            msg = "put_object supports at most 5 GiB; use multipart upload for larger objects"
            raise ValueError(msg)
        try:
            async with self._get_service() as service:
                await service.get_blob_client(self._settings.bucket, key).upload_blob(
                    data,
                    length=len(data),
                    metadata=metadata or {},
                    overwrite=True,
                    content_settings=ContentSettings(content_type=content_type),
                )
        except AzureError as error:
            self._raise(error, key)

    async def delete_object(self, key: str) -> None:
        from azure.core.exceptions import (  # noqa: PLC0415 -- Load Azure SDK on first use.
            AzureError,
            ResourceNotFoundError,
        )

        _validate_key(key)
        try:
            async with self._get_service() as service:
                await service.get_blob_client(self._settings.bucket, key).delete_blob(delete_snapshots="include")
        except ResourceNotFoundError:
            return
        except AzureError as error:
            self._raise(error, key)

    async def object_exists(self, key: str) -> bool:
        from azure.core.exceptions import AzureError  # noqa: PLC0415 -- Load Azure SDK on first use.

        _validate_key(key)
        try:
            async with self._get_service() as service:
                return await service.get_blob_client(self._settings.bucket, key).exists()
        except AzureError as error:
            self._raise(error, key)

    async def check_bucket_access(self) -> bool:
        from azure.core.exceptions import AzureError  # noqa: PLC0415 -- Load Azure SDK on first use.

        if not self._settings.bucket.strip():
            msg = "S3 bucket must not be empty"
            raise ValueError(msg)
        try:
            async with self._get_service() as service:
                await service.get_container_client(self._settings.bucket).get_container_properties()
            return True  # noqa: TRY300
        except AzureError as error:
            self._raise(error, self._settings.bucket)

    async def list_objects_sample(self, max_keys: int = 1) -> list[str]:
        from azure.core.exceptions import AzureError  # noqa: PLC0415 -- Load Azure SDK on first use.

        if not 1 <= max_keys <= _MAX_LIST_KEYS:
            msg = f"max_keys must be between 1 and {_MAX_LIST_KEYS}"
            raise ValueError(msg)
        try:
            result: list[str] = []
            async with self._get_service() as service:
                async for blob in service.get_container_client(self._settings.bucket).list_blobs(
                    results_per_page=max_keys
                ):
                    result.append(blob.name)
                    if len(result) == max_keys:
                        break
            return result  # noqa: TRY300
        except AzureError as error:
            self._raise(error, self._settings.bucket)

    async def generate_presigned_url(
        self,
        key: str,
        expires_in: int = 3600,
        http_method: str = "GET",
        *,
        put_constraints: S3PresignedPutConstraints | None = None,
    ) -> str:
        from azure.core.exceptions import AzureError  # noqa: PLC0415 -- Load Azure SDK on first use.
        from azure.storage.blob import (  # noqa: PLC0415 -- Load Azure SDK on first use.
            BlobSasPermissions,
            generate_blob_sas,
        )

        _validate_key(key)
        if not 1 <= expires_in <= _MAX_PRESIGNED_EXPIRY_SECONDS:
            msg = f"expires_in must be between 1 and {_MAX_PRESIGNED_EXPIRY_SECONDS} seconds"
            raise ValueError(msg)
        if http_method not in {"GET", "PUT"}:
            msg = "http_method must be GET or PUT"
            raise ValueError(msg)
        _build_presigned_params(key, http_method, put_constraints)
        now = datetime.now(UTC)
        expiry = now + timedelta(seconds=expires_in)
        permission = BlobSasPermissions(read=True) if http_method == "GET" else BlobSasPermissions(create=True)
        try:
            if self._account_key is not None:
                token = generate_blob_sas(
                    account_name=self._account_name,
                    container_name=self._settings.bucket,
                    blob_name=key,
                    account_key=self._account_key,
                    permission=permission,
                    expiry=expiry,
                    protocol="https",
                )
            else:
                async with self._get_service() as service:
                    delegation_key = await service.get_user_delegation_key(
                        key_start_time=now - timedelta(minutes=5),
                        key_expiry_time=expiry,
                    )
                token = generate_blob_sas(
                    account_name=self._account_name,
                    container_name=self._settings.bucket,
                    blob_name=key,
                    user_delegation_key=delegation_key,
                    permission=permission,
                    expiry=expiry,
                    protocol="https",
                )
        except AzureError as error:
            self._raise(error, key)
        base_url = (self._settings.public_url or self._endpoint).rstrip("/")
        return f"{base_url}/{quote(self._settings.bucket, safe='')}/{quote(key, safe='/')}?{token}"


class S3Client:
    """Caller-compatible object-storage facade dispatching by provider."""

    def __init__(self, settings: S3Settings) -> None:
        """Retain settings until the first object-storage operation."""
        self._settings = settings
        self.__backend: _S3Backend | _AzureBlobBackend | None = None

    def _get_backend(self) -> _S3Backend | _AzureBlobBackend:
        if self.__backend is None:
            self.__backend = (
                _AzureBlobBackend(self._settings)
                if self._settings.provider == "azure_blob"
                else _S3Backend(self._settings)
            )
        return self.__backend

    @property
    def _session(self) -> object:
        """Return the AWS session retained for health and instrumentation seams."""
        backend = self._get_backend()
        if isinstance(backend, _S3Backend):
            return backend._session  # noqa: SLF001
        msg = "Azure Blob clients do not expose an aiobotocore session"
        raise AttributeError(msg)

    async def get_object(self, key: str, *, max_bytes: int | None = None) -> bytes:  # noqa: D102
        return await self._get_backend().get_object(key, max_bytes=max_bytes)

    async def head_object(self, key: str) -> S3ObjectMetadata:  # noqa: D102
        return await self._get_backend().head_object(key)

    async def put_object(  # noqa: D102
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> None:
        await self._get_backend().put_object(key, data, content_type, metadata)

    async def delete_object(self, key: str) -> None:  # noqa: D102
        await self._get_backend().delete_object(key)

    async def object_exists(self, key: str) -> bool:  # noqa: D102
        return await self._get_backend().object_exists(key)

    async def check_bucket_access(self) -> bool:  # noqa: D102
        return await self._get_backend().check_bucket_access()

    async def list_objects_sample(self, max_keys: int = 1) -> list[str]:  # noqa: D102
        return await self._get_backend().list_objects_sample(max_keys)

    def required_upload_headers(self) -> dict[str, str]:
        """Return headers required for direct uploads by the configured provider."""
        if self._settings.provider == "azure_blob":
            return {"x-ms-blob-type": "BlockBlob"}
        return {}

    async def generate_presigned_url(  # noqa: D102
        self,
        key: str,
        expires_in: int = 3600,
        http_method: str = "GET",
        *,
        put_constraints: S3PresignedPutConstraints | None = None,
    ) -> str:
        return await self._get_backend().generate_presigned_url(
            key,
            expires_in,
            http_method,
            put_constraints=put_constraints,
        )
