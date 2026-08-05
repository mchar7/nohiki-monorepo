package ai.nohiki.kafka.connect.transforms;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.ByteBuffer;
import java.util.Map;
import org.apache.kafka.common.config.ConfigDef;
import org.apache.kafka.connect.data.Schema;
import org.apache.kafka.connect.data.SchemaBuilder;
import org.apache.kafka.connect.data.Struct;
import org.apache.kafka.connect.source.SourceRecord;
import org.jspecify.annotations.Nullable;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

@DisplayName("NohikiWalRouterSmt")
class NohikiWalRouterSmtTest {

  // -----------------------------------------------------------------------
  // Schema fixtures
  // -----------------------------------------------------------------------

  /** Canonical Debezium pgoutput logical-decoding message schema. */
  private static final Schema MESSAGE_SCHEMA =
      SchemaBuilder.struct()
          .name("io.debezium.connector.postgresql.Message")
          .field("prefix", Schema.STRING_SCHEMA)
          .field("content", Schema.OPTIONAL_BYTES_SCHEMA)
          .build();

  /** Canonical envelope schema for op=m events. */
  private static final Schema ENVELOPE_SCHEMA_MESSAGE =
      SchemaBuilder.struct()
          .field("op", Schema.STRING_SCHEMA)
          .field("message", MESSAGE_SCHEMA)
          .build();

  /** Envelope schema lacking a 'message' field (exercises safeGetStruct DataException path). */
  private static final Schema ENVELOPE_SCHEMA_NO_MESSAGE =
      SchemaBuilder.struct().field("op", Schema.STRING_SCHEMA).build();

  /** Envelope schema where 'message' is STRING (exercises safeGetStruct non-Struct branch). */
  private static final Schema ENVELOPE_SCHEMA_STRING_MESSAGE =
      SchemaBuilder.struct()
          .field("op", Schema.STRING_SCHEMA)
          .field("message", Schema.STRING_SCHEMA)
          .build();

  /** Envelope schema with INT 'op' (exercises safeGetString DataException on op). */
  private static final Schema ENVELOPE_SCHEMA_INT_OP =
      SchemaBuilder.struct()
          .field("op", Schema.INT32_SCHEMA)
          .field("message", MESSAGE_SCHEMA)
          .build();

  /** Message schema with prefix as BYTES (exercises safeGetString DataException on prefix). */
  private static final Schema MESSAGE_SCHEMA_BYTES_PREFIX =
      SchemaBuilder.struct()
          .field("prefix", Schema.BYTES_SCHEMA)
          .field("content", Schema.OPTIONAL_BYTES_SCHEMA)
          .build();

  private static final Schema ENVELOPE_SCHEMA_BYTES_PREFIX =
      SchemaBuilder.struct()
          .field("op", Schema.STRING_SCHEMA)
          .field("message", MESSAGE_SCHEMA_BYTES_PREFIX)
          .build();

  /** Message schema without 'content' field (exercises safeGetBytes DataException path). */
  private static final Schema MESSAGE_SCHEMA_NO_CONTENT =
      SchemaBuilder.struct().field("prefix", Schema.STRING_SCHEMA).build();

  private static final Schema ENVELOPE_SCHEMA_NO_CONTENT =
      SchemaBuilder.struct()
          .field("op", Schema.STRING_SCHEMA)
          .field("message", MESSAGE_SCHEMA_NO_CONTENT)
          .build();

  /** Message schema where content is STRING (exercises safeGetBytes non-bytes branch). */
  private static final Schema MESSAGE_SCHEMA_STRING_CONTENT =
      SchemaBuilder.struct()
          .field("prefix", Schema.STRING_SCHEMA)
          .field("content", Schema.STRING_SCHEMA)
          .build();

  private static final Schema ENVELOPE_SCHEMA_STRING_CONTENT =
      SchemaBuilder.struct()
          .field("op", Schema.STRING_SCHEMA)
          .field("message", MESSAGE_SCHEMA_STRING_CONTENT)
          .build();

