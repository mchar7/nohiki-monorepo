#!/bin/bash
# Kafka topic initialization script
# Pre-creates all application topics before services start.
#
# This prevents race conditions where consumers subscribe to topics
# that don't exist yet, causing aiokafka to silently fail to assign
# partitions until the topic is created by a producer.
#
# Uses the Kafka AdminClient via a single JVM process for efficiency.

set -euo pipefail

BOOTSTRAP_SERVER="${BOOTSTRAP_SERVER:-nohiki-cp-kafka:29092}"
PARTITIONS="${PARTITIONS:-3}"
REPLICATION="${REPLICATION:-1}"

TOPICS="
user-auth.cdc.account-deleted.v1
user-auth.cdc.account-updated.v1
user-auth.fct.activity.v1
user-auth.fct.access-token-revoked.v1
user-pref.cdc.pref-created.v1
user-pref.cdc.pref-updated.v1
user-pref.cdc.pref-deleted.v1
user-pref.fct.upload-attached.v1
user-pref.fct.upload-detached.v1
user-pref.cmd.attach-upload.v1
user-pref.cmd.create-requested.v1
user-pref.cmd.delete-requested.v1
user-pref.cmd.detach-upload.v1
user-pref.cmd.update-requested.v1
user-pref.cmd.settings-update-requested.v1
user-pref.cmd.pref-importance-update-requested.v1
user-pref.cdc.settings-created.v1
user-pref.cdc.settings-updated.v1
user-pref.sys.embedding-callback.v1
user-pref.sys.skill-callback.v1
user-upload.cdc.upload-created.v1
user-upload.cdc.upload-updated.v1
user-upload.cdc.upload-deleted.v1
user-upload.cmd.create-requested.v1
user-upload.cmd.delete-requested.v1
user-entitlement.cdc.entitlement-changed.v1
job-ingest.cmd.discovery-requested.v1
job-ingest.fct.listing-discovered.v1
job-ingest.fct.enrichment-completed.v1
job-ingest.sys.embedding-callback.v1
job-ingest.sys.skill-callback.v1
job-listing.fct.accepted.v1
job-listing.fct.duplicate-detected.v1
job-listing.cdc.listing-created.v1
job-listing.cdc.listing-updated.v1
job-listing.cdc.listing-deleted.v1
job-listing.cmd.backfill-requested.v1
job-listing.cmd.snapshot-refresh-requested.v1
job-correlation.cdc.correlation-evaluated.v1
job-correlation.fct.batch-completed.v1
job-correlation.sys.llm-completed.v1
job-correlation.sys.backfill-listings.v1
job-correlation.cmd.feedback-recorded.v1
job-correlation.cmd.training-export-requested.v1
job-correlation.fct.training-data-exported.v1
job-correlation.sys.embedding-callback.v1
job-query.cdc.query-created.v1
job-query.cdc.query-updated.v1
job-query.cdc.query-deleted.v1
feedback.cmd.score-feedback-requested.v1
feedback.cmd.score-adjustment-requested.v1
feedback.cdc.asymmetric-feedback-created.v1
feedback.cdc.manual-adjustment-created.v1
doc-template.cdc.template-created.v1
doc-template.cdc.template-updated.v1
doc-template.cdc.template-deleted.v1
doc-template.fct.render-completed.v1
doc-template.cmd.create-requested.v1
doc-template.cmd.version-add-requested.v1
doc-template.cmd.delete-requested.v1
doc-template.cmd.render-requested.v1
doc-content.cmd.generation-requested.v1
doc-content.fct.generation-completed.v1
doc-content.fct.generation-failed.v1
doc-process.cmd.processing-requested.v1
doc-process.fct.processing-completed.v1
doc-process.fct.processing-failed.v1
ml.cmd.embedding-requested.v1
ml.fct.embedding-completed.v1
ml.fct.embedding-completed-json.v1
ml.fct.embedding-failed.v1
ml.cmd.embedding-refresh-requested.v1
ml.cmd.rerank-requested.v1
ml.fct.rerank-completed.v1
ml.sys.kubernetes-compute.v1
ml.sys.kubernetes-batch-compute.v1
ml.sys.modal-compute.v1
ml.dlq.qdrant-sink-errors.v1
ml.cmd.batch-embedding-requested.v1
skill.fct.mention-created.v1
skill.cmd.normalization-requested.v1
skill.fct.alias-learned.v1
skill.cmd.skill-proposed.v1
skill.fct.skill-created.v1
skill.fct.skill-graph-seeded.v1
skill.fct.relationship-created.v1
skill.sys.embedding-callback.v1
skill.sys.batch-embedding-callback.v1
skill.sys.normalization-embedding-callback.v1
job-ingest-enrichment.sys.embedding-callback.v1
notification.fct.sent.v1
notification.fct.failed.v1
sys.fct.schedule-tick.v1
sys.fct.inactivity-tick.v1
"

# Snapshot existing topics once (single JVM call).
if ! EXISTING=$(kafka-topics --bootstrap-server "${BOOTSTRAP_SERVER}" --list 2>/dev/null); then
  echo "ERROR: unable to list Kafka topics at ${BOOTSTRAP_SERVER}" >&2
  exit 1
fi

# Create any missing topic. --if-not-exists makes concurrent creation race-safe:
# a topic another process creates between the list and the create is not an error.
failures=0
for topic in ${TOPICS}; do
  if grep -Fqx -- "${topic}" <<<"${EXISTING}"; then
    continue
  fi
  if ! kafka-topics --bootstrap-server "${BOOTSTRAP_SERVER}" \
      --create --if-not-exists \
      --topic "${topic}" \
      --partitions "${PARTITIONS}" \
      --replication-factor "${REPLICATION}" > /dev/null 2>&1; then
    echo "ERROR: failed to create topic ${topic}" >&2
    failures=$((failures + 1))
  fi
done

# Re-list once and derive truthful counts from the actual cluster state, so a
# topic created concurrently counts as skipped rather than created.
if ! FINAL=$(kafka-topics --bootstrap-server "${BOOTSTRAP_SERVER}" --list 2>/dev/null); then
  echo "ERROR: unable to re-list Kafka topics at ${BOOTSTRAP_SERVER}" >&2
  exit 1
fi

created=0
skipped=0
for topic in ${TOPICS}; do
  if grep -Fqx -- "${topic}" <<<"${EXISTING}"; then
    skipped=$((skipped + 1))
  elif grep -Fqx -- "${topic}" <<<"${FINAL}"; then
    created=$((created + 1))
  else
    echo "ERROR: topic ${topic} absent after creation" >&2
    failures=$((failures + 1))
  fi
done

total=$(printf '%s\n' "${FINAL}" | grep -cvE '^(_|$)' || true)
echo "Kafka init complete: created=${created} skipped=${skipped} total=${total}"

if [ "${failures}" -ne 0 ]; then
  echo "ERROR: ${failures} topic operation(s) failed" >&2
  exit 1
fi
