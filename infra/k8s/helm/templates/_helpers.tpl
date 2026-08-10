{{/*
Umbrella chart helpers.
Service-level helpers live in nohiki-common library chart.
These are only for umbrella-level templates (secrets.yaml, ingressroute.yaml, jobs, cronjobs, etc.).
*/}}

{{/*
Construct a full image reference for Job/CronJob templates in the umbrella chart.
Mirrors the nohiki-common.image helper logic for consistent registry/owner/repo handling.

Usage:
  {{- $img := include "nohiki.jobImage" (dict "glob" .Values.global "cfg" $cfg "default" "my-image") | quote }}

Args (passed as a dict):
  glob:    .Values.global  - provides nohikiImage registry, owner, repositoryName, and imageTag
  cfg:     service config block - provides image.repository and image.tag overrides
  default: fallback image name when cfg.image.repository is absent
*/}}
{{- define "nohiki.jobImage" -}}
{{- $glob := index . "glob" | default dict }}
{{- $globImage := $glob.nohikiImage | default dict }}
{{- $cfg := index . "cfg" | default dict }}
{{- $cfgImage := $cfg.image | default dict }}
{{- $imageName := $cfgImage.repository | default (index . "default") }}
{{- $registry := $cfgImage.registry | default $globImage.registry | default "" }}
{{- $owner := $cfgImage.owner | default $globImage.owner | default "" }}
{{- $repoName := $cfgImage.repositoryName | default $globImage.repositoryName | default "" }}
{{- $repository := $imageName }}
{{- if and $registry $owner $repoName }}
{{- $repository = printf "%s/%s/%s/%s" $registry $owner $repoName $imageName }}
{{- else if $registry }}
{{- $repository = printf "%s/%s" $registry $imageName }}
{{- end }}
{{- $digests := $glob.imageDigests | default dict }}
{{- $digest := index $digests $imageName | default "" }}
{{- if $digest }}
{{- if not (regexMatch "^sha256:[0-9a-f]{64}$" $digest) }}
{{- fail (printf "invalid digest for image %s: %s" $imageName $digest) }}
{{- end }}
{{- printf "%s@%s" $repository $digest }}
{{- else if eq ($glob.environment | default "") "prod" }}
{{- fail (printf "production image digest is required for canonical repository %s" $repository) }}
{{- else }}
{{- $tag := $cfgImage.tag | default $glob.imageTag | default "latest" }}
{{- printf "%s:%s" $repository $tag }}
{{- end }}
{{- end }}

{{/*
Resolve imagePullPolicy for Job/CronJob templates, falling back to global policy.

Usage:
  imagePullPolicy: {{ include "nohiki.jobImagePullPolicy" (dict "glob" .Values.global "cfg" $cfg) }}

Args:
  glob: .Values.global  - provides nohikiImage.pullPolicy fallback
  cfg:  service config block - provides image.pullPolicy override
*/}}
{{- define "nohiki.jobImagePullPolicy" -}}
{{- $glob := index . "glob" | default dict }}
{{- $globImage := $glob.nohikiImage | default dict }}
{{- $cfg := index . "cfg" | default dict }}
{{- $cfgImage := $cfg.image | default dict }}
{{- $cfgImage.pullPolicy | default $globImage.pullPolicy | default "IfNotPresent" -}}
{{- end -}}

{{- define "nohiki.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "nohiki.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "nohiki.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "nohiki.labels" -}}
helm.sh/chart: {{ include "nohiki.chart" . }}
app.kubernetes.io/name: {{ include "nohiki.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: nohiki
{{- end -}}
