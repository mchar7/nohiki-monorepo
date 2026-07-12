{{/*
Service template for Nohiki microservices.
Usage: {{ include "nohiki-common.service" . }}
*/}}
{{- define "nohiki-common.service" -}}
{{- $svc := .Values.service | default dict }}
{{- if and (ne .Values.enabled false) (ne ($svc.enabled | default true) false) }}
apiVersion: v1
kind: Service
metadata:
  name: {{ include "nohiki-common.fullname" . }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "nohiki-common.labels" . | nindent 4 }}
spec:
  type: {{ $svc.type | default "ClusterIP" }}
  ports:
    - port: {{ $svc.port | default 8000 }}
      targetPort: http
      protocol: TCP
      name: http
  selector:
    {{- include "nohiki-common.selectorLabels" . | nindent 4 }}
{{- end }}
{{- end }}
