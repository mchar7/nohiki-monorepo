{{/*
Volume mount for ML manifest ConfigMap.
Usage: {{ include "nohiki-common.manifestVolumeMount" . | nindent 12 }}
*/}}
{{- define "nohiki-common.manifestVolumeMount" -}}
{{- $m := .Values.mlManifest | default dict }}
{{- if $m.enabled }}
- name: ml-manifest
  mountPath: {{ $m.mountPath | default "/app/data/config/semantic_representation_manifest.json" }}
  subPath: {{ $m.subPath | default "semantic_representation_manifest.json" }}
  readOnly: true
{{- end }}
{{- end }}

{{/*
Volume for ML manifest ConfigMap.
Usage: {{ include "nohiki-common.manifestVolume" . | nindent 8 }}
*/}}
{{- define "nohiki-common.manifestVolume" -}}
{{- $m := .Values.mlManifest | default dict }}
{{- if $m.enabled }}
- name: ml-manifest
  configMap:
    name: {{ $m.configMapName | default "nohiki-ml-manifest" }}
{{- end }}
{{- end }}

{{/*
Deployment template for Nohiki microservices.
Usage: {{ include "nohiki-common.deployment" . }}
*/}}
{{- define "nohiki-common.deployment" -}}
{{- if ne .Values.enabled false }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "nohiki-common.fullname" . }}
  namespace: {{ .Release.Namespace }}
  {{- $otelTls := ((.Values.global | default dict).observability | default dict).otelTls | default dict }}
  {{- $modelEgress := ((.Values.global | default dict).modelEgress | default dict) }}
  {{- $usesModelEgress := ((.Values.llm | default dict).enabled | default false) }}
  labels:
    {{- include "nohiki-common.labels" . | nindent 4 }}
spec:
  revisionHistoryLimit: 3
  {{- $scaling := .Values.scaling | default dict }}
  {{- if not $scaling.enabled }}
  replicas: {{ .Values.replicaCount | default 1 }}
  {{- end }}
  selector:
    matchLabels:
      {{- include "nohiki-common.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      {{- with (include "nohiki-common.podAnnotations" . | fromYaml) }}
      annotations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      labels:
        {{- include "nohiki-common.podLabels" . | nindent 8 }}
    spec:
      serviceAccountName: {{ include "nohiki-common.serviceAccountName" . }}
      automountServiceAccountToken: false
      securityContext:
        {{- if .Values.podSecurityContext }}
        {{- toYaml .Values.podSecurityContext | nindent 8 }}
        {{- else }}
        {{- include "nohiki-common.defaultPodSecurityContext" . | nindent 8 }}
        {{- end }}
      terminationGracePeriodSeconds: {{ .Values.terminationGracePeriodSeconds | default 30 }}
      {{- $initContainers := include "nohiki-common.allInitContainers" . | trim }}
      {{- if $initContainers }}
      initContainers:
        {{- $initContainers | nindent 8 }}
      {{- end }}
      containers:
        - name: {{ .Chart.Name }}
          securityContext:
            {{- if .Values.securityContext }}
            {{- toYaml .Values.securityContext | nindent 12 }}
            {{- else }}
            {{- include "nohiki-common.defaultSecurityContext" . | nindent 12 }}
            {{- end }}
          image: {{ include "nohiki-common.image" . }}
          imagePullPolicy: {{ include "nohiki-common.imagePullPolicy" . }}
          lifecycle:
            preStop:
              exec:
                command:
                  - /bin/sh
                  - -c
                  - sleep 5
          ports:
            - name: http
              containerPort: {{ .Values.service.targetPort | default .Values.service.port | default 8000 }}
              protocol: TCP
          {{- $probes := .Values.probes | default dict }}
          {{- $liveness := $probes.liveness | default dict }}
          {{- if ne ($liveness.enabled | default true) false }}
          livenessProbe:
            {{- include "nohiki-common.probes.liveness" . | trim | nindent 12 }}
          {{- end }}
          {{- $readiness := $probes.readiness | default dict }}
          {{- if ne ($readiness.enabled | default true) false }}
          readinessProbe:
            {{- include "nohiki-common.probes.readiness" . | trim | nindent 12 }}
          {{- end }}
          resources:
            {{- include "nohiki-common.resources" . | trim | nindent 12 }}
          env:
            {{- include "nohiki-common.env.all" . | trim | nindent 12 }}
          volumeMounts:
            - name: tmp
              mountPath: /tmp
            {{- include "nohiki-common.secretsVolumeMount" . | trim | nindent 12 }}
            {{- include "nohiki-common.manifestVolumeMount" . | trim | nindent 12 }}
            {{- if $otelTls.enabled }}
            - name: otel-ca
              mountPath: {{ required (printf "%s requires global.observability.otelTls.mountPath" (include "nohiki-common.name" .)) $otelTls.mountPath }}
              readOnly: true
            {{- end }}
            {{- if $usesModelEgress }}
            - name: model-egress-ca
              mountPath: {{ $modelEgress.caMountPath | default "/etc/nohiki/model-egress" }}
              readOnly: true
            {{- end }}
            {{- with .Values.extraVolumeMounts }}
            {{- toYaml . | nindent 12 }}
            {{- end }}
        {{- with .Values.sidecars }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
      volumes:
        - name: tmp
          emptyDir:
            sizeLimit: 100Mi
        {{- include "nohiki-common.secretsVolume" . | trim | nindent 8 }}
        {{- include "nohiki-common.manifestVolume" . | trim | nindent 8 }}
        {{- if $otelTls.enabled }}
        - name: otel-ca
          secret:
            secretName: {{ required (printf "%s requires global.observability.otelTls.secretName" (include "nohiki-common.name" .)) $otelTls.secretName }}
            items:
              - key: ca.crt
                path: ca.crt
        {{- end }}
        {{- if $usesModelEgress }}
        - name: model-egress-ca
          secret:
            secretName: {{ $modelEgress.caSecretName | default (printf "%s-model-egress-ca" .Release.Name) }}
            items:
              - key: ca.crt
                path: ca.crt
        {{- end }}
        {{- with .Values.extraVolumes }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
      {{- with .Values.topologySpreadConstraints }}
      topologySpreadConstraints:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.nodeSelector }}
      nodeSelector:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.affinity }}
      affinity:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.tolerations }}
      tolerations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
{{- end }}
{{- end }}
