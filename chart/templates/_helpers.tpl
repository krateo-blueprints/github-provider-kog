{{/*
The plugin Deployment/Service name (used by both the workload and the webServiceUrl the
gitref OAS get-operation points its `servers` override at, so the rest-dynamic-controller
routes the GET to the plugin instead of GitHub).
*/}}
{{- define "github-provider-kog.pluginName" -}}
{{- printf "%s-plugin" .Release.Name -}}
{{- end -}}

{{/*
The in-cluster URL of the plugin web service. Referenced from assets/gitref.yaml (rendered
through `tpl`) as the get-operation server, so the generated controller calls the plugin.
*/}}
{{- define "webServiceUrl" -}}
{{- printf "http://%s-plugin.%s.svc:8080" .Release.Name .Release.Namespace -}}
{{- end -}}
