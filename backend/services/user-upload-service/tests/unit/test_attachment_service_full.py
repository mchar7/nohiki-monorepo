"""unit tests for attachment_service.services.attachment_service module."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from nohiki.common.v1 import ContentType
from nohiki_db_utils.testing import create_mock_session
from nohiki_fastapi_utils.errors import NotFoundError
from nohiki_s3_client import S3ConnectionError, S3Error, S3ObjectNotFoundError, S3PermissionError
from user_upload_service.db.models import Upload, mime_to_content_type
from user_upload_service.services.attachment_service import (
    UploadMetadataInput,
    create_metadata,
    delete_attachment,
    delete_user_attachments,
    exists_by_id,
    get_attachment_by_id,
    get_attachment_by_id_or_none,
    list_user_attachments,
)


class TestGetAttachmentById:
    """Tests for get_attachment_by_id function."""

    @pytest.mark.asyncio
    async def test_returns_attachment_when_found(self) -> None:
        """Returns attachment when it exists and is not deleted."""
        mock_db = create_mock_session()
        upload_id = uuid.uuid4()

        attachment = MagicMock(spec=Upload)
        attachment.id = upload_id
        attachment.is_deleted = False
        mock_db.get = AsyncMock(return_value=attachment)

        result = await get_attachment_by_id(mock_db, upload_id)

        assert result == attachment
        mock_db.get.assert_awaited_once_with(Upload, upload_id)

    @pytest.mark.asyncio
    async def test_raises_not_found_when_missing(self) -> None:
        """Raises NotFoundError when attachment doesn't exist."""
        mock_db = create_mock_session()
        upload_id = uuid.uuid4()
        mock_db.get = AsyncMock(return_value=None)

        with pytest.raises(NotFoundError, match="Upload"):
            await get_attachment_by_id(mock_db, upload_id)

    @pytest.mark.asyncio
    async def test_raises_not_found_when_deleted(self) -> None:
        """Raises NotFoundError when attachment is soft-deleted."""
        mock_db = create_mock_session()
        upload_id = uuid.uuid4()

        attachment = MagicMock(spec=Upload)
        attachment.is_deleted = True
        mock_db.get = AsyncMock(return_value=attachment)

        with pytest.raises(NotFoundError, match="Upload"):
            await get_attachment_by_id(mock_db, upload_id)


