{{/*
Common environment variables for all services.
Usage: {{ include "nohiki-common.env.common" . | nindent 12 }}
*/}}
{{- define "nohiki-common.env.common" -}}
{{- $glob := .Values.global | default dict }}
{{- $svc := .Values.service | default dict }}
{{- $prefix := .Values.envPrefix | default "" }}
- name: ENVIRONMENT
  value: {{ required (printf "%s requires global.environment" (include "nohiki-common.name" .)) $glob.environment | quote }}
- name: SERVICE_NAME
  value: {{ $svc.name | default (include "nohiki-common.name" .) | quote }}
- name: SERVICE_VERSION
  value: {{ .Chart.AppVersion | default "0.1.0" | quote }}
- name: {{ $prefix }}SECRETS_DIR
  value: {{ (.Values.secrets).mountPath | default "/run/secrets" | quote }}
- name: POD_NAME
  valueFrom:
    fieldRef:
      fieldPath: metadata.name
- name: POD_NAMESPACE
  valueFrom:
    fieldRef:
      fieldPath: metadata.namespace
- name: POD_IP
  valueFrom:
    fieldRef:
      fieldPath: status.podIP
{{- end }}

{{/*
Database environment variables (nested format).
Credentials are read from secrets at /run/secrets/database/*, non-sensitive from env.
Usage: {{ include "nohiki-common.env.database" . | nindent 12 }}
*/}}
{{- define "nohiki-common.env.database" -}}
{{- $db := .Values.database | default dict }}
{{- if $db.enabled }}
{{- $glob := .Values.global | default dict }}
{{- $globDb := $glob.database | default dict }}
{{- $prefix := .Values.envPrefix | default "" }}
- name: {{ $prefix }}DATABASE__DSN
  valueFrom:
    secretKeyRef:
      name: {{ printf "%s-db-credentials" .Chart.Name }}
      key: dsn
- name: {{ $prefix }}DATABASE__SCHEMA_NAME
  value: {{ $db.schema | default "public" | quote }}
{{- end }}
{{- end }}

{{/*
Redis environment variables (DSN format matching compose).
Usage: {{ include "nohiki-common.env.redis" . | nindent 12 }}
*/}}
{{- define "nohiki-common.env.redis" -}}
{{- $redis := .Values.redis | default dict }}
{{- if $redis.enabled }}
{{- $glob := .Values.global | default dict }}
{{- $globSecrets := $glob.secrets | default dict }}
{{- $prefix := .Values.envPrefix | default "" }}
- name: {{ $prefix }}REDIS__DSN
  valueFrom:
    secretKeyRef:
      name: {{ $globSecrets.redisSecretName | default "nohiki-redis-credentials" }}
      key: dsn
{{- end }}
{{- end }}

{{/*
Kafka environment variables (DSN format matching compose: kafka://host:port).
Usage: {{ include "nohiki-common.env.kafka" . | nindent 12 }}
*/}}
{{- define "nohiki-common.env.kafka" -}}
{{- $kafka := .Values.kafka | default dict }}
{{- if $kafka.enabled | default true }}
{{- $glob := .Values.global | default dict }}
{{- $globKafka := $glob.kafka | default dict }}
{{- $prefix := .Values.envPrefix | default "" }}
{{- $bootstrap := required (printf "%s requires global.kafka.bootstrapServers" (include "nohiki-common.name" .)) $globKafka.bootstrapServers }}
{{- $dsn := $globKafka.dsn | default (printf "kafka://%s" $bootstrap) }}
- name: {{ $prefix }}KAFKA__DSN
  value: {{ $dsn | quote }}
- name: {{ $prefix }}KAFKA__CONSUMER_GROUP
  value: {{ $kafka.consumerGroup | default (printf "%s-consumer" (include "nohiki-common.name" .)) | quote }}
{{- $security := $globKafka.security | default dict }}
{{- $sasl := $security.sasl | default dict }}
- name: {{ $prefix }}KAFKA__SECURITY__PROTOCOL
  value: {{ $security.protocol | default "PLAINTEXT" | quote }}
{{- if $sasl.mechanism }}
- name: {{ $prefix }}KAFKA__SECURITY__SASL__MECHANISM
  value: {{ $sasl.mechanism | quote }}
{{- end }}
{{- if $sasl.secretName }}
- name: {{ $prefix }}KAFKA__SECURITY__SASL__USERNAME
  valueFrom:
    secretKeyRef:
      name: {{ $sasl.secretName }}
      key: username
