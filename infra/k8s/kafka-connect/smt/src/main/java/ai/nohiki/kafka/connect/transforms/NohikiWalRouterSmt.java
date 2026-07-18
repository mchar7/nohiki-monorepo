package ai.nohiki.kafka.connect.transforms;

import com.fasterxml.jackson.jr.ob.JSON;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.util.Map;
import org.apache.kafka.common.config.ConfigDef;
import org.apache.kafka.connect.connector.ConnectRecord;
import org.apache.kafka.connect.data.Schema;
import org.apache.kafka.connect.data.Struct;
import org.apache.kafka.connect.errors.DataException;
import org.apache.kafka.connect.header.ConnectHeaders;
import org.apache.kafka.connect.transforms.Transformation;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Kafka Connect SMT that routes Debezium pgoutput logical-decoding message events
 * (op=m, emitted via {@code pg_logical_emit_message}) to their target Kafka topic.
 *
 * <p>The source service encodes routing metadata in the WAL message's {@code prefix}
 * as a compact JSON envelope, and writes the protobuf payload as the {@code content}
 * (bytea). This SMT parses the prefix, rewrites the record with the target topic,
 * key, and headers, and passes the raw content bytes through as the Kafka value.
 *
 * <p>This transform is intended for a dedicated WAL-message connector. Every record
 * that is not a valid {@code op=m} logical-decoding message is dropped so rows from
 * the connector's minimal publication can never leak to Kafka.
 *
 * <p>Prefix envelope schema (JSON):
 * <pre>
 * {
 *   "id":             "&lt;event uuid&gt;",
 *   "topic":          "&lt;target Kafka topic&gt;",        (required)
 *   "aggregate_id":   "&lt;aggregate uuid&gt;",             (becomes Kafka key)
 *   "aggregate_type": "&lt;string&gt;",                     (header: aggregatetype)
 *   "correlation_id": "&lt;uuid or null&gt;",               (header: tracingspancontext)
 *   "traceparent":    "&lt;W3C traceparent, optional&gt;"   (header: traceparent)
 * }
 * </pre>
 *
 * <p>Kafka record produced (byte-parity with the current outbox EventRouter):
 * <ul>
 *   <li>Topic: {@code prefix.topic}
 *   <li>Key: {@code prefix.aggregate_id} as {@link Schema#OPTIONAL_STRING_SCHEMA}
 *   <li>Value: {@code message.content} as {@link Schema#OPTIONAL_BYTES_SCHEMA}
 *   <li>Headers: {@code aggregatetype}, {@code tracingspancontext}, {@code id},
 *       {@code traceparent} (optional fields omitted when absent)
 * </ul>
 */
public class NohikiWalRouterSmt<R extends ConnectRecord<R>> implements Transformation<R> {

    private static final Logger log = LoggerFactory.getLogger(NohikiWalRouterSmt.class);

    /** Debezium reserves the "dbz-" prefix namespace for incremental-snapshot signals. */
    private static final String DEBEZIUM_SIGNAL_PREFIX = "dbz-";

    private static final String FIELD_OP = "op";
    private static final String FIELD_MESSAGE = "message";
    private static final String FIELD_MESSAGE_PREFIX = "prefix";
    private static final String FIELD_MESSAGE_CONTENT = "content";

    private static final String OP_MESSAGE = "m";

    private static final String ENV_TOPIC = "topic";
    private static final String ENV_AGGREGATE_ID = "aggregate_id";
    private static final String ENV_AGGREGATE_TYPE = "aggregate_type";
    private static final String ENV_CORRELATION_ID = "correlation_id";
    private static final String ENV_TRACEPARENT = "traceparent";
    private static final String ENV_EVENT_ID = "id";

    private static final String HEADER_AGGREGATE_TYPE = "aggregatetype";
    private static final String HEADER_TRACING_CONTEXT = "tracingspancontext";
    private static final String HEADER_EVENT_ID = "id";
    private static final String HEADER_TRACEPARENT = "traceparent";

    @Override
    public ConfigDef config() {
        return new ConfigDef();
    }

    @Override
    public void configure(Map<String, ?> props) {
        // No configuration knobs: all routing metadata lives in the WAL message prefix.
    }

    @Override
    public R apply(R record) {
        if (record == null || !(record.value() instanceof Struct value)) {
            return null;
        }

        String op = safeGetString(value, FIELD_OP);
        if (!OP_MESSAGE.equals(op)) {
            return null;
        }

        Struct message = safeGetStruct(value, FIELD_MESSAGE);
        if (message == null) {
            log.debug("Dropping message event with missing 'message' struct");
            return null;
        }

        String prefix = safeGetString(message, FIELD_MESSAGE_PREFIX);
        if (prefix == null || prefix.isEmpty()) {
            log.debug("Dropping message event with missing/empty prefix");
            return null;
        }

        if (prefix.startsWith(DEBEZIUM_SIGNAL_PREFIX)) {
            log.debug("Skipping Debezium internal signal message: prefix={}", prefix);
            return null;
        }

        Map<String, Object> envelope;
        try {
            envelope = JSON.std.mapFrom(prefix);
        } catch (IOException e) {
            log.warn("Dropping WAL message with unparseable prefix JSON: {}", prefix, e);
            return null;
        }

        String topic = textOrNull(envelope, ENV_TOPIC);
        if (topic == null || topic.isEmpty()) {
            log.warn("Dropping WAL message: prefix envelope missing required 'topic'. prefix={}", prefix);
            return null;
        }

        String aggregateId = textOrNull(envelope, ENV_AGGREGATE_ID);
        String aggregateType = textOrNull(envelope, ENV_AGGREGATE_TYPE);
        String correlationId = textOrNull(envelope, ENV_CORRELATION_ID);
        String traceparent = textOrNull(envelope, ENV_TRACEPARENT);
        String eventId = textOrNull(envelope, ENV_EVENT_ID);

        byte[] content = safeGetBytes(message, FIELD_MESSAGE_CONTENT);

        ConnectHeaders headers = new ConnectHeaders();
        if (aggregateType != null) {
            headers.addString(HEADER_AGGREGATE_TYPE, aggregateType);
        }
        if (correlationId != null) {
            headers.addString(HEADER_TRACING_CONTEXT, correlationId);
        }
        if (eventId != null) {
            headers.addString(HEADER_EVENT_ID, eventId);
        }
        if (traceparent != null) {
            headers.addString(HEADER_TRACEPARENT, traceparent);
        }

        return record.newRecord(
                topic,
                null,
                Schema.OPTIONAL_STRING_SCHEMA,
                aggregateId,
                Schema.OPTIONAL_BYTES_SCHEMA,
                content,
                record.timestamp(),
                headers);
    }

    @Override
    public void close() {
        // No resources to release.
    }

    private static String safeGetString(Struct struct, String field) {
        try {
            return struct.getString(field);
        } catch (DataException e) {
            return null;
        }
    }

    private static Struct safeGetStruct(Struct struct, String field) {
        try {
            return struct.get(field) instanceof Struct s ? s : null;
        } catch (DataException e) {
            return null;
        }
    }

    private static byte[] safeGetBytes(Struct struct, String field) {
        try {
            return switch (struct.get(field)) {
                case byte[] bytes -> bytes;
                case ByteBuffer buffer -> {
                    ByteBuffer dup = buffer.duplicate();
                    byte[] bytes = new byte[dup.remaining()];
                    dup.get(bytes);
                    yield bytes;
                }
                case null, default -> null;
            };
        } catch (DataException e) {
            return null;
        }
    }

    /**
     * Returns the string form of an envelope field, or {@code null} when the field
     * is absent, explicitly JSON null, or cannot be represented as text.
     */
    private static String textOrNull(Map<String, Object> envelope, String field) {
        Object value = envelope.get(field);
        return value == null ? null : value.toString();
    }
}
