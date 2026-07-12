{{/*
NetworkPolicy template.
In local k3s mode (infra on host), NetworkPolicy is typically disabled since
services need to reach host IP for PostgreSQL/Redis/Kafka/RustFS/Qdrant.
In production (in-cluster infra), this provides a proper deny-all + allowlist.
*/}}
{{- define "nohiki-common.networkpolicy" -}}
{{- if ne .Values.enabled false }}
{{- $np := .Values.networkPolicy | default dict }}
{{- if ne ($np.enabled | default true) false }}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "nohiki-common.fullname" . }}
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "nohiki-common.labels" . | nindent 4 }}
spec:
  podSelector:
    matchLabels:
      {{- include "nohiki-common.selectorLabels" . | nindent 6 }}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    {{- $monitoring := .Values.monitoring | default dict }}
    {{- $scaling := .Values.scaling | default dict }}
    {{- $globalKeda := ((.Values.global | default dict).keda | default dict) }}
    {{- $httpAddon := $globalKeda.httpAddon | default dict }}
    {{- $hasGatewayIngress := ($np.allowGatewayIngress | default false) }}
    {{- $hasBffIngress := ($np.allowBffIngress | default false) }}
    {{- $hasKedaIngress := and $httpAddon.enabled $scaling.enabled (eq ($scaling.type | default "") "http") }}
    {{- if or $monitoring.enabled $hasGatewayIngress $hasBffIngress $hasKedaIngress }}
    {{- if $monitoring.enabled }}
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: {{ .Release.Namespace }}
          podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
              operator.prometheus.io/name: {{ .Release.Name }}-kube-prometheus-stack-prometheus
      ports:
        - port: {{ .Values.service.port | default 8000 }}
          protocol: TCP
    {{- end }}
    {{- if $hasGatewayIngress }}
    - from:
        - podSelector:
            matchLabels:
              gateway.networking.k8s.io/gateway-name: {{ .Release.Name }}-gateway
      ports:
        - port: {{ .Values.service.port | default 8000 }}
          protocol: TCP
    {{- end }}
    {{- if $hasBffIngress }}
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: bff-service
              app.kubernetes.io/instance: {{ .Release.Name }}
      ports:
        - port: {{ .Values.service.port | default 8000 }}
          protocol: TCP
    {{- end }}
    {{- if $hasKedaIngress }}
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: nohiki-http-interceptor
              app.kubernetes.io/part-of: nohiki
      ports:
        - port: {{ .Values.service.port | default 8000 }}
          protocol: TCP
    {{- end }}
    {{- else }}
    []
    {{- end }}
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
    {{- $global := .Values.global | default dict }}
    {{- $modelEgress := $global.modelEgress | default dict }}
    {{- $usesModelEgress := ((.Values.llm | default dict).enabled | default false) }}
    {{- $globalNp := $global.networkPolicy | default dict }}
    {{- $managed := $globalNp.managedEgress | default dict }}
    {{- $db := .Values.database | default dict }}
    {{- if $db.enabled }}
    - to:
        - podSelector:
            matchLabels:
              cnpg.io/cluster: nohiki-pg
      ports:
        - port: 5432
          protocol: TCP
    {{- with (($managed.database | default dict).cidrs | default list) }}
    - to:
        {{- range . }}
        - ipBlock:
            cidr: {{ . | quote }}
            {{- if eq . "0.0.0.0/0" }}
            except:
              - 10.0.0.0/8
              - 172.16.0.0/12
              - 192.168.0.0/16
            {{- end }}
        {{- end }}
      ports:
        - port: {{ (($global.database | default dict).port | default 5432) }}
          protocol: TCP
    {{- end }}
    {{- end }}
    {{- $kafka := .Values.kafka | default dict }}
    {{- if $kafka.enabled }}
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: kafka
      ports:
        - port: 9092
          protocol: TCP
        - port: 29092
          protocol: TCP
    {{- with (($managed.kafka | default dict).cidrs | default list) }}
    - to:
        {{- range . }}
        - ipBlock:
            cidr: {{ . | quote }}
            {{- if eq . "0.0.0.0/0" }}
            except:
              - 10.0.0.0/8
              - 172.16.0.0/12
              - 192.168.0.0/16
            {{- end }}
        {{- end }}
      ports:
        - port: {{ (($global.kafka | default dict).port | default 9092) }}
          protocol: TCP
    {{- end }}
    {{- end }}
    {{- $redis := .Values.redis | default dict }}
    {{- if $redis.enabled }}
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: valkey
      ports:
        - port: 6379
          protocol: TCP
    {{- with (($managed.redis | default dict).cidrs | default list) }}
    - to:
        {{- range . }}
        - ipBlock:
            cidr: {{ . | quote }}
            {{- if eq . "0.0.0.0/0" }}
            except:
              - 10.0.0.0/8
              - 172.16.0.0/12
              - 192.168.0.0/16
            {{- end }}
        {{- end }}
      ports:
        - port: {{ (($global.redis | default dict).port | default 6379) }}
          protocol: TCP
    {{- end }}
    {{- end }}
    {{- $s3 := .Values.s3 | default dict }}
    {{- if $s3.enabled }}
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: rustfs
      ports:
        - port: 9000
          protocol: TCP
    {{- with (($managed.s3 | default dict).cidrs | default list) }}
    - to:
        {{- range . }}
        - ipBlock:
            cidr: {{ . | quote }}
            {{- if eq . "0.0.0.0/0" }}
            except:
              - 10.0.0.0/8
              - 172.16.0.0/12
              - 192.168.0.0/16
            {{- end }}
        {{- end }}
      ports:
        - port: {{ (($global.s3 | default dict).port | default 443) }}
          protocol: TCP
    {{- end }}
    {{- end }}
    {{- $qdrant := .Values.qdrant | default dict }}
    {{- if $qdrant.enabled }}
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: qdrant
      ports:
        - port: 6334
          protocol: TCP
    {{- with (($managed.qdrant | default dict).cidrs | default list) }}
    - to:
        {{- range . }}
        - ipBlock:
            cidr: {{ . | quote }}
            {{- if eq . "0.0.0.0/0" }}
            except:
              - 10.0.0.0/8
              - 172.16.0.0/12
              - 192.168.0.0/16
            {{- end }}
        {{- end }}
      ports:
        - port: {{ (($global.qdrant | default dict).grpcPort | default 6334) }}
          protocol: TCP
    {{- end }}
    {{- end }}
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: otel-collector
              app.kubernetes.io/instance: {{ .Release.Name }}
      ports:
        - port: 4317
          protocol: TCP
    {{- if ($np.allowAuthEgress | default false) }}
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: user-auth-service
              app.kubernetes.io/instance: {{ .Release.Name }}
      ports:
        - port: 8000
          protocol: TCP
    {{- end }}
    {{- if $usesModelEgress }}
    - to:
        - podSelector:
            matchLabels:
              gateway.networking.k8s.io/gateway-name: {{ .Release.Name }}-model-egress
      ports:
        - port: {{ $modelEgress.listenerPort | default 8443 }}
          protocol: TCP
    {{- end }}
    {{- if or (not $usesModelEgress) ($np.allowExtraEgressWithModelEgress | default false) }}
    {{- range $rule := ($np.extraEgress | default list) }}
    {{- range $peer := ($rule.to | default list) }}
    {{- with $peer.ipBlock }}
    {{- if eq (.cidr | default "") "0.0.0.0/0" }}
    {{- $_ := set . "except" (list "10.0.0.0/8" "100.64.0.0/10" "127.0.0.0/8" "169.254.0.0/16" "172.16.0.0/12" "192.168.0.0/16") }}
    {{- end }}
    {{- end }}
    {{- end }}
    {{- end }}
    {{- with ($np.extraEgress | default list) }}
    {{- toYaml . | nindent 4 }}
    {{- end }}
    {{- end }}
{{- end }}
{{- end }}
{{- end }}