  /** Row-event envelope (Debezium pgoutput create/update/delete/read). */
  private static final Schema ROW_AFTER_SCHEMA =
      SchemaBuilder.struct().field("id", Schema.STRING_SCHEMA).build();

  private static final Schema ENVELOPE_SCHEMA_ROW =
      SchemaBuilder.struct()
          .field("op", Schema.STRING_SCHEMA)
          .field("after", ROW_AFTER_SCHEMA)
          .build();

  // -----------------------------------------------------------------------

  private NohikiWalRouterSmt<SourceRecord> smt;

  @BeforeEach
  void setUp() {
    smt = new NohikiWalRouterSmt<>();
    smt.configure(Map.of());
  }

  @AfterEach
  void tearDown() {
    smt.close();
  }

  // =======================================================================
  // Lifecycle
  // =======================================================================

  @Nested
  @DisplayName("Lifecycle")
  class Lifecycle {

    @Test
    @DisplayName("config() returns a non-null, empty ConfigDef")
    void configReturnsEmptyConfigDef() {
      ConfigDef def = smt.config();
      assertThat(def).isNotNull();
      assertThat(def.configKeys()).isEmpty();
    }

    @Test
    @DisplayName("version() reports the loaded module version")
    void versionReportsModuleVersion() {
      assertThat(smt.version()).isEqualTo("0.1.0");
    }

    @Test
    @DisplayName("configure() accepts empty props and leaves the SMT functional")
    void configureEmpty() {
      smt.configure(Map.of());
      SourceRecord out =
          smt.apply(messageRecord("{\"topic\":\"t\",\"aggregate_id\":\"a\"}", new byte[] {1}));
      assertThat(out).isNotNull();
      assertThat(out.topic()).isEqualTo("t");
    }

    @Test
    @DisplayName("configure() tolerates unknown properties (they are ignored)")
    void configureIgnoresUnknownProps() {
      smt.configure(Map.of("unknown.prop", "value", "another", 42));
      SourceRecord out =
          smt.apply(messageRecord("{\"topic\":\"t\",\"aggregate_id\":\"a\"}", new byte[] {1}));
      assertThat(out).isNotNull();
      assertThat(out.topic()).isEqualTo("t");
    }

    @Test
    @DisplayName("close() is idempotent and does not throw when called multiple times")
    void closeIsIdempotent() {
      smt.close();
      smt.close();
      smt.close();
      // @AfterEach will close a fourth time; all calls must be no-op safe.
    }
  }

  // =======================================================================
  // Successful routing
  // =======================================================================

  @Nested
  @DisplayName("Routing")
  class Routing {

    @Test
    @DisplayName("Full envelope routes to target topic with key, value, and all four headers")
    void fullEnvelope() {
      byte[] payload = new byte[] {1, 2, 3, 4, 5};
      String prefix =
          """
                    {
                      "id": "01970000-0000-7000-8000-000000000001",
                      "topic": "skill.fct.skill-created.v1",
                      "aggregate_id": "01970000-0000-7000-8000-00000000a001",
                      "aggregate_type": "skill",
                      "correlation_id": "01970000-0000-7000-8000-00000000cfff",
                      "traceparent": "00-11111111111111111111111111111111-2222222222222222-01"
                    }""";

      SourceRecord out = smt.apply(messageRecord(prefix, payload));

      assertThat(out).isNotNull();
      assertThat(out.topic()).isEqualTo("skill.fct.skill-created.v1");
      assertThat(out.keySchema()).isEqualTo(Schema.OPTIONAL_STRING_SCHEMA);
      assertThat(out.key()).isEqualTo("01970000-0000-7000-8000-00000000a001");
      assertThat(out.valueSchema()).isEqualTo(Schema.OPTIONAL_BYTES_SCHEMA);
      assertThat((byte[]) out.value()).containsExactly(payload);
      assertThat(headerValue(out, "aggregatetype")).isEqualTo("skill");
      assertThat(headerValue(out, "tracingspancontext"))
          .isEqualTo("01970000-0000-7000-8000-00000000cfff");
      assertThat(headerValue(out, "id")).isEqualTo("01970000-0000-7000-8000-000000000001");
      assertThat(headerValue(out, "traceparent"))
          .isEqualTo("00-11111111111111111111111111111111-2222222222222222-01");
      assertThat(headerCount(out)).isEqualTo(4);
    }

