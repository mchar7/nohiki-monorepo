{{/*
Container resource limits and requests.
Usage: {{ include "nohiki-common.resources" . | nindent 12 }}
*/}}
{{- define "nohiki-common.resources" -}}
{{- $resources := .Values.resources | default dict }}
{{- $requests := $resources.requests | default dict }}
{{- $limits := $resources.limits | default dict }}
{{- $gpu := int ($resources.gpu | default 0) }}
requests:
  cpu: {{ $requests.cpu | default "100m" }}
  memory: {{ $requests.memory | default "256Mi" }}
  {{- if gt $gpu 0 }}
  nvidia.com/gpu: {{ $gpu }}
  {{- end }}
limits:
  cpu: {{ $limits.cpu | default "500m" }}
  memory: {{ $limits.memory | default "512Mi" }}
  {{- if gt $gpu 0 }}
  nvidia.com/gpu: {{ $gpu }}
  {{- end }}
{{- end }}
