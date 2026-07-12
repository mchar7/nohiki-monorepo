{{/*
PodDisruptionBudget template for HA services.
Only created when replicaCount > 1 or scaling is enabled.
Usage: {{ include "nohiki-common.pdb" . }}
*/}}
{{- define "nohiki-common.pdb" -}}
{{- if ne .Values.enabled false }}
{{- $scaling := .Values.scaling | default dict }}
{{- $replicas := .Values.replicaCount | default 1 }}
{{- if or $scaling.enabled (gt (int $replicas) 1) }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ include "nohiki-common.fullname" . }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "nohiki-common.labels" . | nindent 4 }}
spec:
  {{- $pdb := .Values.pdb | default dict }}
  {{- if $pdb.minAvailable }}
  minAvailable: {{ $pdb.minAvailable }}
  {{- else if $pdb.maxUnavailable }}
  maxUnavailable: {{ $pdb.maxUnavailable }}
  {{- else }}
  maxUnavailable: 1
  {{- end }}
  selector:
    matchLabels:
      {{- include "nohiki-common.selectorLabels" . | nindent 6 }}
{{- end }}
{{- end }}
{{- end }}