    @Test
    @DisplayName("Minimal envelope (topic + aggregate_id only) routes with no optional headers")
    void minimalEnvelope() {
      byte[] payload = new byte[] {9};
      SourceRecord out =
          smt.apply(messageRecord("{\"topic\":\"t\",\"aggregate_id\":\"a\"}", payload));

      assertThat(out).isNotNull();
      assertThat(out.topic()).isEqualTo("t");
      assertThat(out.key()).isEqualTo("a");
      assertThat((byte[]) out.value()).containsExactly(payload);
      assertThat(headerCount(out)).isZero();
    }

    @Test
    @DisplayName("Opaque content with a malformed frame length prefix is preserved byte-for-byte")
    void malformedFrameLengthPrefixIsOpaque() {
      byte[] payload = new byte[] {(byte) 0xff, (byte) 0xff, (byte) 0xff, (byte) 0xff, 1, 2, 3};

      SourceRecord out =
          smt.apply(messageRecord("{\"topic\":\"t\",\"aggregate_id\":\"a\"}", payload));

      assertThat(out).isNotNull();
      assertThat((byte[]) out.value()).containsExactly(payload);
    }

    @Test
    @DisplayName("Opaque content with a truncated framed payload is preserved byte-for-byte")
    void truncatedFramedPayloadIsOpaque() {
      byte[] payload = new byte[] {0, 0, 0, 5, '{', '}'};

      SourceRecord out =
          smt.apply(messageRecord("{\"topic\":\"t\",\"aggregate_id\":\"a\"}", payload));

      assertThat(out).isNotNull();
      assertThat((byte[]) out.value()).containsExactly(payload);
    }

    @Test
    @DisplayName("ByteBuffer content is decoded to a byte[] value")
    void byteBufferContent() {
      byte[] payload = new byte[] {1, 2, 3};
      Struct message =
          new Struct(MESSAGE_SCHEMA)
              .put("prefix", "{\"topic\":\"t\",\"aggregate_id\":\"a\"}")
              .put("content", ByteBuffer.wrap(payload));
      SourceRecord input =
          buildRecord(ENVELOPE_SCHEMA_MESSAGE, envelopeM(message, ENVELOPE_SCHEMA_MESSAGE));

      SourceRecord out = smt.apply(input);

      assertThat(out).isNotNull();
      assertThat((byte[]) out.value()).containsExactly(payload);
    }

    @Test
    @DisplayName("ByteBuffer with non-zero position is fully read (duplicate() is used)")
    void byteBufferWithOffset() {
      byte[] backing = new byte[] {99, 99, 1, 2, 3};
      ByteBuffer buf = ByteBuffer.wrap(backing);
      buf.position(2);
      Struct message =
          new Struct(MESSAGE_SCHEMA)
              .put("prefix", "{\"topic\":\"t\",\"aggregate_id\":\"a\"}")
              .put("content", buf);
      SourceRecord input =
          buildRecord(ENVELOPE_SCHEMA_MESSAGE, envelopeM(message, ENVELOPE_SCHEMA_MESSAGE));

      SourceRecord out = smt.apply(input);
      assertThat(out).isNotNull();

      assertThat((byte[]) out.value()).containsExactly(1, 2, 3);
      assertThat(buf.position()).as("original buffer position must be unchanged").isEqualTo(2);
    }

