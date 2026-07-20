package handler

import (
	"encoding/json"
	"net/http"

	"trpc.group/trpc-go/trpc-go/log"
{% if http_enabled %}
	thttp "trpc.group/trpc-go/trpc-go/http"
{% endif %}
)

type HTTPHandler struct {
{% if rpc_enabled %}
	service *{{ handler_type_name }}
{% endif %}
}

{% if rpc_enabled %}
func NewHTTPHandler(service *{{ handler_type_name }}) *HTTPHandler {
	return &HTTPHandler{service: service}
}
{% else %}
func NewHTTPHandler() *HTTPHandler {
	return &HTTPHandler{}
}
{% endif %}

func (h *HTTPHandler) Register() {
{% for api in http_apis %}
	thttp.HandleFunc("{{ api.path }}", h.{{ api.handler_name }})
{% endfor %}
}

{% for api in http_apis %}
// {{ api.path }}  HTTP API
func (h *HTTPHandler) {{ api.handler_name }}(w http.ResponseWriter, r *http.Request) error {
	// [LLM: implement an explicit HTTP-to-RPC mapping using fields from the provided proto]
	writeJSON(w, http.StatusOK, nil)
	return nil
}
{% endfor %}

func writeJSON(w http.ResponseWriter, status int, body interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if body == nil {
		return
	}
	if err := json.NewEncoder(w).Encode(body); err != nil {
		log.Errorf("writeJSON encode failed: %v", err)
	}
}
