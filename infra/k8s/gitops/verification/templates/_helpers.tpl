{{- define "verification.image" -}}
{{- $name := .name -}}
{{- $root := .root -}}
{{- $digest := required (printf "global.imageDigests.%s is required" $name) (index $root.Values.global.imageDigests $name) -}}
{{- if not (regexMatch "^sha256:[0-9a-f]{64}$" $digest) -}}
{{- fail (printf "global.imageDigests.%s must be an immutable sha256 digest" $name) -}}
{{- end -}}
{{- printf "%s/%s@%s" (trimSuffix "/" $root.Values.global.nohikiImage.registry) $name $digest -}}
{{- end -}}
