{{/*
  github-provider-kog.kindEnabled — whether this release renders a kind.

  Called as (list . "<Kind>") at the top of every rd-* and configmap-* template. The answer is
  "true" or empty, so it reads directly in an `if`.

  EMPTY MEANS ALL, on purpose. `.Values.kinds` could default to the 32 names, but the CDC stores
  defaults on the composition, so an install would keep that list forever and never render a kind
  added by a later chart.
*/}}
{{- define "github-provider-kog.kindEnabled" -}}
{{- $root := index . 0 -}}
{{- $kind := index . 1 -}}
{{- if or (not $root.Values.kinds) (has $kind $root.Values.kinds) -}}true{{- end -}}
{{- end -}}

{{/*
spec.serverURL for every RestDefinition: GitHub Enterprise's API base URL, or nothing for
github.com. oasgen (>= 0.52.0) REPLACES the document's servers[0] with it, and the endpoint host
policy is built from that, so api.github.com stops being permitted at all: a misconfigured install
fails closed instead of sending the Enterprise token to the public API.
*/}}
{{- define "github-provider-kog.serverURL" -}}
{{- with .Values.githubBaseUrl }}
serverURL: {{ . | quote }}
{{- end }}
{{- end }}
