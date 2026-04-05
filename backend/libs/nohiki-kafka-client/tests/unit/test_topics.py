"""Unit tests for Kafka topic constants."""

from __future__ import annotations

import re

from nohiki_kafka_client import Topics


class TestTopicsNamingConvention:
    """Test that all topics follow the naming convention."""

    TOPIC_PATTERN = re.compile(r"^[a-z]+(-[a-z]+)*\.(cmd|fct|cdc|sys)\.[a-z]+(-[a-z]+)*\.v\d+$")

    def _get_all_topics(self) -> list[tuple[str, str]]:
        """Get all topic constants from Topics class."""
        return [
            (name, value) for name, value in vars(Topics).items() if isinstance(value, str) and not name.startswith("_")
        ]

    def test_all_topics_follow_naming_convention(self) -> None:
        """All topics must follow <domain>.<classification>.<event>.v<version>."""
        topics = self._get_all_topics()
        assert len(topics) > 0, "No topics found"

        for name, value in topics:
            assert self.TOPIC_PATTERN.match(value), (
                f"Topic {name}={value!r} does not match pattern <domain>.<cmd|fct|cdc|sys>.<event>.v<version>"
            )

    def test_no_duplicate_topic_values(self) -> None:
        """All topic values must be unique."""
        topics = self._get_all_topics()
        values = [v for _, v in topics]
        duplicates = [v for v in values if values.count(v) > 1]
        assert not duplicates, f"Duplicate topic values: {set(duplicates)}"


class TestUserPrefCommandTopics:
    """Test user-pref command topics exist and are correctly named."""

    def test_pref_create_requested_exists(self) -> None:
        """USER_PREF_CREATE_REQUESTED topic exists."""
        assert hasattr(Topics, "USER_PREF_CREATE_REQUESTED")
        assert Topics.USER_PREF_CREATE_REQUESTED == "user-pref.cmd.create-requested.v1"

    def test_pref_update_requested_exists(self) -> None:
        """USER_PREF_UPDATE_REQUESTED topic exists."""
        assert hasattr(Topics, "USER_PREF_UPDATE_REQUESTED")
        assert Topics.USER_PREF_UPDATE_REQUESTED == "user-pref.cmd.update-requested.v1"

    def test_pref_delete_requested_exists(self) -> None:
        """USER_PREF_DELETE_REQUESTED topic exists."""
        assert hasattr(Topics, "USER_PREF_DELETE_REQUESTED")
        assert Topics.USER_PREF_DELETE_REQUESTED == "user-pref.cmd.delete-requested.v1"

    def test_pref_attach_upload_requested_exists(self) -> None:
        """USER_PREF_ATTACH_UPLOAD_REQUESTED topic exists."""
        assert hasattr(Topics, "USER_PREF_ATTACH_UPLOAD_REQUESTED")
        assert Topics.USER_PREF_ATTACH_UPLOAD_REQUESTED == "user-pref.cmd.attach-upload.v1"

    def test_pref_detach_upload_requested_exists(self) -> None:
        """USER_PREF_DETACH_UPLOAD_REQUESTED topic exists."""
        assert hasattr(Topics, "USER_PREF_DETACH_UPLOAD_REQUESTED")
        assert Topics.USER_PREF_DETACH_UPLOAD_REQUESTED == "user-pref.cmd.detach-upload.v1"


class TestUserAuthFactTopics:
    """Test user-auth fact topics exist and are correctly named."""

    def test_access_token_revoked_exists(self) -> None:
        """USER_AUTH_ACCESS_TOKEN_REVOKED topic exists."""
        assert hasattr(Topics, "USER_AUTH_ACCESS_TOKEN_REVOKED")
        assert Topics.USER_AUTH_ACCESS_TOKEN_REVOKED == "user-auth.fct.access-token-revoked.v1"


class TestUserUploadCommandTopics:
    """Test user-upload command topics exist and are correctly named."""

    def test_upload_create_requested_exists(self) -> None:
        """USER_UPLOAD_CREATE_REQUESTED topic exists."""
        assert hasattr(Topics, "USER_UPLOAD_CREATE_REQUESTED")
        assert Topics.USER_UPLOAD_CREATE_REQUESTED == "user-upload.cmd.create-requested.v1"

    def test_upload_delete_requested_exists(self) -> None:
        """USER_UPLOAD_DELETE_REQUESTED topic exists."""
        assert hasattr(Topics, "USER_UPLOAD_DELETE_REQUESTED")
        assert Topics.USER_UPLOAD_DELETE_REQUESTED == "user-upload.cmd.delete-requested.v1"


