{{/*
Prometheus scraping annotations.
Usage: {{ include "nohiki-common.prometheusAnnotations" . | nindent 8 }}
*/}}
{{- define "nohiki-common.prometheusAnnotations" -}}
{{- $service := .Values.service | default dict }}
prometheus.io/scrape: "true"
prometheus.io/port: {{ $service.port | default 8000 | quote }}
prometheus.io/path: "/metrics"
{{- end }}
