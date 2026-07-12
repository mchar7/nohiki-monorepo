{{/*
Expand the name of the chart.
*/}}
{{- define "nohiki-common.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Fully qualified app name (truncated to 63 chars for DNS compliance).
*/}}
{{- define "nohiki-common.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Chart label value.
*/}}
{{- define "nohiki-common.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels (applied to all resources).
*/}}
{{- define "nohiki-common.labels" -}}
helm.sh/chart: {{ include "nohiki-common.chart" . }}
{{ include "nohiki-common.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/component: {{ .Chart.Name }}
app.kubernetes.io/part-of: nohiki
{{- $glob := .Values.global | default dict }}
environment: {{ $glob.environment | default "dev" }}
{{- end }}

{{/*
Selector labels (used for pod matching).
*/}}
{{- define "nohiki-common.selectorLabels" -}}
app.kubernetes.io/name: {{ include "nohiki-common.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Pod labels (selector labels + optional extras).
*/}}
{{- define "nohiki-common.podLabels" -}}
{{ include "nohiki-common.selectorLabels" . }}
app.kubernetes.io/part-of: nohiki
{{- with .Values.podLabels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Pod annotations (Prometheus scraping + custom).
*/}}
{{- define "nohiki-common.podAnnotations" -}}
{{- include "nohiki-common.prometheusAnnotations" . }}
{{- with .Values.podAnnotations }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Service account name.
*/}}
{{- define "nohiki-common.serviceAccountName" -}}
{{- $sa := .Values.serviceAccount | default dict }}
{{- if $sa.create }}
{{- default (include "nohiki-common.fullname" .) $sa.name }}
{{- else }}
{{- default "default" $sa.name }}
{{- end }}
{{- end }}

{{/*
Canonical image repository path (no tag/digest). Shared by nohiki-common.image
and the accelerator digest guard so both compute the digest key identically.
For local k3s (empty registry): image-name
For CI/prod (with registry): registry/owner/repo/image-name
*/}}
{{- define "nohiki-common.imageRepository" -}}
{{- $glob := .Values.global | default dict }}
{{- $globImage := $glob.nohikiImage | default dict }}
{{- $svcImage := .Values.image | default dict }}
{{- $imageName := $svcImage.name | default .Chart.Name }}
{{- $registry := $svcImage.registry | default $globImage.registry | default "" }}
{{- $owner := $svcImage.owner | default $globImage.owner | default "" }}
{{- $repoName := $svcImage.repositoryName | default $globImage.repositoryName | default "" }}
{{- $repository := $imageName }}
{{- if and $registry $owner $repoName }}
{{- $repository = printf "%s/%s/%s/%s" $registry $owner $repoName $imageName }}
{{- else if $registry }}
{{- $repository = printf "%s/%s" $registry $imageName }}
{{- end }}
{{- $repository -}}
{{- end }}

{{/*
Container image reference (repository + digest in prod, repository + tag otherwise).
*/}}
{{- define "nohiki-common.image" -}}
{{- $glob := .Values.global | default dict }}
{{- $svcImage := .Values.image | default dict }}
{{- $imageName := $svcImage.name | default .Chart.Name }}
{{- $repository := include "nohiki-common.imageRepository" . | trim }}
{{- $digests := $glob.imageDigests | default dict }}
{{- $digest := index $digests $repository | default "" }}
{{- if $digest }}
{{- if not (regexMatch "^sha256:[0-9a-f]{64}$" $digest) }}
{{- fail (printf "invalid digest for image %s: %s" $imageName $digest) }}
{{- end }}
{{- printf "%s@%s" $repository $digest }}
{{- else if eq ($glob.environment | default "") "prod" }}
{{- fail (printf "production image digest is required for canonical repository %s" $repository) }}
{{- else }}
{{- $tag := $svcImage.tag | default $glob.imageTag | default .Chart.AppVersion | default "latest" }}
{{- printf "%s:%s" $repository $tag }}
{{- end }}
{{- end }}

{{/*
Image pull policy.
*/}}
{{- define "nohiki-common.imagePullPolicy" -}}
{{- $glob := .Values.global | default dict }}
{{- $globImage := $glob.nohikiImage | default dict }}
{{- .Values.image.pullPolicy | default $globImage.pullPolicy | default "IfNotPresent" }}
{{- end }}

{{/*
App port (HTTP port from service config).
*/}}
{{- define "nohiki-common.appPort" -}}
{{- $service := .Values.service | default dict }}
{{- $service.targetPort | default $service.port | default 8000 }}
{{- end }}

{{/*
Default pod-level security context (non-root, seccomp).
Override per-service via .Values.podSecurityContext.
*/}}
{{- define "nohiki-common.defaultPodSecurityContext" -}}
runAsNonRoot: true
runAsUser: 999
runAsGroup: 999
fsGroup: 999
seccompProfile:
  type: RuntimeDefault
{{- end }}

{{/*
Default container-level security context (hardened).
Override per-service via .Values.securityContext.
*/}}
{{- define "nohiki-common.defaultSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop:
    - ALL
{{- end }}

{{/*
All init containers (user-defined + system-generated).
Combines .Values.initContainers with auto-generated wait-for containers.
*/}}
{{- define "nohiki-common.allInitContainers" -}}
{{- $initContainers := list }}
{{- /* Add user-defined init containers */}}
{{- with .Values.initContainers }}
{{- $initContainers = concat $initContainers . }}
{{- end }}
{{- /* Output combined init containers */}}
{{- if $initContainers }}
{{- toYaml $initContainers }}
{{- end }}
{{- end }}