class TestDocTemplateCommandTopics:
    """Test doc-template command topics exist and are correctly named."""

    def test_template_create_requested_exists(self) -> None:
        """DOC_TEMPLATE_CREATE_REQUESTED topic exists."""
        assert hasattr(Topics, "DOC_TEMPLATE_CREATE_REQUESTED")
        assert Topics.DOC_TEMPLATE_CREATE_REQUESTED == "doc-template.cmd.create-requested.v1"

    def test_template_version_add_requested_exists(self) -> None:
        """DOC_TEMPLATE_VERSION_ADD_REQUESTED topic exists."""
        assert hasattr(Topics, "DOC_TEMPLATE_VERSION_ADD_REQUESTED")
        assert Topics.DOC_TEMPLATE_VERSION_ADD_REQUESTED == "doc-template.cmd.version-add-requested.v1"

    def test_template_delete_requested_exists(self) -> None:
        """DOC_TEMPLATE_DELETE_REQUESTED topic exists."""
        assert hasattr(Topics, "DOC_TEMPLATE_DELETE_REQUESTED")
        assert Topics.DOC_TEMPLATE_DELETE_REQUESTED == "doc-template.cmd.delete-requested.v1"

    def test_template_render_requested_exists(self) -> None:
        """DOC_TEMPLATE_RENDER_REQUESTED topic exists."""
        assert hasattr(Topics, "DOC_TEMPLATE_RENDER_REQUESTED")
        assert Topics.DOC_TEMPLATE_RENDER_REQUESTED == "doc-template.cmd.render-requested.v1"


class TestDocContentTopics:
    """Test doc-content topics exist and are correctly named."""

    def test_content_generation_requested_exists(self) -> None:
        """DOC_CONTENT_GENERATION_REQUESTED topic exists."""
        assert hasattr(Topics, "DOC_CONTENT_GENERATION_REQUESTED")
        assert Topics.DOC_CONTENT_GENERATION_REQUESTED == "doc-content.cmd.generation-requested.v1"

    def test_content_generation_completed_exists(self) -> None:
        """DOC_CONTENT_GENERATION_COMPLETED topic exists."""
        assert hasattr(Topics, "DOC_CONTENT_GENERATION_COMPLETED")
        assert Topics.DOC_CONTENT_GENERATION_COMPLETED == "doc-content.fct.generation-completed.v1"

    def test_content_generation_failed_exists(self) -> None:
        """DOC_CONTENT_GENERATION_FAILED topic exists."""
        assert hasattr(Topics, "DOC_CONTENT_GENERATION_FAILED")
        assert Topics.DOC_CONTENT_GENERATION_FAILED == "doc-content.fct.generation-failed.v1"


class TestExistingTopicsUnchanged:
    """Verify existing topics were not accidentally modified."""

    def test_user_pref_cdc_topics_unchanged(self) -> None:
        """Existing CDC topics must remain unchanged."""
        assert Topics.USER_PREF_CREATED == "user-pref.cdc.pref-created.v1"
        assert Topics.USER_PREF_UPDATED == "user-pref.cdc.pref-updated.v1"
        assert Topics.USER_PREF_DELETED == "user-pref.cdc.pref-deleted.v1"

    def test_user_upload_cdc_topics_unchanged(self) -> None:
        """Existing upload CDC topics must remain unchanged."""
        assert Topics.USER_UPLOAD_CREATED == "user-upload.cdc.upload-created.v1"
        assert Topics.USER_UPLOAD_UPDATED == "user-upload.cdc.upload-updated.v1"
        assert Topics.USER_UPLOAD_DELETED == "user-upload.cdc.upload-deleted.v1"

    def test_doc_template_existing_topics_unchanged(self) -> None:
        """Existing template topics must remain unchanged."""
        assert Topics.DOC_TEMPLATE_RENDER_REQUESTED == "doc-template.cmd.render-requested.v1"
        assert Topics.DOC_TEMPLATE_RENDER_COMPLETED == "doc-template.fct.render-completed.v1"
        assert Topics.DOC_TEMPLATE_CREATED == "doc-template.cdc.template-created.v1"


