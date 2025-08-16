{{- define "raycluster.name" -}}
{{ .Chart.Name }}
{{- end -}}

{{- define "raycluster.fullname" -}}
{{ .Release.Name }}
{{- end -}}