    @Test
    @DisplayName("Preserves source-record timestamp on the routed record")
    void preservesTimestamp() {
      Struct message =
          new Struct(MESSAGE_SCHEMA)
              .put("prefix", "{\"topic\":\"t\",\"aggregate_id\":\"a\"}")
              .put("content", new byte[] {1});
      Struct envelope = envelopeM(message, ENVELOPE_SCHEMA_MESSAGE);
      SourceRecord input =
          new SourceRecord(
              null,
              null,
              "src",
              null,
              null,
              null,
              ENVELOPE_SCHEMA_MESSAGE,
              envelope,
              1_234_567_890L);

      SourceRecord out = smt.apply(input);

      assertThat(out).isNotNull();
      assertThat(out.timestamp()).isEqualTo(1_234_567_890L);
    }

    @Test
    @DisplayName("Routes with null key when aggregate_id is absent from the envelope")
    void nullKeyWhenAggregateIdAbsent() {
      SourceRecord out = smt.apply(messageRecord("{\"topic\":\"t\"}", new byte[] {1}));

      assertThat(out).isNotNull();
      assertThat(out.keySchema()).isEqualTo(Schema.OPTIONAL_STRING_SCHEMA);
      assertThat(out.key()).isNull();
    }

    @Test
    @DisplayName("Routes with null key when aggregate_id is explicit JSON null")
    void nullKeyWhenAggregateIdExplicitNull() {
      SourceRecord out =
          smt.apply(messageRecord("{\"topic\":\"t\",\"aggregate_id\":null}", new byte[] {1}));

      assertThat(out).isNotNull();
      assertThat(out.key()).isNull();
    }

    @Test
    @DisplayName("Omits all optional headers when their envelope fields are explicit JSON null")
    void omitsHeadersOnExplicitNull() {
      String prefix =
          """
                    {"topic":"t","aggregate_id":"a",
                     "id":null,"aggregate_type":null,
                     "correlation_id":null,"traceparent":null}""";

      SourceRecord out = smt.apply(messageRecord(prefix, new byte[] {1}));

      assertThat(out).isNotNull();
      assertThat(headerCount(out)).isZero();
    }

    @Test
    @DisplayName("Routes with null value when content field is absent from the message schema")
    void nullValueWhenContentFieldAbsent() {
      Struct message =
          new Struct(MESSAGE_SCHEMA_NO_CONTENT)
              .put("prefix", "{\"topic\":\"t\",\"aggregate_id\":\"a\"}");
      SourceRecord input =
          buildRecord(ENVELOPE_SCHEMA_NO_CONTENT, envelopeM(message, ENVELOPE_SCHEMA_NO_CONTENT));

      SourceRecord out = smt.apply(input);

      assertThat(out).isNotNull();
      assertThat(out.value()).isNull();
      assertThat(out.valueSchema()).isEqualTo(Schema.OPTIONAL_BYTES_SCHEMA);
    }

    @Test
    @DisplayName(
        "Routes with null value when content is of an unsupported type (String, not bytes)")
    void nullValueWhenContentUnsupportedType() {
      Struct message =
          new Struct(MESSAGE_SCHEMA_STRING_CONTENT)
              .put("prefix", "{\"topic\":\"t\",\"aggregate_id\":\"a\"}")
              .put("content", "not-bytes");
      SourceRecord input =
          buildRecord(
              ENVELOPE_SCHEMA_STRING_CONTENT, envelopeM(message, ENVELOPE_SCHEMA_STRING_CONTENT));

      SourceRecord out = smt.apply(input);

      assertThat(out).isNotNull();
      assertThat(out.value()).isNull();
    }

    @Test
    @DisplayName(
        "Routes with null value when content is explicitly null (OPTIONAL_BYTES allows this)")
    void nullValueWhenContentExplicitlyNull() {
      Struct message =
          new Struct(MESSAGE_SCHEMA).put("prefix", "{\"topic\":\"t\",\"aggregate_id\":\"a\"}");
      SourceRecord input =
          buildRecord(ENVELOPE_SCHEMA_MESSAGE, envelopeM(message, ENVELOPE_SCHEMA_MESSAGE));

      SourceRecord out = smt.apply(input);

      assertThat(out).isNotNull();
      assertThat(out.value()).isNull();
    }
  }

