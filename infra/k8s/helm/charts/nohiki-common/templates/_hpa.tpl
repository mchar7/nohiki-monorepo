{{/*
KEDA ScaledObject dispatcher - routes to appropriate template based on scaling.type.
Usage: {{ include "nohiki-common.keda-scaler" . }}
*/}}
{{- define "nohiki-common.keda-scaler" -}}
{{- $scaling := .Values.scaling | default dict }}
{{- if $scaling.enabled }}
{{- $type := $scaling.type | default "http" }}
{{- if eq $type "http" }}
{{ include "nohiki-common.kedaScaledObject.http" . }}
{{- else if eq $type "kafka" }}
{{ include "nohiki-common.kedaScaledObject.kafka" . }}
{{- else if eq $type "multi" }}
{{ include "nohiki-common.kedaScaledObject.multi" . }}
{{- else if eq $type "prometheus" }}
{{ include "nohiki-common.kedaScaledObject.prometheus" . }}
{{- end }}
{{- end }}
{{- end }}

{{/*
KEDA HTTPScaledObject for HTTP-based services.
Usage: {{ include "nohiki-common.kedaScaledObject.http" . }}
*/}}
{{- define "nohiki-common.kedaScaledObject.http" -}}
{{- if ne .Values.enabled false }}
{{- $scaling := .Values.scaling | default dict }}
{{- $http := $scaling.http | default dict }}
{{- $glob := .Values.global | default dict }}
{{- $globScaling := $glob.scaling | default dict }}
apiVersion: http.keda.sh/v1alpha1
kind: HTTPScaledObject
metadata:
  name: {{ include "nohiki-common.fullname" . }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "nohiki-common.labels" . | nindent 4 }}
spec:
  hosts:
    - {{ include "nohiki-common.fullname" . }}.{{ .Release.Namespace }}.svc.cluster.local
    {{- range $http.additionalHosts }}
    - {{ . }}
    {{- end }}
  {{- if $http.pathPrefixes }}
  pathPrefixes:
    {{- range $http.pathPrefixes }}
    - {{ . }}
    {{- end }}
  {{- end }}
  targetPendingRequests: {{ $http.targetPendingRequests | default 100 }}
  scaleTargetRef:
    name: {{ include "nohiki-common.fullname" . }}
    kind: Deployment
    apiVersion: apps/v1
    service: {{ include "nohiki-common.fullname" . }}
    port: {{ .Values.service.port | default 8000 }}
  replicas:
    min: {{ $scaling.minReplicas | default $globScaling.minReplicas | default 0 }}
    max: {{ $scaling.maxReplicas | default $globScaling.maxReplicas | default 10 }}
  scaledownPeriod: {{ $scaling.cooldownPeriod | default $globScaling.cooldownPeriod | default 300 }}
{{- end }}
{{- end }}

{{/*
KEDA ScaledObject for Kafka consumer services.
Usage: {{ include "nohiki-common.kedaScaledObject.kafka" . }}
*/}}
{{- define "nohiki-common.kedaScaledObject.kafka" -}}
{{- if ne .Values.enabled false }}
{{- $scaling := .Values.scaling | default dict }}
{{- $kafka := $scaling.kafka | default dict }}
{{- $glob := .Values.global | default dict }}
{{- $globScaling := $glob.scaling | default dict }}
{{- $globKafka := $glob.kafka | default dict }}
{{- $authenticationRef := $kafka.authenticationRef | default "" }}
{{- $security := $globKafka.security | default dict }}
{{- $sasl := $security.sasl | default dict }}
{{- if and (not $authenticationRef) $sasl.secretName }}
{{- $authenticationRef = printf "%s-kafka-auth" $.Release.Name }}
{{- end }}
{{- $kafkaTLS := eq ($security.protocol | default "") "SASL_SSL" }}
{{- $kedaConsumerGroup := $kafka.consumerGroup | default $.Values.kafka.consumerGroup | default (include "nohiki-common.name" $) }}
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
  minReplicaCount: {{ $scaling.minReplicas | default $globScaling.minReplicas | default 0 }}
  maxReplicaCount: {{ $scaling.maxReplicas | default $globScaling.maxReplicas | default 10 }}
  {{- if eq (int ($scaling.minReplicas | default $globScaling.minReplicas | default 0)) 0 }}
  idleReplicaCount: 0
  {{- end }}
  triggers:
    {{- if $kafka.topics }}
    {{- range $kafka.topics }}
    - type: kafka
      metadata:
        bootstrapServers: {{ $globKafka.bootstrapServers | default "nohiki-kafka:9092" }}
        consumerGroup: {{ $kedaConsumerGroup }}
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
    {{- else }}
    - type: kafka
      metadata:
        bootstrapServers: {{ $globKafka.bootstrapServers | default "nohiki-kafka:9092" }}
        consumerGroup: {{ $kedaConsumerGroup }}
        lagThreshold: {{ $kafka.lagThreshold | default "10" | quote }}
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
{{- $globPrometheus := $glob.prometheus | default dict }}
{{- $authenticationRef := $kafka.authenticationRef | default "" }}
{{- $security := $globKafka.security | default dict }}
{{- $sasl := $security.sasl | default dict }}
{{- if and (not $authenticationRef) $sasl.secretName }}
{{- $authenticationRef = printf "%s-kafka-auth" $.Release.Name }}
{{- end }}
{{- $kafkaTLS := eq ($security.protocol | default "") "SASL_SSL" }}
{{- $kedaConsumerGroup := $kafka.consumerGroup | default $.Values.kafka.consumerGroup | default (include "nohiki-common.name" $) }}
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
  minReplicaCount: {{ $scaling.minReplicas | default $globScaling.minReplicas | default 0 }}
  maxReplicaCount: {{ $scaling.maxReplicas | default $globScaling.maxReplicas | default 10 }}
  {{- if eq (int ($scaling.minReplicas | default $globScaling.minReplicas | default 0)) 0 }}
  idleReplicaCount: 0
  {{- end }}
  triggers:
    {{- /* Kafka triggers */}}
    {{- if $kafka.topics }}
    {{- range $kafka.topics }}
    - type: kafka
      metadata:
        bootstrapServers: {{ $globKafka.bootstrapServers | default "nohiki-kafka:9092" }}
        consumerGroup: {{ $kedaConsumerGroup }}
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
  minReplicaCount: {{ $scaling.minReplicas | default $globScaling.minReplicas | default 0 }}
  maxReplicaCount: {{ $scaling.maxReplicas | default $globScaling.maxReplicas | default 10 }}
  {{- if eq (int ($scaling.minReplicas | default $globScaling.minReplicas | default 0)) 0 }}
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
