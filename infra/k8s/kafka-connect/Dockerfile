# =============================================================================
# NOHIKI KAFKA CONNECT - CUSTOM IMAGE
# =============================================================================
#
# Base: Debezium Connect (includes PostgreSQL CDC connector)
# Added: Qdrant Sink Connector, Nohiki WAL Router SMT
#
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: Build the Nohiki WAL Router SMT (JAR is platform-agnostic bytecode,
# so the Alpine builder has no effect on runtime compatibility with the Fedora
# 41-based Debezium Connect image).
# -----------------------------------------------------------------------------
FROM gradle:9.6.1-jdk25-alpine@sha256:4d50266538c871adbcd8ece20d61d10e42b6c8c7dec1f10498d9508d45759c35 AS smt-builder
WORKDIR /build
COPY smt/ /build/
RUN gradle --no-daemon --console=plain test shadowJar

# -----------------------------------------------------------------------------
# Stage 2: Kafka Connect runtime with CDC + sink + custom SMT plugins
# -----------------------------------------------------------------------------
FROM quay.io/debezium/connect:3.6.0.Final@sha256:698f0559e667a242f962221079e75917b2b7a3ad4de62661e977628da0e33b45 AS compose

# Connector registration checks PostgreSQL replication slots with psql.
USER 0
# DL3041 does not recognize microdnf's globbed major-line selector.
# hadolint ignore=DL3041
RUN microdnf install -y 'postgresql-16.*' && \
    microdnf clean all

# Nohiki consumes PostgreSQL CDC only. Removing unused connector plugins reduces
# runtime classpath, image size, and vulnerability exposure.
RUN for connector in /kafka/connect/debezium-connector-*; do \
      if [ "${connector}" != "/kafka/connect/debezium-connector-postgres" ]; then \
        rm -rf "${connector}"; \
      fi; \
    done

# Debezium 3.6.0 predates fixes in its Kafka runtime dependencies. Replace each
# active family as a unit; omit JLine and Plexus because the distributed worker
# does not run Kafka's console or build tooling.
RUN set -eu; \
    fetch_jar() { \
      artifact="$1"; checksum="$2"; destination="$3"; \
      curl --fail --show-error --silent --location \
        "https://repo1.maven.org/maven2/${artifact}" --output "${destination}.new"; \
      printf '%s  %s\n' "${checksum}" "${destination}.new" > "${destination}.sha256"; \
      sha256sum --check --strict "${destination}.sha256"; \
      rm "${destination}.sha256"; \
      mv "${destination}.new" "${destination}"; \
    }; \
    rm -f /kafka/libs/jackson-*.jar /kafka/libs/jetty-*.jar \
      /kafka/libs/jline-*.jar /kafka/libs/plexus-utils-*.jar \
      /kafka/external_libs/apicurio/netty-*.jar \
      /kafka/connect/debezium-connector-postgres/postgresql-*.jar; \
    fetch_jar io/netty/netty-buffer/4.1.135.Final/netty-buffer-4.1.135.Final.jar \
      2a194f99fc93d07c4d442d04ac71bd2dc56d3188cd0e4270cdc2a953d1956bf9 \
      /kafka/external_libs/apicurio/netty-buffer-4.1.135.Final.jar; \
    fetch_jar io/netty/netty-codec/4.1.135.Final/netty-codec-4.1.135.Final.jar \
      7252171264dbb5bb8ed38e77f89643b31e3cabc96144ec27b6882435d718a61e \
      /kafka/external_libs/apicurio/netty-codec-4.1.135.Final.jar; \
    fetch_jar io/netty/netty-codec-dns/4.1.135.Final/netty-codec-dns-4.1.135.Final.jar \
      5e996d7ac7597f368ab114fbb91d16788918c7e5bf166345c51e56db54d50fd1 \
      /kafka/external_libs/apicurio/netty-codec-dns-4.1.135.Final.jar; \
    fetch_jar io/netty/netty-codec-http/4.1.135.Final/netty-codec-http-4.1.135.Final.jar \
      4018529d3d6aecf4044b98c75d9a90c91839ddf49c7aa484c5ac81c90a15da02 \
      /kafka/external_libs/apicurio/netty-codec-http-4.1.135.Final.jar; \
    fetch_jar io/netty/netty-codec-http2/4.1.135.Final/netty-codec-http2-4.1.135.Final.jar \
      aa4e81ab5fa3b7b243eb3e814aa582ab26c073d31b0abffdbb58ee150fa49c16 \
      /kafka/external_libs/apicurio/netty-codec-http2-4.1.135.Final.jar; \
    fetch_jar io/netty/netty-codec-socks/4.1.135.Final/netty-codec-socks-4.1.135.Final.jar \
      ec7a39e8d7d7e223014115a021273f011c3cb1e8fb187cbfb90a74e76d68c25c \
      /kafka/external_libs/apicurio/netty-codec-socks-4.1.135.Final.jar; \
    fetch_jar io/netty/netty-common/4.1.135.Final/netty-common-4.1.135.Final.jar \
      26775ca95820711403cf065fa2ec0134a0a04ff5417c688c0237aee68b55838d \
      /kafka/external_libs/apicurio/netty-common-4.1.135.Final.jar; \
    fetch_jar io/netty/netty-handler/4.1.135.Final/netty-handler-4.1.135.Final.jar \
      245e74e04b6f4e8ef98853152412e3bf1499ce6fcf15329b798c8ce36c3537e2 \
      /kafka/external_libs/apicurio/netty-handler-4.1.135.Final.jar; \
    fetch_jar io/netty/netty-handler-proxy/4.1.135.Final/netty-handler-proxy-4.1.135.Final.jar \
      75661010630a44468f0e85d7ed8be7779c0cb1369fe85d30799cedc52e9ed3b7 \
      /kafka/external_libs/apicurio/netty-handler-proxy-4.1.135.Final.jar; \
    fetch_jar io/netty/netty-resolver/4.1.135.Final/netty-resolver-4.1.135.Final.jar \
      77dd03865965b6c12b9e521bddec82f035caeb33156e09c158289c5094318481 \
      /kafka/external_libs/apicurio/netty-resolver-4.1.135.Final.jar; \
    fetch_jar io/netty/netty-resolver-dns/4.1.135.Final/netty-resolver-dns-4.1.135.Final.jar \
      ca25581e4cebd55797ef3b4d0953b75df32c1af77fe771b96bfaa9e701cdb7c3 \
      /kafka/external_libs/apicurio/netty-resolver-dns-4.1.135.Final.jar; \
    fetch_jar io/netty/netty-transport/4.1.135.Final/netty-transport-4.1.135.Final.jar \
      6bde734d1ec073142eed31b1e68cd5d68fbf241e060b37f07a164e5ecb15631c \
      /kafka/external_libs/apicurio/netty-transport-4.1.135.Final.jar; \
    fetch_jar io/netty/netty-transport-native-unix-common/4.1.135.Final/netty-transport-native-unix-common-4.1.135.Final.jar \
      a7895075f112611d1640a596c2678a28aab92d5681c1c14755b109b8998f995e \
      /kafka/external_libs/apicurio/netty-transport-native-unix-common-4.1.135.Final.jar; \
    fetch_jar com/fasterxml/jackson/core/jackson-annotations/2.21/jackson-annotations-2.21.jar \
      53ca085f4a150f703f49e1aabd935bd03b43e1ea3d55d135438292af22cef56b \
      /kafka/libs/jackson-annotations-2.21.jar; \
    fetch_jar com/fasterxml/jackson/core/jackson-core/2.21.4/jackson-core-2.21.4.jar \
      4b40a06396f239f8de2da57419adde6e94e5edc18a2171d471ea05eeed4e5c2d \
      /kafka/libs/jackson-core-2.21.4.jar; \
    fetch_jar com/fasterxml/jackson/core/jackson-databind/2.21.4/jackson-databind-2.21.4.jar \
      3888e9e69ab66fbacaacc9aea0e9ffbf15368288e4aca468b024dba11c09fbf9 \
      /kafka/libs/jackson-databind-2.21.4.jar; \
    fetch_jar com/fasterxml/jackson/dataformat/jackson-dataformat-csv/2.21.4/jackson-dataformat-csv-2.21.4.jar \
      40f3fc22e9b1575838cc256013bc17db5b824c79fe0b5a32ae1662201e99dcca \
      /kafka/libs/jackson-dataformat-csv-2.21.4.jar; \
    fetch_jar com/fasterxml/jackson/dataformat/jackson-dataformat-yaml/2.21.4/jackson-dataformat-yaml-2.21.4.jar \
      055eb4c008ab12f0cb63e93a6454463d032fde0fca85943d69f8dc7469489e4b \
      /kafka/libs/jackson-dataformat-yaml-2.21.4.jar; \
    fetch_jar com/fasterxml/jackson/datatype/jackson-datatype-jdk8/2.21.4/jackson-datatype-jdk8-2.21.4.jar \
      2dde4a8f1aad3306c040f56ff40da81c6d58dcef3434c00849c9bce09f56a074 \
      /kafka/libs/jackson-datatype-jdk8-2.21.4.jar; \
    fetch_jar com/fasterxml/jackson/jakarta/rs/jackson-jakarta-rs-base/2.21.4/jackson-jakarta-rs-base-2.21.4.jar \
      ce62827a3381ef2db712503e242ab5a51a881613a9446948a3c25b2d7df326fe \
      /kafka/libs/jackson-jakarta-rs-base-2.21.4.jar; \
    fetch_jar com/fasterxml/jackson/jakarta/rs/jackson-jakarta-rs-json-provider/2.21.4/jackson-jakarta-rs-json-provider-2.21.4.jar \
      a8cd69b1dac55bdd0bad9d9803157b296243987b08d5ed7ccde3c81c07ce05cc \
      /kafka/libs/jackson-jakarta-rs-json-provider-2.21.4.jar; \
    fetch_jar com/fasterxml/jackson/module/jackson-module-blackbird/2.21.4/jackson-module-blackbird-2.21.4.jar \
      1d8f67a6e610c349c84cb9b468334164e2b23c86e4be26f903ab8bb1d2067794 \
      /kafka/libs/jackson-module-blackbird-2.21.4.jar; \
    fetch_jar com/fasterxml/jackson/module/jackson-module-jakarta-xmlbind-annotations/2.21.4/jackson-module-jakarta-xmlbind-annotations-2.21.4.jar \
      d5c5798fffa760ba6a84a7c9b65caf577f92b8d1c6bccb71d75e93e2ce59bf1d \
      /kafka/libs/jackson-module-jakarta-xmlbind-annotations-2.21.4.jar; \
    fetch_jar org/eclipse/jetty/jetty-alpn-client/12.0.33/jetty-alpn-client-12.0.33.jar \
      73f31fc34223468ade1ac5934156b71c18c5ef42d44476978b6dae19414349a0 \
      /kafka/libs/jetty-alpn-client-12.0.33.jar; \
    fetch_jar org/eclipse/jetty/jetty-client/12.0.33/jetty-client-12.0.33.jar \
      f5bae5ccce24c6ff8fad7f42515590286dd35935ee050cd4d11dbd4dbcda0602 \
      /kafka/libs/jetty-client-12.0.33.jar; \
    fetch_jar org/eclipse/jetty/ee10/jetty-ee10-servlet/12.0.33/jetty-ee10-servlet-12.0.33.jar \
      c3bf9debb69c9eecbb28e5b8add47b2a7e2af2ac8ed7a6525ebba007bd163a1e \
      /kafka/libs/jetty-ee10-servlet-12.0.33.jar; \
    fetch_jar org/eclipse/jetty/ee10/jetty-ee10-servlets/12.0.33/jetty-ee10-servlets-12.0.33.jar \
      ef632347073a290a7533ed6a4d5e3d2adad0f374a3af5e0e7d2f5d161a8d69f2 \
      /kafka/libs/jetty-ee10-servlets-12.0.33.jar; \
    fetch_jar org/eclipse/jetty/jetty-http/12.0.33/jetty-http-12.0.33.jar \
      325a8b5d5761d790d3c1db61c130e55f57d338ef644c89270d6b835ca52140a3 \
      /kafka/libs/jetty-http-12.0.33.jar; \
    fetch_jar org/eclipse/jetty/jetty-io/12.0.33/jetty-io-12.0.33.jar \
      b904a32a36100586c697a4d5089a22b92746441cd40dfe564f217d8f317d0f4c \
      /kafka/libs/jetty-io-12.0.33.jar; \
    fetch_jar org/eclipse/jetty/jetty-security/12.0.33/jetty-security-12.0.33.jar \
      aa901de005cf68ed5ed48ba11765d2e8d436b000068aec7945022bad58e7ca0f \
      /kafka/libs/jetty-security-12.0.33.jar; \
    fetch_jar org/eclipse/jetty/jetty-server/12.0.33/jetty-server-12.0.33.jar \
      1bfcce5f08967098f1c796ca244cbc0a992eb9d2090b75f3f7999960eb68a0e4 \
      /kafka/libs/jetty-server-12.0.33.jar; \
    fetch_jar org/eclipse/jetty/jetty-session/12.0.33/jetty-session-12.0.33.jar \
      d1ff567a3c259c12b53b4f0260ccb6cb9dfadcab9e12734e50dac3b4c94b0dbf \
      /kafka/libs/jetty-session-12.0.33.jar; \
    fetch_jar org/eclipse/jetty/jetty-util/12.0.33/jetty-util-12.0.33.jar \
      a595911e0ac7f74200b351c9980c66dcf5c3baf1914a49da060fd26d3244b218 \
      /kafka/libs/jetty-util-12.0.33.jar; \
    fetch_jar org/postgresql/postgresql/42.7.13/postgresql-42.7.13.jar \
      6e0e4cc2d8cae902084f8a2b18728b073a6fd9d1f87c9d8bff8f298c18185b93 \
      /kafka/connect/debezium-connector-postgres/postgresql-42.7.13.jar

# Install Qdrant Kafka Sink Connector
# https://github.com/qdrant/qdrant-kafka
ARG QDRANT_CONNECTOR_VERSION=1.3.3
ARG QDRANT_CONNECTOR_SHA256=f35b1eef7db212e561019b9e9218e4674d231ca577b603a40e028e1de8f59fa6
RUN mkdir -p /kafka/connect/qdrant-kafka
WORKDIR /kafka/connect/qdrant-kafka
# WHY: Qdrant Kafka 1.3.3 omits the bundled DNS provider from its service descriptor.
# Terminal exact-match grep fails when unzip produces no output, so pipefail adds no failure coverage.
# hadolint ignore=DL4006
RUN set -eu; \
    curl --fail --show-error --silent --location \
      "https://github.com/qdrant/qdrant-kafka/releases/download/v${QDRANT_CONNECTOR_VERSION}/qdrant-kafka-${QDRANT_CONNECTOR_VERSION}.zip" \
      --output qdrant-kafka.zip; \
    printf '%s  %s\n' "${QDRANT_CONNECTOR_SHA256}" qdrant-kafka.zip > qdrant-kafka.sha256; \
    sha256sum --check --strict qdrant-kafka.sha256; \
    unzip qdrant-kafka.zip; \
    descriptor='META-INF/services/shadow.grpc.NameResolverProvider'; \
    connector_jar="qdrant-kafka-${QDRANT_CONNECTOR_VERSION}/lib/kafka-${QDRANT_CONNECTOR_VERSION}.jar"; \
    dns_provider='shadow.grpc.internal.DnsNameResolverProvider'; \
    uds_provider='shadow.grpc.netty.shaded.io.grpc.netty.UdsNameResolverProvider'; \
    test -f "${connector_jar}"; \
    unzip -Z1 "${connector_jar}" | grep -Fxq 'shadow/grpc/internal/DnsNameResolverProvider.class'; \
    unzip -Z1 "${connector_jar}" | grep -Fxq "${descriptor}"; \
    unzip -p "${connector_jar}" "${descriptor}" | grep -Fxq "${uds_provider}"; \
    mkdir -p META-INF/services; \
    printf '%s\n%s\n' "${dns_provider}" "${uds_provider}" > "${descriptor}"; \
    zip -q -X "${connector_jar}" "${descriptor}"; \
    test "$(unzip -p "${connector_jar}" "${descriptor}")" = "$(printf '%s\n%s' "${dns_provider}" "${uds_provider}")"; \
    rm -rf META-INF qdrant-kafka.zip qdrant-kafka.sha256
WORKDIR /kafka

# Install Nohiki WAL Router SMT (built in stage 1)
RUN mkdir -p /kafka/connect/nohiki-wal-router
COPY --from=smt-builder /build/build/libs/nohiki-wal-router-smt-*-all.jar \
     /kafka/connect/nohiki-wal-router/

# Set plugin path to include all connector directories
ENV CONNECT_PLUGIN_PATH=/kafka/connect

# Add connector configs and scripts for auto-registration
# Use --chmod to set permissions during COPY (BuildKit feature)
COPY --chmod=755 scripts/ /kafka/scripts/
COPY --chmod=644 connectors/ /kafka/connectors/

USER 1001

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=10 \
    CMD ["curl", "--fail", "--silent", "--show-error", "--max-time", "5", "http://localhost:8083/"]

ENTRYPOINT ["/kafka/scripts/entrypoint.sh"]

# -----------------------------------------------------------------------------
# Stage 3: Strimzi-compatible runtime for KafkaConnect custom resources
# -----------------------------------------------------------------------------
FROM quay.io/strimzi/kafka:1.1.0-kafka-4.3.0@sha256:b6848a53c01eec98b37866450a1227c3a41707785ec65b37063d2733a105bf36 AS strimzi
USER root:root
COPY --from=compose --chown=1001:0 /kafka/connect/debezium-connector-postgres/ /opt/kafka/plugins/debezium-postgres/
COPY --from=compose --chown=1001:0 /kafka/connect/qdrant-kafka/ /opt/kafka/plugins/qdrant-kafka/
COPY --from=compose --chown=1001:0 /kafka/connect/nohiki-wal-router/ /opt/kafka/plugins/nohiki-wal-router/
USER 1001
