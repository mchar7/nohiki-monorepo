{{/* Project application secrets from Kubernetes Secrets populated by Helm locally or ESO in production. */}}
{{- define "nohiki-common.secretsVolumeMount" -}}
{{- $secrets := .Values.secrets | default dict }}
{{- if $secrets.enabled | default true }}
- name: secrets-store
  mountPath: {{ $secrets.mountPath | default "/run/secrets" }}
  readOnly: true
{{- end }}
{{- end }}

{{- define "nohiki-common.secretsVolume" -}}
{{- $glob := .Values.global | default dict }}
{{- $globSecrets := $glob.secrets | default dict }}
{{- $secrets := .Values.secrets | default dict }}
{{- $modelEgress := ($glob.modelEgress | default dict) }}
{{- $usesModelEgress := ((.Values.llm | default dict).enabled | default false) }}
{{- $db := .Values.database | default dict }}
{{- if $secrets.enabled | default true }}
- name: secrets-store
  projected:
    sources:
      {{- if $secrets.database }}
      - secret:
          name: {{- if $db.enabled }} {{ printf "%s-db-credentials" .Chart.Name }} {{- else }} {{ $globSecrets.databaseSecretName | default "nohiki-database-credentials" }} {{- end }}
          items:
            - {key: host, path: database/host}
            - {key: port, path: database/port}
            - {key: user, path: database/user}
            - {key: password, path: database/password}
            - {key: database, path: database/database}
            - {key: dsn, path: database/dsn}
      {{- end }}
      {{- if $secrets.redis }}
      - secret:
          name: {{ $globSecrets.redisSecretName | default "nohiki-redis-credentials" }}
          items:
            - {key: dsn, path: redis/dsn}
      {{- end }}
      {{- if $secrets.jwt }}
      - secret:
          name: {{ $globSecrets.jwtSecretName | default "nohiki-jwt-keys" }}
          items:
            - {key: private_key, path: jwt/private_key}
      {{- end }}
      {{- if $secrets.oauth }}
      - secret:
          name: {{ $globSecrets.oauthSecretName | default "nohiki-oauth-credentials" }}
          items:
            - {key: github_client_id, path: oauth/github_client_id}
            - {key: github_client_secret, path: oauth/github_client_secret}
            - {key: google_client_id, path: oauth/google_client_id}
            - {key: google_client_secret, path: oauth/google_client_secret}
      {{- end }}
      {{- if $secrets.email }}
      - secret:
          name: {{ $globSecrets.emailSecretName | default "nohiki-email-api-keys" }}
          items:
            - {key: resend_api_key, path: email/api_key}
      {{- end }}
      {{- if $secrets.jsearch }}
      - secret:
          name: {{ $globSecrets.jsearchSecretName | default "nohiki-jsearch-api-keys" }}
          items:
            - {key: api_key, path: jsearch/api_key}
      {{- end }}
      {{- if $secrets.s3 }}
      - secret:
          name: {{ $globSecrets.s3SecretName | default "nohiki-s3-credentials" }}
          items:
            - {key: access_key, path: s3/access_key}
            - {key: secret_key, path: s3/secret_key}
      {{- end }}
{{- end }}
{{- end }}
