{{/*
Safe type-checked accessor for database.enabled.
Returns "true" (string) if value is a map AND has database.enabled: true, empty otherwise.
Uses typeOf check before any map operations to prevent dig errors on non-map values.
Usage: {{- if eq (include "nohiki.hasDatabaseEnabled" $svcValues) "true" }}
*/}}
{{- define "nohiki.hasDatabaseEnabled" -}}
{{- $type := typeOf . -}}
{{- if or (eq $type "map[string]interface {}") (hasPrefix "map[" $type) -}}
{{- $db := index . "database" | default dict -}}
{{- if and (kindIs "map" $db) (index $db "enabled") -}}
true
{{- end -}}
{{- end -}}
{{- end }}

{{/*
Database Helper Templates - derives database values from service name with override capability.

Design: Iterates over .Values using dig to find subcharts with database.enabled: true.
No hardcoded service list - each service self-registers via its own values.yaml.

Naming Convention (auto-derived from service name):
  user-auth-service -> user_auth_db, user_auth_schema, user_auth_svc, user_auth_debezium

Override: Set explicit values in per-service values.yaml to override derivation.
*/}}

{{/*
Convert service name to database identifier prefix.
Example: user-auth-service -> user_auth
*/}}
{{- define "nohiki.dbPrefix" -}}
{{- . | replace "-service" "" | replace "-" "_" -}}
{{- end }}

{{/*
Get database name for a service (derived or explicit override).
Usage: {{ include "nohiki.dbName" (dict "svcName" "user-auth-service" "svcValues" $svcValues) }}
*/}}
{{- define "nohiki.dbName" -}}
{{- $prefix := include "nohiki.dbPrefix" .svcName -}}
{{- dig "database" "name" (printf "%s_db" $prefix) .svcValues -}}
{{- end }}

{{/*
Get RFC1123-safe Kubernetes resource name for Database CR metadata.name.
Database CR spec.name still uses dbName (can include underscores).
*/}}
{{- define "nohiki.dbResourceName" -}}
{{- $dbName := include "nohiki.dbName" . -}}
{{- $dbName | replace "_" "-" | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{/*
Get database schema for a service (derived or explicit override).
*/}}
{{- define "nohiki.dbSchema" -}}
{{- $prefix := include "nohiki.dbPrefix" .svcName -}}
{{- dig "database" "schema" (printf "%s_schema" $prefix) .svcValues -}}
{{- end }}

{{/*
Get app role name for a service (derived or explicit database.roles.app override).
*/}}
{{- define "nohiki.dbAppRole" -}}
{{- $prefix := include "nohiki.dbPrefix" .svcName -}}
{{- $appRole := dig "database" "roles" "app" "" .svcValues -}}
{{- $appRole | default (printf "%s_svc" $prefix) -}}
{{- end }}

{{/*
Get debezium role name for a service (derived or explicit database.roles.debezium override).
*/}}
{{- define "nohiki.dbDebeziumRole" -}}
{{- $prefix := include "nohiki.dbPrefix" .svcName -}}
{{- $debeziumRole := dig "database" "roles" "debezium" "" .svcValues -}}
{{- $debeziumRole | default (printf "%s_debezium" $prefix) -}}
{{- end }}

{{/* Get app role secret name for a service. */}}
{{- define "nohiki.dbAppSecretName" -}}
{{- printf "%s-db-credentials" .svcName -}}
{{- end }}

{{/* Get Debezium role secret name for a service. */}}
{{- define "nohiki.dbDebeziumSecretName" -}}
{{- printf "%s-debezium-credentials" .svcName -}}
{{- end }}
