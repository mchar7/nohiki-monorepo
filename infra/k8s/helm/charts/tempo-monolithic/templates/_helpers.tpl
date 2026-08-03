{{- define "tempo-monolithic.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "tempo-monolithic.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name (include "tempo-monolithic.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{- define "tempo-monolithic.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{ include "tempo-monolithic.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "tempo-monolithic.selectorLabels" -}}
app.kubernetes.io/name: tempo
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: monolithic
{{- end -}}

{{- define "tempo-monolithic.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "tempo-monolithic.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- required "serviceAccount.name is required when serviceAccount.create is false" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}