- name: {{ $prefix }}KAFKA__SECURITY__SASL__PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ $sasl.secretName }}
      key: password
{{- end }}
{{- end }}
{{- end }}

{{/*
Observability environment variables (matching compose pattern).
Usage: {{ include "nohiki-common.env.observability" . | nindent 12 }}
*/}}
{{- define "nohiki-common.env.observability" -}}
{{- $obs := .Values.observability | default dict }}
{{- if $obs.enabled | default true }}
{{- $glob := .Values.global | default dict }}
{{- $globObs := $glob.observability | default dict }}
{{- $otelEndpoint := required (printf "%s requires global.observability.otelEndpoint" (include "nohiki-common.name" .)) $globObs.otelEndpoint }}
- name: OTEL_COLLECTOR_GRPC_ENDPOINT
  value: {{ $otelEndpoint | quote }}
- name: OTEL_EXPORTER_INSECURE
  value: {{ $globObs.otelInsecure | default "true" | quote }}
- name: OTEL_ENABLED
  value: {{ $globObs.otelEnabled | default "false" | quote }}
{{- $otelTls := $globObs.otelTls | default dict }}
{{- if $otelTls.enabled }}
- name: OTEL_EXPORTER_OTLP_CERTIFICATE
  value: {{ required (printf "%s requires global.observability.otelTls.certificatePath" (include "nohiki-common.name" .)) $otelTls.certificatePath | quote }}
{{- end }}
- name: PHOENIX_COLLECTOR_ENDPOINT
  value: {{ $globObs.phoenixEndpoint | default "" | quote }}
- name: PHOENIX_ENABLED
  value: {{ $globObs.phoenixEnabled | default "false" | quote }}
- name: PHOENIX_PROJECT_NAME
  value: {{ $globObs.phoenixProjectName | default "nohiki" | quote }}
{{- end }}
{{- end }}

{{/*
S3 environment variables (matching compose pattern).
Usage: {{ include "nohiki-common.env.s3" . | nindent 12 }}
*/}}
{{- define "nohiki-common.env.s3" -}}
{{- $s3 := .Values.s3 | default dict }}
{{- if $s3.enabled }}
{{- $glob := .Values.global | default dict }}
{{- $globS3 := $glob.s3 | default dict }}
{{- $prefix := .Values.envPrefix | default "" }}
{{- $endpoint := $s3.endpoint | default $globS3.endpoint }}
- name: {{ $prefix }}S3__PROVIDER
  value: {{ $s3.provider | default $globS3.provider | default "s3" | quote }}
- name: {{ $prefix }}S3__ENDPOINT
  value: {{ required (printf "%s requires s3.endpoint or global.s3.endpoint" (include "nohiki-common.name" .)) $endpoint | quote }}
- name: {{ $prefix }}S3__BUCKET
  value: {{ $s3.bucket | default "nohiki-attachments" | quote }}
- name: {{ $prefix }}S3__REGION
  value: {{ $s3.region | default $globS3.region | default "us-east-1" | quote }}
{{- end }}
{{- end }}

{{/*
Qdrant environment variables.
Usage: {{ include "nohiki-common.env.qdrant" . | nindent 12 }}
*/}}
{{- define "nohiki-common.env.qdrant" -}}
{{- $qdrant := .Values.qdrant | default dict }}
{{- if $qdrant.enabled }}
{{- $glob := .Values.global | default dict }}
{{- $globQdrant := $glob.qdrant | default dict }}
{{- $prefix := .Values.envPrefix | default "" }}
{{- $host := $qdrant.host | default $globQdrant.host | default "nohiki-qdrant" }}
{{- $grpcPort := $qdrant.grpcPort | default $globQdrant.grpcPort | default "6334" }}
{{- $useTls := $qdrant.useTls | default $globQdrant.useTls | default false }}
- name: {{ $prefix }}QDRANT__HOST
  value: {{ $host | quote }}
