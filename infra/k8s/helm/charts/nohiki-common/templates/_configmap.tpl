{{/*
ConfigMap template for Nohiki microservices.
Usage: {{ include "nohiki-common.configmap" . }}
*/}}
{{- define "nohiki-common.configmap" -}}
{{- if and (ne .Values.enabled false) .Values.configMap }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "nohiki-common.fullname" . }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "nohiki-common.labels" . | nindent 4 }}
data:
  {{- toYaml .Values.configMap | nindent 2 }}
{{- end }}
{{- end }}