  // =======================================================================
  // Dropping (return null on malformed input)
  // =======================================================================

  @Nested
  @DisplayName("Dropping malformed message events")
  class Dropping {

    @Test
    @DisplayName("Drops event when the 'message' struct is null on an optional-typed field")
    void dropsWhenMessageIsNull() {
      // Optional-typed message field permitted to be null.
      Schema optionalMessageEnvelope =
          SchemaBuilder.struct()
              .field("op", Schema.STRING_SCHEMA)
              .field(
                  "message",
                  SchemaBuilder.struct()
                      .name("io.debezium.connector.postgresql.Message")
                      .field("prefix", Schema.OPTIONAL_STRING_SCHEMA)
                      .field("content", Schema.OPTIONAL_BYTES_SCHEMA)
                      .optional()
                      .build())
              .build();
      Struct envelope = new Struct(optionalMessageEnvelope).put("op", "m");

      SourceRecord input = buildRecord(optionalMessageEnvelope, envelope);

      assertThat(smt.apply(input)).isNull();
    }

    @Test
    @DisplayName("Drops event when envelope schema has no 'message' field at all")
    void dropsWhenMessageFieldAbsent() {
      Struct envelope = new Struct(ENVELOPE_SCHEMA_NO_MESSAGE).put("op", "m");
      SourceRecord input = buildRecord(ENVELOPE_SCHEMA_NO_MESSAGE, envelope);

      assertThat(smt.apply(input)).isNull();
    }

    @Test
    @DisplayName(
        "Drops event when 'message' field is present but is not a Struct (wrong schema type)")
    void dropsWhenMessageIsNotAStruct() {
      Struct envelope =
          new Struct(ENVELOPE_SCHEMA_STRING_MESSAGE).put("op", "m").put("message", "not-a-struct");
      SourceRecord input = buildRecord(ENVELOPE_SCHEMA_STRING_MESSAGE, envelope);

      assertThat(smt.apply(input)).isNull();
    }

    @Test
    @DisplayName("Drops event when prefix is an empty string")
    void dropsEmptyPrefix() {
      assertThat(smt.apply(messageRecord("", new byte[] {0}))).isNull();
    }

    @Test
    @DisplayName("Drops event when prefix schema is BYTES rather than STRING")
    void dropsWhenPrefixFieldWrongType() {
      Struct message =
          new Struct(MESSAGE_SCHEMA_BYTES_PREFIX)
              .put("prefix", new byte[] {1, 2, 3})
              .put("content", new byte[] {0});
      Struct envelope = envelopeM(message, ENVELOPE_SCHEMA_BYTES_PREFIX);
      SourceRecord input = buildRecord(ENVELOPE_SCHEMA_BYTES_PREFIX, envelope);

      assertThat(smt.apply(input)).isNull();
    }

    @Test
    @DisplayName("Drops Debezium internal signal messages (prefix starts with 'dbz-')")
    void dropsDebeziumSignalMessages() {
      assertThat(smt.apply(messageRecord("dbz-signal-watermark", new byte[] {0}))).isNull();
    }

    @Test
    @DisplayName("Drops a message whose prefix is not valid JSON")
    void dropsUnparseablePrefix() {
      assertThat(smt.apply(messageRecord("not-json", new byte[] {0}))).isNull();
    }

    @Test
    @DisplayName("Drops when the prefix JSON envelope is missing the required 'topic' field")
    void dropsWhenTopicMissing() {
      assertThat(smt.apply(messageRecord("{\"aggregate_id\":\"a\"}", new byte[] {0}))).isNull();
    }