- name: {{ $prefix }}QDRANT__GRPC_PORT
  value: {{ $grpcPort | quote }}
- name: {{ $prefix }}QDRANT__USE_TLS
  value: {{ $useTls | quote }}
{{- $apiKeySecret := $qdrant.apiKeySecret | default $globQdrant.apiKeySecret }}
{{- if $apiKeySecret }}
- name: {{ $prefix }}QDRANT__API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ $apiKeySecret }}
      key: api-key
{{- end }}
{{- end }}

{{- end }}
{{/*
LLM environment variables (provider models, named chains, caching, instrumentation).
Translates values.llm into {PREFIX}LLM__* env vars for nohiki_llm_client settings.
Usage: {{ include "nohiki-common.env.llm" . | nindent 12 }}
*/}}
{{- define "nohiki-common.env.llm" -}}
{{- $llm := .Values.llm | default dict }}
{{- if $llm.enabled }}
{{- $prefix := .Values.envPrefix | default "" }}
{{- $provider := $llm.provider | default dict }}
{{- $glob := .Values.global | default dict }}
{{- $modelEgress := $glob.modelEgress | default dict }}
{{- $gatewayHost := printf "%s-model-egress.%s.svc.cluster.local" .Release.Name .Release.Namespace }}
{{- $gatewayOrigin := printf "https://%s:%v" $gatewayHost ($modelEgress.listenerPort | default 8443) }}
{{- $modelCaFile := printf "%s/ca.crt" ($modelEgress.caMountPath | default "/etc/nohiki/model-egress") }}
{{- $modelClient := dict }}
{{- range $client := $modelEgress.clients }}
{{- if eq $client.name $.Chart.Name }}
{{- $modelClient = $client }}
{{- end }}
{{- end }}
{{- $clientSecretName := required (printf "global.modelEgress.clients requires a Secret mapping for %s" .Chart.Name) $modelClient.secretName }}
{{- $clientSecretKey := required (printf "global.modelEgress.clients requires a secretKey for %s" .Chart.Name) $modelClient.secretKey }}
{{- range $providerName := list "OPENROUTER" "OPENAI" "ANTHROPIC" }}
- name: {{ $prefix }}LLM__PROVIDER__API_KEYS__{{ $providerName }}
  valueFrom:
    secretKeyRef:
      name: {{ $clientSecretName }}
      key: {{ $clientSecretKey }}
{{- end }}
{{- range $i, $m := $provider.models | default list }}
- name: {{ $prefix }}LLM__PROVIDER__MODELS__{{ $i }}__MODEL
  value: {{ $m.model | quote }}
- name: {{ $prefix }}LLM__PROVIDER__MODELS__{{ $i }}__BASE_URL
  value: {{ ternary $gatewayOrigin (printf "%s/v1" $gatewayOrigin) (hasPrefix "anthropic:" $m.model) | quote }}
- name: {{ $prefix }}LLM__PROVIDER__MODELS__{{ $i }}__HEALTH_URL
  value: {{ printf "%s/healthz" $gatewayOrigin | quote }}
- name: {{ $prefix }}LLM__PROVIDER__MODELS__{{ $i }}__TLS_CA_FILE
  value: {{ $modelCaFile | quote }}
{{- if $m.reasoningEffort }}
- name: {{ $prefix }}LLM__PROVIDER__MODELS__{{ $i }}__REASONING_EFFORT
  value: {{ $m.reasoningEffort | quote }}
{{- end }}
{{- range $j, $p := $m.providerOrder | default list }}
- name: {{ $prefix }}LLM__PROVIDER__MODELS__{{ $i }}__PROVIDER_ORDER__{{ $j }}
  value: {{ $p | quote }}
{{- end }}
{{- end }}
{{- if $provider.temperature }}
- name: {{ $prefix }}LLM__PROVIDER__TEMPERATURE
  value: {{ $provider.temperature | quote }}
{{- end }}
{{- if $provider.timeoutSeconds }}
- name: {{ $prefix }}LLM__PROVIDER__TIMEOUT_SECONDS
  value: {{ $provider.timeoutSeconds | quote }}
{{- end }}
{{- if $provider.maxTokens }}
- name: {{ $prefix }}LLM__PROVIDER__MAX_TOKENS
  value: {{ $provider.maxTokens | quote }}
{{- end }}
{{- range $chainName, $chain := $llm.chains | default dict }}
{{- $chainKey := $chainName | upper | replace "-" "_" }}
{{- range $i, $m := $chain.models | default list }}
- name: {{ $prefix }}LLM__CHAINS__{{ $chainKey }}__MODELS__{{ $i }}__MODEL
  value: {{ $m.model | quote }}
