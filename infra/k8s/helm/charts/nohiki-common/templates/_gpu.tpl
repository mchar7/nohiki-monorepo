{{/*
NVIDIA device plugin DaemonSet.

Production-gated GPU enablement for the self-managed AKS GPU node pool. AKS
auto-installs the NVIDIA driver on the GPU pool; this DaemonSet runs the stable
NVIDIA k8s-device-plugin so that `nvidia.com/gpu` becomes an allocatable
resource on GPU nodes. It selects the Terraform GPU pool label and tolerates the
pool taint so it only lands on GPU nodes.

Rendered only when `.Values.gpuDevicePlugin.enabled` is true, so local/staging
CPU deployments are unaffected.

Usage (from an application chart template):
  {{ include "nohiki-common.nvidiaDevicePlugin" . }}
*/}}
{{- define "nohiki-common.nvidiaDevicePlugin" -}}
{{- $gpu := .Values.gpuDevicePlugin | default dict }}
{{- if $gpu.enabled }}
{{- $image := $gpu.image | default dict }}
{{- $repository := $image.repository | default "nvcr.io/nvidia/k8s-device-plugin" }}
{{- $tag := required (printf "%s requires gpuDevicePlugin.image.tag pinned by digest" (include "nohiki-common.name" .)) $image.tag }}
{{- if not (regexMatch "@sha256:[0-9a-f]{64}$" $tag) }}
{{- fail (printf "gpuDevicePlugin image must be pinned by immutable digest, got: %s" $tag) }}
{{- end }}
{{- $name := printf "%s-%s" (include "nohiki-common.fullname" .) ($gpu.name | default "nvidia-device-plugin") | trunc 63 | trimSuffix "-" }}
{{- $res := $gpu.resources | default dict }}
{{- $resReq := $res.requests | default dict }}
{{- $resLim := $res.limits | default dict }}
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: {{ $name }}
  namespace: {{ .Release.Namespace }}
  labels:
    app.kubernetes.io/name: {{ include "nohiki-common.name" . }}
    app.kubernetes.io/instance: {{ .Release.Name }}
    app.kubernetes.io/component: nvidia-device-plugin
    app.kubernetes.io/part-of: nohiki
    app.kubernetes.io/managed-by: {{ .Release.Service }}
    helm.sh/chart: {{ include "nohiki-common.chart" . }}
    environment: {{ (.Values.global | default dict).environment | default "dev" }}
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ include "nohiki-common.name" . }}
      app.kubernetes.io/instance: {{ .Release.Name }}
      app.kubernetes.io/component: nvidia-device-plugin
  updateStrategy:
    type: {{ $gpu.updateStrategy | default "RollingUpdate" }}
  template:
    metadata:
      labels:
        app.kubernetes.io/name: {{ include "nohiki-common.name" . }}
        app.kubernetes.io/instance: {{ .Release.Name }}
        app.kubernetes.io/component: nvidia-device-plugin
        app.kubernetes.io/part-of: nohiki
    spec:
      # Reserve the plugin so it survives node pressure and is rescheduled first.
      priorityClassName: {{ $gpu.priorityClassName | default "system-node-critical" }}
      # The plugin talks to kubelet over a unix socket, never the API server.
      automountServiceAccountToken: false
      containers:
        - name: nvidia-device-plugin
          image: {{ printf "%s:%s" $repository $tag }}
          imagePullPolicy: {{ $image.pullPolicy | default "IfNotPresent" }}
          # Must run as root to create the plugin socket in the kubelet dir.
          # Everything else is hardened to match the platform container baseline.
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop:
                - ALL
            seccompProfile:
              type: RuntimeDefault
          resources:
            requests:
              cpu: {{ $resReq.cpu | default "50m" }}
              memory: {{ $resReq.memory | default "30Mi" }}
            limits:
              cpu: {{ $resLim.cpu | default "100m" }}
              memory: {{ $resLim.memory | default "60Mi" }}
          volumeMounts:
            - name: device-plugin
              mountPath: /var/lib/kubelet/device-plugins
      volumes:
        - name: device-plugin
          hostPath:
            path: /var/lib/kubelet/device-plugins
            type: Directory
      nodeSelector:
        {{- toYaml ($gpu.nodeSelector | default (dict "workload" "nohiki-ml-gpu")) | nindent 8 }}
      tolerations:
        {{- toYaml ($gpu.tolerations | default (list (dict "key" "sku" "operator" "Equal" "value" "gpu" "effect" "NoSchedule"))) | nindent 8 }}
{{- end }}
{{- end }}
