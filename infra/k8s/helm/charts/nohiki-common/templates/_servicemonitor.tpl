{{/*
Prometheus ServiceMonitor for automatic metrics scraping.
Requires the Prometheus Operator CRD. Only created when monitoring is enabled.
Usage: {{ include "nohiki-common.servicemonitor" . }}
*/}}
{{- define "nohiki-common.servicemonitor" -}}
{{- if ne .Values.enabled false }}
{{- $monitoring := .Values.monitoring | default dict }}
{{- if $monitoring.enabled }}
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: {{ include "nohiki-common.fullname" . }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "nohiki-common.labels" . | nindent 4 }}
    {{- with $monitoring.labels }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
spec:
  selector:
    matchLabels:
      {{- include "nohiki-common.selectorLabels" . | nindent 6 }}
  endpoints:
    - port: http
      path: {{ $monitoring.path | default "/metrics" }}
      interval: {{ $monitoring.interval | default "30s" }}
      scrapeTimeout: {{ $monitoring.scrapeTimeout | default "10s" }}
  namespaceSelector:
    matchNames:
      - {{ .Release.Namespace }}
{{- end }}
{{- end }}
{{- end }}
