{{/*
ServiceAccount template for Nohiki microservices.
Supports Azure Workload Identity via .Values.serviceAccount.azureClientId.
Usage: {{ include "nohiki-common.serviceaccount" . }}
*/}}
{{- define "nohiki-common.serviceaccount" -}}
{{- if and (ne .Values.enabled false) .Values.serviceAccount.create }}
{{- $sa := .Values.serviceAccount | default dict }}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ include "nohiki-common.serviceAccountName" . }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "nohiki-common.labels" . | nindent 4 }}
  {{- $annotations := dict }}
  {{- if $sa.annotations }}
  {{- $annotations = merge $annotations $sa.annotations }}
  {{- end }}
  {{- if $sa.azureClientId }}
  {{- $_ := set $annotations "azure.workload.identity/client-id" $sa.azureClientId }}
  {{- end }}
  {{- if $annotations }}
  annotations:
    {{- toYaml $annotations | nindent 4 }}
  {{- end }}
automountServiceAccountToken: false
{{- end }}
{{- end }}
