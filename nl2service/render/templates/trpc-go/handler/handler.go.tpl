package handler

{% if rpc_methods %}
import (
	"context"

	pb "{{ module_path }}/pb"
)

{% endif %}
type {{ handler_type_name }} struct{}

func New{{ handler_type_name }}() *{{ handler_type_name }} {
	return &{{ handler_type_name }}{}
}

{% for method in rpc_methods %}
func (h *{{ handler_type_name }}) {{ method.name }}(ctx context.Context, req *pb.{{ method.request_message }}) (*pb.{{ method.response_message }}, error) {
	_ = ctx
	_ = req
	// [LLM: implement {{ method.name }} according to the confirmed business requirement]
	return &pb.{{ method.response_message }}{
		PayloadJson: req.GetPayloadJson(),
		Message: "{{ method.response_description }}",
	}, nil
}

{% endfor %}