class TestGetAttachmentByIdOrNone:
    """Tests for get_attachment_by_id_or_none function."""

    @pytest.mark.asyncio
    async def test_returns_attachment_when_found(self) -> None:
        """Returns attachment when it exists and is not deleted."""
        mock_db = create_mock_session()
        upload_id = uuid.uuid4()

        attachment = MagicMock(spec=Upload)
        attachment.is_deleted = False
        mock_db.get = AsyncMock(return_value=attachment)

        result = await get_attachment_by_id_or_none(mock_db, upload_id)

        assert result == attachment

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self) -> None:
        """Returns None when attachment doesn't exist."""
        mock_db = create_mock_session()
        mock_db.get = AsyncMock(return_value=None)

        result = await get_attachment_by_id_or_none(mock_db, uuid.uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_deleted(self) -> None:
        """Returns None when attachment is soft-deleted."""
        mock_db = create_mock_session()
        attachment = MagicMock(spec=Upload)
        attachment.is_deleted = True
        mock_db.get = AsyncMock(return_value=attachment)

        result = await get_attachment_by_id_or_none(mock_db, uuid.uuid4())

        assert result is None


class TestCreateMetadata:
    """Tests for create_metadata function."""

    @pytest.mark.asyncio
    async def test_creates_upload_record(self) -> None:
        """Creates Upload record from metadata input."""
        mock_db = create_mock_session()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        data = UploadMetadataInput(
            upload_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            storage_key="user/hash/file.pdf",
            filename="file.pdf",
            content_type=ContentType.PDF,
            file_size=1024,
            content_hash="abc123",
        )

        result = await create_metadata(mock_db, data)

        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()
        mock_db.refresh.assert_awaited_once()
        assert result.name == "file.pdf"
        assert result.file_size == 1024


class TestMimeToContentType:
    """Tests for mime_to_content_type function."""

    def test_known_mime_type(self) -> None:
        """Returns correct ContentType for known MIME type."""
        result = mime_to_content_type("application/pdf")
        assert result == ContentType.PDF

    def test_unknown_mime_type(self) -> None:
        """Returns UNSPECIFIED for unknown MIME type."""
        result = mime_to_content_type("application/unknown")
        assert result == ContentType.UNSPECIFIED


class TestListUserAttachments:
    """Tests for list_user_attachments function."""

    @pytest.mark.asyncio
    async def test_returns_user_attachments(self, sample_user_id: uuid.UUID) -> None:
        """Returns list of attachments for user."""
        mock_db = create_mock_session()

        attachments = [MagicMock(spec=Upload), MagicMock(spec=Upload)]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = attachments
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await list_user_attachments(mock_db, sample_user_id)

        assert len(result) == 2
        assert result == attachments

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_none(self, sample_user_id: uuid.UUID) -> None:
        """Returns empty list when user has no attachments."""
        mock_db = create_mock_session()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await list_user_attachments(mock_db, sample_user_id)

        assert result == []


class TestDeleteAttachment:
    """Tests for delete_attachment function."""

    @pytest.mark.asyncio
    async def test_deletes_from_s3_and_marks_deleted(self) -> None:
        """Deletes S3 object and soft-deletes database record."""
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()
        upload_id = uuid.uuid4()

        attachment = MagicMock(spec=Upload)
        attachment.id = upload_id
        attachment.is_deleted = False
        attachment.storage_key = "user/hash/file.pdf"
        mock_db.get = AsyncMock(return_value=attachment)

        mock_s3 = AsyncMock()
        mock_s3.delete_object = AsyncMock()

        result = await delete_attachment(mock_db, mock_s3, upload_id)

        mock_s3.delete_object.assert_awaited_once_with(attachment.storage_key)
        assert attachment.is_deleted is True
        mock_db.flush.assert_awaited_once()
        assert result == attachment

    @pytest.mark.asyncio
    async def test_preserves_metadata_on_s3_error(self) -> None:
        """Leaves metadata active so Kafka redelivery can retry S3 deletion."""
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()
        upload_id = uuid.uuid4()

        attachment = MagicMock(spec=Upload)
        attachment.id = upload_id
        attachment.is_deleted = False
        attachment.storage_key = "user/hash/file.pdf"
        mock_db.get = AsyncMock(return_value=attachment)

        mock_s3 = AsyncMock()
        mock_s3.delete_object = AsyncMock(side_effect=S3Error("S3 error"))

        with pytest.raises(S3Error, match="S3 error"):
            await delete_attachment(mock_db, mock_s3, upload_id)

        assert attachment.is_deleted is False
        mock_db.flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_treats_missing_s3_object_as_success(self) -> None:
        """Soft-deletes metadata when the provider already removed the object."""
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()
        upload_id = uuid.uuid4()

        attachment = MagicMock(spec=Upload, is_deleted=False, storage_key="missing-key")
        mock_db.get = AsyncMock(return_value=attachment)

        mock_s3 = AsyncMock()
        mock_s3.delete_object = AsyncMock(side_effect=S3ObjectNotFoundError(attachment.storage_key))

        result = await delete_attachment(mock_db, mock_s3, upload_id)

        mock_s3.delete_object.assert_awaited_once_with(attachment.storage_key)
        assert result is attachment
        assert attachment.is_deleted is True
        mock_db.flush.assert_awaited_once()

    @pytest.mark.parametrize(
        "failure",
        [S3PermissionError("forbidden-key"), S3ConnectionError("storage unavailable")],
    )
    @pytest.mark.asyncio
    async def test_propagates_permission_and_connection_failures(self, failure: S3Error) -> None:
        """Leaves metadata active when deletion cannot be confirmed."""
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()
        upload_id = uuid.uuid4()

        attachment = MagicMock(spec=Upload, is_deleted=False, storage_key="key")
        mock_db.get = AsyncMock(return_value=attachment)

        mock_s3 = AsyncMock()
        mock_s3.delete_object = AsyncMock(side_effect=failure)

        with pytest.raises(type(failure)) as exc_info:
            await delete_attachment(mock_db, mock_s3, upload_id)

        assert exc_info.value is failure
        assert attachment.is_deleted is False
        mock_db.flush.assert_not_awaited()


class TestDeleteUserAttachments:
    """Tests for delete_user_attachments function."""

    @pytest.mark.asyncio
    async def test_deletes_all_user_attachments(self, sample_user_id: uuid.UUID) -> None:
        """Deletes all attachments for a user."""
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()

        attachments = [
            MagicMock(spec=Upload, storage_key="key1", is_deleted=False),
            MagicMock(spec=Upload, storage_key="key2", is_deleted=False),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = attachments
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_s3 = AsyncMock()
        mock_s3.delete_object = AsyncMock()

        result = await delete_user_attachments(mock_db, mock_s3, sample_user_id)

        assert len(result) == 2
        assert mock_s3.delete_object.await_count == 2
        for att in result:
            assert att.is_deleted is True

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_attachments(self, sample_user_id: uuid.UUID) -> None:
        """Returns zero when user has no attachments."""
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_s3 = AsyncMock()

        result = await delete_user_attachments(mock_db, mock_s3, sample_user_id)

        assert result == []
        mock_s3.delete_object.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_preserves_metadata_on_individual_s3_error(self, sample_user_id: uuid.UUID) -> None:
        """Leaves all metadata active so Kafka redelivery retries the cascade."""
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()

        attachments = [
            MagicMock(spec=Upload, storage_key="key1", is_deleted=False),
            MagicMock(spec=Upload, storage_key="key2", is_deleted=False),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = attachments
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_s3 = AsyncMock()
        mock_s3.delete_object = AsyncMock(side_effect=[S3Error("Failed"), None])

        with pytest.raises(ExceptionGroup) as exc_info:
            await delete_user_attachments(mock_db, mock_s3, sample_user_id)

        assert any(isinstance(error, S3Error) for error in exc_info.value.exceptions)
        assert all(attachment.is_deleted is False for attachment in attachments)
        mock_db.flush.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_treats_missing_objects_as_success(self, sample_user_id: uuid.UUID) -> None:
        """Soft-deletes every record when the provider already removed every object."""
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()

        attachments = [
            MagicMock(spec=Upload, storage_key="missing-key-1", is_deleted=False),
            MagicMock(spec=Upload, storage_key="missing-key-2", is_deleted=False),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = attachments
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_s3 = AsyncMock()
        mock_s3.delete_object = AsyncMock(
            side_effect=[
                S3ObjectNotFoundError(attachments[0].storage_key),
                S3ObjectNotFoundError(attachments[1].storage_key),
            ],
        )

        result = await delete_user_attachments(mock_db, mock_s3, sample_user_id)

        assert result == attachments
        assert all(attachment.is_deleted is True for attachment in attachments)
        assert mock_s3.delete_object.await_count == 2
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retries_partial_bulk_failure_after_missing_object(self, sample_user_id: uuid.UUID) -> None:
        """Allows a later retry when one object is gone but another cannot be reached."""
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()

        attachments = [
            MagicMock(spec=Upload, storage_key="missing-key", is_deleted=False),
            MagicMock(spec=Upload, storage_key="unavailable-key", is_deleted=False),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = attachments
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_s3 = AsyncMock()
        mock_s3.delete_object = AsyncMock(
            side_effect=[
                S3ObjectNotFoundError(attachments[0].storage_key),
                S3ConnectionError("storage unavailable"),
            ],
        )

        with pytest.raises(ExceptionGroup) as exc_info:
            await delete_user_attachments(mock_db, mock_s3, sample_user_id)

        assert any(isinstance(error, S3ConnectionError) for error in exc_info.value.exceptions)
        assert all(attachment.is_deleted is False for attachment in attachments)
        mock_db.flush.assert_not_awaited()

        mock_s3.delete_object.side_effect = None
        result = await delete_user_attachments(mock_db, mock_s3, sample_user_id)

        assert result == attachments
        assert all(attachment.is_deleted is True for attachment in attachments)
        assert mock_s3.delete_object.await_count == 4
        mock_db.flush.assert_awaited_once()


class TestExistsById:
    """Tests for exists_by_id function."""

    @pytest.mark.asyncio
    async def test_returns_true_when_record_exists(self) -> None:
        """Returns True for existing record regardless of is_deleted."""
        mock_db = create_mock_session()
        upload_id = uuid.uuid4()
        attachment = MagicMock(spec=Upload)
        attachment.is_deleted = True  # even soft-deleted
        mock_db.get = AsyncMock(return_value=attachment)

        assert await exists_by_id(mock_db, upload_id) is True
        mock_db.get.assert_awaited_once_with(Upload, upload_id)

    @pytest.mark.asyncio
    async def test_returns_false_when_no_record(self) -> None:
        """Returns False when no record exists."""
        mock_db = create_mock_session()
        mock_db.get = AsyncMock(return_value=None)

        assert await exists_by_id(mock_db, uuid.uuid4()) is False
