package handler

import (
	"context"

	{% if rpc_methods %}
		pb "{{ module_path }}/{{ group }}/{{ app }}_{{ server }}"
	{% endif %}
)

type {{ server | capitalize }}Handler struct{}

func New{{ server | capitalize }}Handler() *{{ server | capitalize }}Handler {
	return &{{ server | capitalize }}Handler{}
}

{% for method in rpc_methods %}
func (h *{{ server | capitalize }}Handler) {{ method.name }}(ctx context.Context, req *pb.{{ method.request_message }}) (*pb.{{ method.response_message }}, error) {

	// [LLM: implement {{ method.name }} according to the confirmed business requirement]
	return nil, nil
}

{% endfor %}
