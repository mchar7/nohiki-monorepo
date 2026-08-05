{{/*
KEDA ScaledObject dispatcher - routes to appropriate template based on scaling.type.
Usage: {{ include "nohiki-common.keda-scaler" . }}
*/}}
{{- define "nohiki-common.keda-scaler" -}}
{{- $scaling := .Values.scaling | default dict }}
{{- if and $scaling.enabled (not $scaling.excluded) }}
{{- $type := $scaling.type | default "http" }}
{{- if eq $type "kafka" }}
{{ include "nohiki-common.kedaScaledObject.kafka" . }}
{{- else if eq $type "multi" }}
{{ include "nohiki-common.kedaScaledObject.multi" . }}
{{- else if eq $type "prometheus" }}
{{ include "nohiki-common.kedaScaledObject.prometheus" . }}
{{- end }}
{{- end }}
{{- end }}


{{/*
KEDA ScaledObject for Kafka consumer services.
Usage: {{ include "nohiki-common.kedaScaledObject.kafka" . }}
*/}}
{{- define "nohiki-common.kedaScaledObject.kafka" -}}
{{- $scaling := .Values.scaling | default dict }}
{{- $kafka := $scaling.kafka | default dict }}
{{- if and (ne .Values.enabled false) $kafka.topics }}
{{- $glob := .Values.global | default dict }}
{{- $globScaling := $glob.scaling | default dict }}
{{- $globKafka := $glob.kafka | default dict }}
{{- $bootstrapGate := $globKafka.bootstrapGate | default dict }}
{{- $security := $globKafka.security | default dict }}
{{- $sasl := $security.sasl | default dict }}
{{- $authenticationRef := "" }}
{{- if $sasl.secretName }}
{{- $authenticationRef = printf "%s-kafka-auth" $.Release.Name }}
{{- end }}
{{- $kafkaTLS := eq ($security.protocol | default "") "SASL_SSL" }}
{{- $kedaConsumerGroup := $kafka.consumerGroup | default $.Values.kafka.consumerGroup | default (include "nohiki-common.name" $) }}
{{- $minReplicas := $globScaling.minReplicas | default 0 }}
{{- if hasKey $scaling "minReplicas" }}
{{- $minReplicas = $scaling.minReplicas }}
{{- end }}
{{- $maxReplicas := int ($scaling.maxReplicas | default $globScaling.maxReplicas | default 10) }}
{{- $partitionCount := int ($kafka.partitionCount | default $globKafka.partitionCount | default 3) }}
{{- if gt $maxReplicas $partitionCount }}
{{- $maxReplicas = $partitionCount }}
{{- end }}
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: {{ include "nohiki-common.fullname" . }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "nohiki-common.labels" . | nindent 4 }}
  {{- if $bootstrapGate.enabled }}
  annotations:
    helm.sh/hook: post-install,post-upgrade
    helm.sh/hook-weight: "0"
    helm.sh/hook-delete-policy: before-hook-creation,hook-failed
  {{- end }}
spec:
  scaleTargetRef:
    name: {{ include "nohiki-common.fullname" . }}
  pollingInterval: {{ $scaling.pollingInterval | default 15 }}
  cooldownPeriod: {{ $scaling.cooldownPeriod | default $globScaling.cooldownPeriod | default 300 }}
  minReplicaCount: {{ $minReplicas }}
  maxReplicaCount: {{ $maxReplicas }}
  {{- if eq (int $minReplicas) 0 }}
  idleReplicaCount: 0
  {{- end }}
  triggers:
    {{- range $kafka.topics }}
    - type: kafka
      metadata:
        bootstrapServers: {{ $globKafka.bootstrapServers | default "nohiki-kafka:9092" }}
        consumerGroup: {{ .consumerGroup | default $kedaConsumerGroup }}
        topic: {{ .name }}
        lagThreshold: {{ .lagThreshold | default $kafka.lagThreshold | default "10" | quote }}
        allowIdleConsumers: "true"
        {{- if $kafkaTLS }}
        tls: enable
        {{- end }}
        {{- if $kafka.offsetResetPolicy }}
        offsetResetPolicy: {{ $kafka.offsetResetPolicy | quote }}
        {{- end }}
      {{- if $authenticationRef }}
      authenticationRef:
        name: {{ $authenticationRef }}
      {{- end }}
    {{- end }}
{{- end }}
{{- end }}

{{/*
KEDA ScaledObject with multiple triggers (Kafka + Prometheus).
Usage: {{ include "nohiki-common.kedaScaledObject.multi" . }}
*/}}
{{- define "nohiki-common.kedaScaledObject.multi" -}}
{{- if ne .Values.enabled false }}
{{- $scaling := .Values.scaling | default dict }}
{{- $kafka := $scaling.kafka | default dict }}
{{- $prometheus := $scaling.prometheus | default dict }}
{{- $glob := .Values.global | default dict }}
{{- $globScaling := $glob.scaling | default dict }}
{{- $globKafka := $glob.kafka | default dict }}
{{- $bootstrapGate := $globKafka.bootstrapGate | default dict }}
{{- $globPrometheus := $glob.prometheus | default dict }}
{{- $security := $globKafka.security | default dict }}
{{- $sasl := $security.sasl | default dict }}
{{- $authenticationRef := "" }}
{{- if $sasl.secretName }}
{{- $authenticationRef = printf "%s-kafka-auth" $.Release.Name }}
{{- end }}
{{- $kafkaTLS := eq ($security.protocol | default "") "SASL_SSL" }}
{{- $kedaConsumerGroup := $kafka.consumerGroup | default $.Values.kafka.consumerGroup | default (include "nohiki-common.name" $) }}
{{- $minReplicas := $globScaling.minReplicas | default 0 }}
{{- if hasKey $scaling "minReplicas" }}
{{- $minReplicas = $scaling.minReplicas }}
{{- end }}
{{- $maxReplicas := int ($scaling.maxReplicas | default $globScaling.maxReplicas | default 10) }}
{{- $partitionCount := int ($kafka.partitionCount | default $globKafka.partitionCount | default 3) }}
{{- if gt $maxReplicas $partitionCount }}
{{- $maxReplicas = $partitionCount }}
{{- end }}
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: {{ include "nohiki-common.fullname" . }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "nohiki-common.labels" . | nindent 4 }}
  {{- if $bootstrapGate.enabled }}
  annotations:
    helm.sh/hook: post-install,post-upgrade
    helm.sh/hook-weight: "0"
    helm.sh/hook-delete-policy: before-hook-creation,hook-failed
  {{- end }}