    @Test
    @DisplayName("Drops when the prefix envelope has an empty 'topic'")
    void dropsWhenTopicEmpty() {
      assertThat(
              smt.apply(messageRecord("{\"topic\":\"\",\"aggregate_id\":\"a\"}", new byte[] {0})))
          .isNull();
    }

    @Test
    @DisplayName("Drops when the prefix envelope has an explicit JSON null 'topic'")
    void dropsWhenTopicExplicitlyNull() {
      assertThat(
              smt.apply(messageRecord("{\"topic\":null,\"aggregate_id\":\"a\"}", new byte[] {0})))
          .isNull();
    }
  }

  // =======================================================================
  // Dropping (dedicated WAL connector must never leak publication row records)
  // =======================================================================

  @Nested
  @DisplayName("Dropping non-message records")
  class NonMessageDropping {

    @ParameterizedTest(name = "op={0} row event is dropped")
    @ValueSource(strings = {"c", "u", "d", "r", "t"})
    void dropsRowEvents(String op) {
      Struct after = new Struct(ROW_AFTER_SCHEMA).put("id", "row-1");
      Struct envelope = new Struct(ENVELOPE_SCHEMA_ROW).put("op", op).put("after", after);
      SourceRecord input = buildRecord(ENVELOPE_SCHEMA_ROW, envelope);

      assertThat(smt.apply(input)).isNull();
    }

    @Test
    @DisplayName("Drops when 'op' field is of unexpected type (INT32, not STRING)")
    void dropsWhenOpFieldWrongType() {
      Struct message =
          new Struct(MESSAGE_SCHEMA)
              .put("prefix", "{\"topic\":\"t\",\"aggregate_id\":\"a\"}")
              .put("content", new byte[] {1});
      Struct envelope = new Struct(ENVELOPE_SCHEMA_INT_OP).put("op", 1).put("message", message);
      SourceRecord input = buildRecord(ENVELOPE_SCHEMA_INT_OP, envelope);

      assertThat(smt.apply(input)).isNull();
    }

    @Test
    @DisplayName("Drops a record whose value is null")
    void dropsNullValue() {
      SourceRecord input = new SourceRecord(null, null, "t", null, null, null, null, null);

      assertThat(smt.apply(input)).isNull();
    }

    @Test
    @DisplayName("Drops a record whose value is not a Struct (e.g., String)")
    void dropsNonStructValue() {
      SourceRecord input =
          new SourceRecord(null, null, "t", null, null, null, Schema.STRING_SCHEMA, "not-a-struct");

      assertThat(smt.apply(input)).isNull();
    }

    @Test
    @DisplayName("Returns null when the entire record is null")
    void returnsNullForNullRecord() {
      assertThat(smt.apply(null)).isNull();
    }
  }

  // -----------------------------------------------------------------------
  // Helpers
  // -----------------------------------------------------------------------

  /** Build a standard op=m SourceRecord with the canonical message schema. */
  private static SourceRecord messageRecord(String prefix, byte[] content) {
    Struct message = new Struct(MESSAGE_SCHEMA).put("prefix", prefix).put("content", content);
    return buildRecord(ENVELOPE_SCHEMA_MESSAGE, envelopeM(message, ENVELOPE_SCHEMA_MESSAGE));
  }

  /** Build an envelope struct for op=m with the given message and envelope schema. */
  private static Struct envelopeM(Object message, Schema envelopeSchema) {
    return new Struct(envelopeSchema).put("op", "m").put("message", message);
  }

  private static SourceRecord buildRecord(Schema valueSchema, Struct value) {
    return new SourceRecord(null, null, "source.message", null, null, null, valueSchema, value);
  }

  private static @Nullable String headerValue(SourceRecord record, String name) {
    var header = record.headers().lastWithName(name);
    return header == null ? null : (String) header.value();
  }

  private static int headerCount(SourceRecord record) {
    int n = 0;
    var iterator = record.headers().iterator();
    while (iterator.hasNext()) {
      iterator.next();
      n++;
    }
    return n;
  }
}