- name: {{ $prefix }}LLM__CHAINS__{{ $chainKey }}__MODELS__{{ $i }}__BASE_URL
  value: {{ ternary $gatewayOrigin (printf "%s/v1" $gatewayOrigin) (hasPrefix "anthropic:" $m.model) | quote }}
- name: {{ $prefix }}LLM__CHAINS__{{ $chainKey }}__MODELS__{{ $i }}__HEALTH_URL
  value: {{ printf "%s/healthz" $gatewayOrigin | quote }}
- name: {{ $prefix }}LLM__CHAINS__{{ $chainKey }}__MODELS__{{ $i }}__TLS_CA_FILE
  value: {{ $modelCaFile | quote }}
{{- if $m.reasoningEffort }}
- name: {{ $prefix }}LLM__CHAINS__{{ $chainKey }}__MODELS__{{ $i }}__REASONING_EFFORT
  value: {{ $m.reasoningEffort | quote }}
{{- end }}
{{- range $j, $p := $m.providerOrder | default list }}
- name: {{ $prefix }}LLM__CHAINS__{{ $chainKey }}__MODELS__{{ $i }}__PROVIDER_ORDER__{{ $j }}
  value: {{ $p | quote }}
{{- end }}
{{- end }}
{{- if $chain.temperature }}
- name: {{ $prefix }}LLM__CHAINS__{{ $chainKey }}__TEMPERATURE
  value: {{ $chain.temperature | quote }}
{{- end }}
{{- if $chain.timeoutSeconds }}
- name: {{ $prefix }}LLM__CHAINS__{{ $chainKey }}__TIMEOUT_SECONDS
  value: {{ $chain.timeoutSeconds | quote }}
{{- end }}
{{- if $chain.maxTokens }}
- name: {{ $prefix }}LLM__CHAINS__{{ $chainKey }}__MAX_TOKENS
  value: {{ $chain.maxTokens | quote }}
{{- end }}
{{- end }}
{{- $caching := $llm.caching | default dict }}
{{- if $caching.enabled }}
- name: {{ $prefix }}LLM__CACHING__ENABLED
  value: {{ $caching.enabled | quote }}
{{- end }}
{{- $instrumentation := $llm.instrumentation | default dict }}
{{- if $instrumentation.enabled }}
- name: {{ $prefix }}LLM__INSTRUMENTATION__ENABLED
  value: {{ $instrumentation.enabled | quote }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Manifest path environment variable.
Sets {PREFIX}MANIFEST_PATH to the ConfigMap-mounted file location.
Usage: {{ include "nohiki-common.env.manifest" . | nindent 12 }}
*/}}
{{- define "nohiki-common.env.manifest" -}}
{{- $m := .Values.mlManifest | default dict }}
{{- if $m.enabled }}
{{- $prefix := .Values.envPrefix | default "" }}
- name: {{ $prefix }}MANIFEST_PATH
  value: {{ $m.mountPath | default "/app/data/config/semantic_representation_manifest.json" | quote }}
{{- end }}
{{- end }}

{{/*
All environment variables combined.
Usage: {{ include "nohiki-common.env.all" . | nindent 12 }}
*/}}
{{- define "nohiki-common.env.all" -}}
{{ include "nohiki-common.env.common" . }}
{{- include "nohiki-common.env.database" . }}
{{- include "nohiki-common.env.redis" . }}
{{- include "nohiki-common.env.kafka" . }}
{{- include "nohiki-common.env.s3" . }}
{{- include "nohiki-common.env.qdrant" . }}
{{- include "nohiki-common.env.observability" . }}
{{- include "nohiki-common.env.llm" . }}
{{- include "nohiki-common.env.manifest" . }}
{{- with .Values.extraEnv }}
{{ tpl (toYaml .) $ }}
{{- end }}
{{- end }}
