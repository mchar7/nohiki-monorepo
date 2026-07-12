{{/*
HTTP liveness probe.
*/}}
{{- define "nohiki-common.probes.liveness" -}}
{{- $probes := .Values.probes | default dict -}}
{{- $liveness := $probes.liveness | default dict -}}
httpGet:
  path: {{ $liveness.path | default "/healthz" }}
  port: http
initialDelaySeconds: {{ $liveness.initialDelaySeconds | default 30 }}
periodSeconds: {{ $liveness.periodSeconds | default 30 }}
timeoutSeconds: {{ $liveness.timeoutSeconds | default 5 }}
failureThreshold: {{ $liveness.failureThreshold | default 3 }}
{{- end }}

{{/*
HTTP readiness probe.
*/}}
{{- define "nohiki-common.probes.readiness" -}}
{{- $probes := .Values.probes | default dict -}}
{{- $readiness := $probes.readiness | default dict -}}
httpGet:
  path: {{ $readiness.path | default "/readyz" }}
  port: http
initialDelaySeconds: {{ $readiness.initialDelaySeconds | default 15 }}
periodSeconds: {{ $readiness.periodSeconds | default 15 }}
timeoutSeconds: {{ $readiness.timeoutSeconds | default 5 }}
failureThreshold: {{ $readiness.failureThreshold | default 3 }}
{{- end }}
