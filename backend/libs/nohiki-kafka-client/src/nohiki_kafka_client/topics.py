"""Kafka topic constants for Nohiki microservices.

Topic naming convention: <scope-subdomain>.<classification>.<event-name>.v<version>

Classifications:
- fct: Fact/Event (something happened, immutable)
- cdc: Change Data Capture (entity state change)
- cmd: Command (request to do something)
- sys: System/Internal (not for external consumption)

Scope-Subdomain Prefixes:
- user-: User-centric data (auth, pref, upload, entitlement)
- job-: Job lifecycle (ingest, listing, correlation)
- doc-: Document generation (schema, layout, content)
- (none): Infrastructure services (notification, ml)

Usage:
    from nohiki_kafka_client import Topics

    @kafka_client.message_handler(Topics.USER_PREF_CREATED, ...)
    async def handle_pref_created(...): ...

    await kafka_client.publish(topic=Topics.JOB_LISTING_CREATED, ...)
"""

from typing import Final


class Topics:
    """Centralized Kafka topic constants.

    All topic names follow the convention: <scope-subdomain>.<classification>.<event-name>.v<version>
    Import this class and access topics as Topics.TOPIC_NAME.
    """

    # ════════════════════════════════════════════════════════════════════════════
    # USER DOMAIN
    # ════════════════════════════════════════════════════════════════════════════

    USER_AUTH_ACCOUNT_DELETED: Final[str] = "user-auth.cdc.account-deleted.v1"
    USER_AUTH_ACCOUNT_UPDATED: Final[str] = "user-auth.cdc.account-updated.v1"
    USER_AUTH_ACTIVITY: Final[str] = "user-auth.fct.activity.v1"
    # This Kafka topic identifier is not a credential; S105 is a false positive.
    USER_AUTH_ACCESS_TOKEN_REVOKED: Final[str] = "user-auth.fct.access-token-revoked.v1"  # noqa: S105

    # Preferences (user-pref-service) - CDC topics
    USER_PREF_CREATED: Final[str] = "user-pref.cdc.pref-created.v1"
    USER_PREF_UPDATED: Final[str] = "user-pref.cdc.pref-updated.v1"
    USER_PREF_DELETED: Final[str] = "user-pref.cdc.pref-deleted.v1"

    # Preferences (user-pref-service) - Fact topics
    USER_PREF_UPLOAD_ATTACHED: Final[str] = "user-pref.fct.upload-attached.v1"
    USER_PREF_UPLOAD_DETACHED: Final[str] = "user-pref.fct.upload-detached.v1"

    # Preferences (user-pref-service) - Command topics
    USER_PREF_ATTACH_UPLOAD_REQUESTED: Final[str] = "user-pref.cmd.attach-upload.v1"
    USER_PREF_CREATE_REQUESTED: Final[str] = "user-pref.cmd.create-requested.v1"
    USER_PREF_DELETE_REQUESTED: Final[str] = "user-pref.cmd.delete-requested.v1"
    USER_PREF_DETACH_UPLOAD_REQUESTED: Final[str] = "user-pref.cmd.detach-upload.v1"
    USER_PREF_UPDATE_REQUESTED: Final[str] = "user-pref.cmd.update-requested.v1"
    USER_PREF_SETTINGS_UPDATE_REQUESTED: Final[str] = "user-pref.cmd.settings-update-requested.v1"
    USER_PREF_FEATURE_IMPORTANCE_UPDATE_REQUESTED: Final[str] = "user-pref.cmd.pref-importance-update-requested.v1"

    # User Pref Settings (user-pref-service) - CDC topics
    USER_PREF_SETTINGS_CREATED: Final[str] = "user-pref.cdc.settings-created.v1"
    USER_PREF_SETTINGS_UPDATED: Final[str] = "user-pref.cdc.settings-updated.v1"

    # Uploads (user-upload-service) - CDC topics
    USER_UPLOAD_CREATED: Final[str] = "user-upload.cdc.upload-created.v1"
    USER_UPLOAD_UPDATED: Final[str] = "user-upload.cdc.upload-updated.v1"
    USER_UPLOAD_DELETED: Final[str] = "user-upload.cdc.upload-deleted.v1"

    # Uploads (user-upload-service) - Command topics
    USER_UPLOAD_CREATE_REQUESTED: Final[str] = "user-upload.cmd.create-requested.v1"
    USER_UPLOAD_DELETE_REQUESTED: Final[str] = "user-upload.cmd.delete-requested.v1"

    USER_ENTITLEMENT_CHANGED: Final[str] = "user-entitlement.cdc.entitlement-changed.v1"

    # ════════════════════════════════════════════════════════════════════════════
    # JOB DOMAIN
    # ════════════════════════════════════════════════════════════════════════════

    JOB_INGEST_DISCOVERY_REQUESTED: Final[str] = "job-ingest.cmd.discovery-requested.v1"
    JOB_INGEST_LISTING_DISCOVERED: Final[str] = "job-ingest.fct.listing-discovered.v1"
    JOB_INGEST_ENRICHMENT_COMPLETED: Final[str] = "job-ingest.fct.enrichment-completed.v1"

    JOB_LISTING_ACCEPTED: Final[str] = "job-listing.fct.accepted.v1"
    JOB_LISTING_DUPLICATE_DETECTED: Final[str] = "job-listing.fct.duplicate-detected.v1"
    JOB_LISTING_CREATED: Final[str] = "job-listing.cdc.listing-created.v1"
    JOB_LISTING_UPDATED: Final[str] = "job-listing.cdc.listing-updated.v1"
    JOB_LISTING_DELETED: Final[str] = "job-listing.cdc.listing-deleted.v1"

    # Job Listing Commands (job-storage-service)
    JOB_LISTING_BACKFILL_REQUESTED: Final[str] = "job-listing.cmd.backfill-requested.v1"
    JOB_LISTING_SNAPSHOT_REFRESH_REQUESTED: Final[str] = "job-listing.cmd.snapshot-refresh-requested.v1"

    JOB_CORRELATION_EVALUATED: Final[str] = "job-correlation.cdc.correlation-evaluated.v1"
    JOB_CORRELATION_BATCH_COMPLETED: Final[str] = "job-correlation.fct.batch-completed.v1"
    JOB_CORRELATION_BACKFILL_LISTINGS: Final[str] = "job-correlation.sys.backfill-listings.v1"

    # Correlation feedback (job-correlation-evaluation-service) - Command topics
    JOB_CORRELATION_FEEDBACK_RECORDED: Final[str] = "job-correlation.cmd.feedback-recorded.v1"
    JOB_CORRELATION_TRAINING_EXPORT_REQUESTED: Final[str] = "job-correlation.cmd.training-export-requested.v1"

    # ════════════════════════════════════════════════════════════════════════════
    # FEEDBACK DOMAIN (Score feedback for L2R personalization)
    # ════════════════════════════════════════════════════════════════════════════

    # Score feedback (feedback domain) - Command topics
    FEEDBACK_SCORE_FEEDBACK_REQUESTED: Final[str] = "feedback.cmd.score-feedback-requested.v1"
    FEEDBACK_SCORE_ADJUSTMENT_REQUESTED: Final[str] = "feedback.cmd.score-adjustment-requested.v1"

    # Score feedback (feedback domain) - CDC topics

    JOB_QUERY_CREATED: Final[str] = "job-query.cdc.query-created.v1"
    JOB_QUERY_UPDATED: Final[str] = "job-query.cdc.query-updated.v1"
    JOB_QUERY_DELETED: Final[str] = "job-query.cdc.query-deleted.v1"

    # ════════════════════════════════════════════════════════════════════════════
    # DOC DOMAIN
    # ════════════════════════════════════════════════════════════════════════════

    # Template (doc-template-service) - CDC topics
    DOC_TEMPLATE_CREATED: Final[str] = "doc-template.cdc.template-created.v1"
    DOC_TEMPLATE_UPDATED: Final[str] = "doc-template.cdc.template-updated.v1"
    DOC_TEMPLATE_DELETED: Final[str] = "doc-template.cdc.template-deleted.v1"

    # Template (doc-template-service) - Fact topics
    DOC_TEMPLATE_RENDER_COMPLETED: Final[str] = "doc-template.fct.render-completed.v1"

    # Template (doc-template-service) - Command topics
    DOC_TEMPLATE_CREATE_REQUESTED: Final[str] = "doc-template.cmd.create-requested.v1"
    DOC_TEMPLATE_VERSION_ADD_REQUESTED: Final[str] = "doc-template.cmd.version-add-requested.v1"
    DOC_TEMPLATE_DELETE_REQUESTED: Final[str] = "doc-template.cmd.delete-requested.v1"
    DOC_TEMPLATE_RENDER_REQUESTED: Final[str] = "doc-template.cmd.render-requested.v1"

    # Content (doc-content-service) - Command topics
    DOC_CONTENT_GENERATION_REQUESTED: Final[str] = "doc-content.cmd.generation-requested.v1"

    # Content (doc-content-service) - Fact topics
    DOC_CONTENT_GENERATION_COMPLETED: Final[str] = "doc-content.fct.generation-completed.v1"
    DOC_CONTENT_GENERATION_FAILED: Final[str] = "doc-content.fct.generation-failed.v1"

    # Process (doc-process-service) - Command topics
    DOC_PROCESS_PROCESSING_REQUESTED: Final[str] = "doc-process.cmd.processing-requested.v1"

    # Process (doc-process-service) - Fact topic (broadcast, separate from callback)
    DOC_PROCESS_PROCESSING_COMPLETED: Final[str] = "doc-process.fct.processing-completed.v1"

    # ════════════════════════════════════════════════════════════════════════════
    # ML DOMAIN
    # ════════════════════════════════════════════════════════════════════════════

    ML_EMBEDDING_REQUESTED: Final[str] = "ml.cmd.embedding-requested.v1"
    ML_EMBEDDING_COMPLETED: Final[str] = "ml.fct.embedding-completed.v1"
    ML_EMBEDDING_COMPLETED_JSON: Final[str] = "ml.fct.embedding-completed-json.v1"

    # Embedding callback topics (service-specific)
    SKILL_EMBEDDING_CALLBACK: Final[str] = "skill.sys.embedding-callback.v1"
    JOB_CORRELATION_EMBEDDING_CALLBACK: Final[str] = "job-correlation.sys.embedding-callback.v1"
    USER_PREF_EMBEDDING_CALLBACK: Final[str] = "user-pref.sys.embedding-callback.v1"

    # Batch embedding command topic
    ML_BATCH_EMBEDDING_REQUESTED: Final[str] = "ml.cmd.batch-embedding-requested.v1"

    # Batch embedding callback (skill-graph-service specific)
    SKILL_BATCH_EMBEDDING_CALLBACK: Final[str] = "skill.sys.batch-embedding-callback.v1"

    # Normalization embedding callback (skill-graph-service internal)
    SKILL_NORMALIZATION_EMBEDDING_CALLBACK: Final[str] = "skill.sys.normalization-embedding-callback.v1"

    # Enrichment embedding callback (job-ingest-enrichment-service)
    JOB_INGEST_ENRICHMENT_EMBEDDING_CALLBACK: Final[str] = "job-ingest-enrichment.sys.embedding-callback.v1"

    ML_RERANK_REQUESTED: Final[str] = "ml.cmd.rerank-requested.v1"

    # Internal ML routing topics (ml-gateway-service → compute workers)
    ML_INTERNAL_K8S_COMPUTE: Final[str] = "ml.sys.kubernetes-compute.v1"
    ML_INTERNAL_MODAL_COMPUTE: Final[str] = "ml.sys.modal-compute.v1"

    # ════════════════════════════════════════════════════════════════════════════
    # NOTIFICATION DOMAIN
    # ════════════════════════════════════════════════════════════════════════════

    NOTIFICATION_SENT: Final[str] = "notification.fct.sent.v1"
    NOTIFICATION_FAILED: Final[str] = "notification.fct.failed.v1"

    # ════════════════════════════════════════════════════════════════════════════
    # SKILL DOMAIN
    # ════════════════════════════════════════════════════════════════════════════

    SKILL_MENTION_CREATED: Final[str] = "skill.fct.mention-created.v1"
    SKILL_NORMALIZATION_REQUESTED: Final[str] = "skill.cmd.normalization-requested.v1"

    # Alias learning and skill governance
    SKILL_ALIAS_LEARNED: Final[str] = "skill.fct.alias-learned.v1"
    SKILL_PROPOSED: Final[str] = "skill.cmd.skill-proposed.v1"
    SKILL_CREATED: Final[str] = "skill.fct.skill-created.v1"

    # Bootstrap lifecycle event (bootstrap-skill-graph job → skill-graph-service)
    SKILL_GRAPH_SEEDED: Final[str] = "skill.fct.skill-graph-seeded.v1"

    # Skill normalization callback topics (service-specific)
    JOB_INGEST_SKILL_CALLBACK: Final[str] = "job-ingest.sys.skill-callback.v1"
    USER_PREF_SKILL_CALLBACK: Final[str] = "user-pref.sys.skill-callback.v1"

    # ════════════════════════════════════════════════════════════════════════════
    # SYSTEM DOMAIN
    # ════════════════════════════════════════════════════════════════════════════

    SYS_SCHEDULE_TICK: Final[str] = "sys.fct.schedule-tick.v1"


__all__ = ["Topics"]
