{{/*
ml-compute accelerator: the SINGLE operator switch for CPU vs CUDA.

An application chart exposes one field, `.Values.accelerator.mode` (cpu|cuda),
and calls `nohiki-common.accelerator.normalize` at the top of every template that
depends on GPU scheduling (Deployment, NVIDIA device plugin). The normalizer then
DERIVES, authoritatively and coherently, all of:
  - the image variant   (.Values.image.name)
  - the GPU resource    (.Values.resources.gpu -> nvidia.com/gpu)
  - the pod placement   (.Values.nodeSelector, .Values.tolerations)
  - the device plugin   (.Values.gpuDevicePlugin.enabled)
  - the compute backend (env {PREFIX}PROCESSING__COMPUTE_BACKEND)
so operators never coordinate those five/six fields by hand.

  cpu  (default): CPU image, no nvidia.com/gpu, no GPU selector/toleration, device
                  plugin off, no compute-backend env (the service defaults to CPU).
  cuda:           GPU image variant, one nvidia.com/gpu (configurable), GPU
                  node-pool selector + taint toleration, device plugin on, gpu
                  compute backend. Fails render unless the GPU image digest is
                  pinned in global.imageDigests.

Invalid configurations fail render: an unknown mode, cuda without a pinned GPU
image digest, or cpu alongside an explicitly requested GPU artifact.
*/}}

{{/*
Resolve and validate the accelerator mode. Returns "cpu" or "cuda".
*/}}
{{- define "nohiki-common.accelerator.mode" -}}
{{- $acc := .Values.accelerator | default dict -}}
{{- $mode := $acc.mode | default "cpu" -}}
{{- if not (has $mode (list "cpu" "cuda")) -}}
{{- fail (printf "%s: accelerator.mode must be \"cpu\" or \"cuda\", got %q" (include "nohiki-common.name" .) $mode) -}}
{{- end -}}
{{- $mode -}}
{{- end -}}

{{/*
Rewrite .Values.extraEnv so exactly one {PREFIX}PROCESSING__COMPUTE_BACKEND entry
exists (or none). Args: dict "root" $ "name" <env name> "value" <backend|"">.
An empty/absent value strips the entry (CPU relies on the service default).
*/}}
{{- define "nohiki-common.accelerator.backendEnv" -}}
{{- $root := .root -}}
{{- $name := .name -}}
{{- $value := .value | default "" -}}
{{- $out := list -}}
{{- if $value -}}
{{- $out = append $out (dict "name" $name "value" $value) -}}
{{- end -}}
{{- range $root.Values.extraEnv | default list -}}
{{- if ne .name $name -}}
{{- $out = append $out . -}}
{{- end -}}
{{- end -}}
{{- $_ := set $root.Values "extraEnv" $out -}}
{{- end -}}

{{/*
Derive every GPU-related field from .Values.accelerator.mode. Idempotent and
guarded to run exactly once per render so validation sees the operator's original
intent. Call before nohiki-common.deployment / nohiki-common.nvidiaDevicePlugin.
*/}}
{{- define "nohiki-common.accelerator.normalize" -}}
{{- if not .Values.__acceleratorNormalized -}}
{{- $mode := include "nohiki-common.accelerator.mode" . | trim -}}
{{- $acc := .Values.accelerator | default dict -}}
{{- $res := .Values.resources | default dict -}}
{{- $plugin := .Values.gpuDevicePlugin | default dict -}}
{{- $origGpu := int ($res.gpu | default 0) -}}
{{- $origPluginEnabled := $plugin.enabled | default false -}}
{{- $prefix := .Values.envPrefix | default "" -}}
{{- $backendEnvName := printf "%sPROCESSING__COMPUTE_BACKEND" $prefix -}}
{{/* Ensure the sub-dicts exist so set() persists on the live .Values object. */}}
{{- if not .Values.image -}}{{- $_ := set .Values "image" dict -}}{{- end -}}
{{- if not .Values.resources -}}{{- $_ := set .Values "resources" dict -}}{{- end -}}
{{- if not .Values.gpuDevicePlugin -}}{{- $_ := set .Values "gpuDevicePlugin" dict -}}{{- end -}}
{{- if eq $mode "cuda" -}}
{{- $_ := set .Values.image "name" ($acc.gpuImageName | default "ml-compute-service-gpu") -}}
{{/* Fail render when the pinned GPU image digest is absent. */}}
{{- $glob := .Values.global | default dict -}}
{{- $digests := $glob.imageDigests | default dict -}}
{{- $repo := include "nohiki-common.imageRepository" . | trim -}}
{{- if not (index $digests $repo) -}}
{{- fail (printf "%s: accelerator.mode=cuda requires a pinned GPU image digest for %q in global.imageDigests" (include "nohiki-common.name" .) $repo) -}}
{{- end -}}
{{- $_ := set .Values.resources "gpu" (int ($acc.gpuCount | default 1)) -}}
{{- $_ := set .Values "nodeSelector" (dict "workload" "nohiki-ml-gpu") -}}
{{- $_ := set .Values "tolerations" (list (dict "key" "sku" "operator" "Equal" "value" "gpu" "effect" "NoSchedule")) -}}
{{- $_ := set .Values.gpuDevicePlugin "enabled" true -}}
{{- $_ := include "nohiki-common.accelerator.backendEnv" (dict "root" . "name" $backendEnvName "value" "gpu") -}}
{{- else -}}
{{/* Reject the incoherent hand-mixed CPU+GPU config, then strip GPU scheduling. */}}
{{- if or $origPluginEnabled (gt $origGpu 0) -}}
{{- fail (printf "%s: accelerator.mode=cpu conflicts with a requested GPU artifact (gpuDevicePlugin.enabled=%v, resources.gpu=%d); set accelerator.mode=cuda or drop the GPU fields" (include "nohiki-common.name" .) $origPluginEnabled $origGpu) -}}
{{- end -}}
{{- $_ := set .Values.image "name" ($acc.cpuImageName | default "ml-compute-service") -}}
{{- $_ := set .Values.resources "gpu" 0 -}}
{{- $_ := set .Values.gpuDevicePlugin "enabled" false -}}
{{- $_ := set .Values "nodeSelector" dict -}}
{{- $_ := set .Values "tolerations" list -}}
{{- $_ := include "nohiki-common.accelerator.backendEnv" (dict "root" . "name" $backendEnvName) -}}
{{- end -}}
{{- $_ := set .Values "__acceleratorNormalized" true -}}
{{- end -}}
{{- end -}}