spec:
  scaleTargetRef:
    name: {{ include "nohiki-common.fullname" . }}
  pollingInterval: {{ $scaling.pollingInterval | default 15 }}
  cooldownPeriod: {{ $scaling.cooldownPeriod | default $globScaling.cooldownPeriod | default 300 }}
  minReplicaCount: {{ $minReplicas }}
  maxReplicaCount: {{ $maxReplicas }}
  {{- if eq (int $minReplicas) 0 }}
  idleReplicaCount: 0
  {{- end }}
  triggers:
    {{- /* Kafka triggers */}}
    {{- if $kafka.topics }}
    {{- range $kafka.topics }}
    - type: kafka
      metadata:
        bootstrapServers: {{ $globKafka.bootstrapServers | default "nohiki-kafka:9092" }}
        consumerGroup: {{ .consumerGroup | default $kedaConsumerGroup }}
        topic: {{ .name }}
        lagThreshold: {{ .lagThreshold | default $kafka.lagThreshold | default "10" | quote }}
        allowIdleConsumers: "true"
        {{- if $kafkaTLS }}
        tls: enable
        {{- end }}
      {{- if $authenticationRef }}
      authenticationRef:
        name: {{ $authenticationRef }}
      {{- end }}
    {{- end }}
    {{- end }}
    {{- /* Prometheus trigger */}}
    {{- if $prometheus.query }}
    - type: prometheus
      metadata:
        serverAddress: {{ $globPrometheus.serverAddress | default "http://prometheus-server.monitoring.svc.cluster.local" }}
        metricName: {{ $prometheus.metricName | default "custom_metric" }}
        query: {{ $prometheus.query | quote }}
        threshold: {{ $prometheus.threshold | default "10" | quote }}
        {{- if $prometheus.activationThreshold }}
        activationThreshold: {{ $prometheus.activationThreshold | quote }}
        {{- end }}
    {{- end }}
{{- end }}
{{- end }}

{{/*
KEDA ScaledObject for Prometheus-based scaling.
Usage: {{ include "nohiki-common.kedaScaledObject.prometheus" . }}
*/}}
{{- define "nohiki-common.kedaScaledObject.prometheus" -}}
{{- if ne .Values.enabled false }}
{{- $scaling := .Values.scaling | default dict }}
{{- $prometheus := $scaling.prometheus | default dict }}
{{- $glob := .Values.global | default dict }}
{{- $globScaling := $glob.scaling | default dict }}
{{- $globPrometheus := $glob.prometheus | default dict }}
{{- $minReplicas := $globScaling.minReplicas | default 0 }}
{{- if hasKey $scaling "minReplicas" }}
{{- $minReplicas = $scaling.minReplicas }}
{{- end }}
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: {{ include "nohiki-common.fullname" . }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "nohiki-common.labels" . | nindent 4 }}
spec:
  scaleTargetRef:
    name: {{ include "nohiki-common.fullname" . }}
  pollingInterval: {{ $scaling.pollingInterval | default 15 }}
  cooldownPeriod: {{ $scaling.cooldownPeriod | default $globScaling.cooldownPeriod | default 300 }}
  minReplicaCount: {{ $minReplicas }}
  maxReplicaCount: {{ $scaling.maxReplicas | default $globScaling.maxReplicas | default 10 }}
  {{- if eq (int $minReplicas) 0 }}
  idleReplicaCount: 0
  {{- end }}
  triggers:
    - type: prometheus
      metadata:
        serverAddress: {{ $globPrometheus.serverAddress | default "http://prometheus-server.monitoring.svc.cluster.local" }}
        metricName: {{ $prometheus.metricName | default "custom_metric" }}
        query: {{ $prometheus.query | quote }}
        threshold: {{ $prometheus.threshold | default "10" | quote }}
        {{- if $prometheus.activationThreshold }}
        activationThreshold: {{ $prometheus.activationThreshold | quote }}
        {{- end }}
{{- end }}
{{- end }}

{{/*
Fallback HPA when KEDA is not available.
Usage: {{ include "nohiki-common.hpa" . }}
*/}}
{{- define "nohiki-common.hpa" -}}
{{- $autoscaling := .Values.autoscaling | default dict }}
{{- if and (ne .Values.enabled false) $autoscaling.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ include "nohiki-common.fullname" . }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "nohiki-common.labels" . | nindent 4 }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ include "nohiki-common.fullname" . }}
  minReplicas: {{ $autoscaling.minReplicas | default 1 }}
  maxReplicas: {{ $autoscaling.maxReplicas | default 10 }}
  metrics:
    {{- if $autoscaling.targetCPUUtilizationPercentage }}
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: {{ $autoscaling.targetCPUUtilizationPercentage }}
    {{- end }}
    {{- if $autoscaling.targetMemoryUtilizationPercentage }}
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: {{ $autoscaling.targetMemoryUtilizationPercentage }}
    {{- end }}
{{- end }}
{{- end }}