class TestTopicClassification:
    """Test that topics are correctly classified."""

    def test_command_topics_have_cmd_classification(self) -> None:
        """All command topics must have .cmd. classification."""
        command_topics = [
            Topics.USER_PREF_CREATE_REQUESTED,
            Topics.USER_PREF_UPDATE_REQUESTED,
            Topics.USER_PREF_DELETE_REQUESTED,
            Topics.USER_PREF_ATTACH_UPLOAD_REQUESTED,
            Topics.USER_PREF_DETACH_UPLOAD_REQUESTED,
            Topics.USER_UPLOAD_CREATE_REQUESTED,
            Topics.USER_UPLOAD_DELETE_REQUESTED,
            Topics.DOC_TEMPLATE_CREATE_REQUESTED,
            Topics.DOC_TEMPLATE_VERSION_ADD_REQUESTED,
            Topics.DOC_TEMPLATE_DELETE_REQUESTED,
            Topics.DOC_TEMPLATE_RENDER_REQUESTED,
            Topics.DOC_CONTENT_GENERATION_REQUESTED,
            Topics.JOB_INGEST_DISCOVERY_REQUESTED,
        ]
        for topic in command_topics:
            assert ".cmd." in topic, f"Command topic {topic} missing .cmd. classification"

    def test_cdc_topics_have_cdc_classification(self) -> None:
        """All CDC topics must have .cdc. classification."""
        cdc_topics = [
            Topics.USER_PREF_CREATED,
            Topics.USER_PREF_UPDATED,
            Topics.USER_PREF_DELETED,
            Topics.USER_UPLOAD_CREATED,
            Topics.USER_UPLOAD_UPDATED,
            Topics.USER_UPLOAD_DELETED,
            Topics.DOC_TEMPLATE_CREATED,
            Topics.DOC_TEMPLATE_UPDATED,
            Topics.DOC_TEMPLATE_DELETED,
        ]
        for topic in cdc_topics:
            assert ".cdc." in topic, f"CDC topic {topic} missing .cdc. classification"

    def test_fact_topics_have_fct_classification(self) -> None:
        """All fact topics must have .fct. classification."""
        fact_topics = [
            Topics.USER_PREF_UPLOAD_ATTACHED,
            Topics.USER_PREF_UPLOAD_DETACHED,
            Topics.DOC_TEMPLATE_RENDER_COMPLETED,
            Topics.DOC_CONTENT_GENERATION_COMPLETED,
            Topics.DOC_CONTENT_GENERATION_FAILED,
            Topics.NOTIFICATION_SENT,
            Topics.NOTIFICATION_FAILED,
        ]
        for topic in fact_topics:
            assert ".fct." in topic, f"Fact topic {topic} missing .fct. classification"


class TestTopicDomains:
    """Test that topics have correct domain prefixes."""

    def test_user_pref_topics_have_correct_domain(self) -> None:
        """User pref topics must start with user-pref."""
        user_pref_topics = [
            Topics.USER_PREF_CREATED,
            Topics.USER_PREF_UPDATED,
            Topics.USER_PREF_DELETED,
            Topics.USER_PREF_UPLOAD_ATTACHED,
            Topics.USER_PREF_UPLOAD_DETACHED,
            Topics.USER_PREF_CREATE_REQUESTED,
            Topics.USER_PREF_UPDATE_REQUESTED,
            Topics.USER_PREF_DELETE_REQUESTED,
            Topics.USER_PREF_ATTACH_UPLOAD_REQUESTED,
            Topics.USER_PREF_DETACH_UPLOAD_REQUESTED,
        ]
        for topic in user_pref_topics:
            assert topic.startswith("user-pref."), f"Topic {topic} should start with user-pref."

    def test_user_upload_topics_have_correct_domain(self) -> None:
        """User upload topics must start with user-upload."""
        user_upload_topics = [
            Topics.USER_UPLOAD_CREATED,
            Topics.USER_UPLOAD_UPDATED,
            Topics.USER_UPLOAD_DELETED,
            Topics.USER_UPLOAD_CREATE_REQUESTED,
            Topics.USER_UPLOAD_DELETE_REQUESTED,
        ]
        for topic in user_upload_topics:
            assert topic.startswith("user-upload."), f"Topic {topic} should start with user-upload."

    def test_doc_template_topics_have_correct_domain(self) -> None:
        """Doc template topics must start with doc-template."""
        doc_template_topics = [
            Topics.DOC_TEMPLATE_CREATED,
            Topics.DOC_TEMPLATE_UPDATED,
            Topics.DOC_TEMPLATE_DELETED,
            Topics.DOC_TEMPLATE_RENDER_REQUESTED,
            Topics.DOC_TEMPLATE_RENDER_COMPLETED,
            Topics.DOC_TEMPLATE_CREATE_REQUESTED,
            Topics.DOC_TEMPLATE_VERSION_ADD_REQUESTED,
            Topics.DOC_TEMPLATE_DELETE_REQUESTED,
        ]
        for topic in doc_template_topics:
            assert topic.startswith("doc-template."), f"Topic {topic} should start with doc-template."

    def test_doc_content_topics_have_correct_domain(self) -> None:
        """Doc content topics must start with doc-content."""
        doc_content_topics = [
            Topics.DOC_CONTENT_GENERATION_REQUESTED,
            Topics.DOC_CONTENT_GENERATION_COMPLETED,
            Topics.DOC_CONTENT_GENERATION_FAILED,
        ]
        for topic in doc_content_topics:
            assert topic.startswith("doc-content."), f"Topic {topic} should start with doc-content."
