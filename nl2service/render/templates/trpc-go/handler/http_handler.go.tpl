package handler

import (
	"encoding/json"
	"net/http"
	"strings"

	pb "{{ module_path }}/pb"
)

type HTTPHandler struct {
	service *{{ handler_type_name }}
}

func NewHTTPHandler(service *{{ handler_type_name }}) *HTTPHandler {
	return &HTTPHandler{service: service}
}

func (h *HTTPHandler) Register(mux *http.ServeMux) {
	mux.HandleFunc("{{ health_path }}", h.Health)
{% for api in http_apis %}
	mux.HandleFunc("{{ api.path }}", h.{{ api.handler_name }})
{% endfor %}
}

func (h *HTTPHandler) Health(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeMethodNotAllowed(w, http.MethodGet)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": "ok"})
}

{% for api in http_apis %}
func (h *HTTPHandler) {{ api.handler_name }}(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.Method{{ api.method | upper | capitalize }} {
		writeMethodNotAllowed(w, http.Method{{ api.method | upper | capitalize }})
		return
	}

	var payload map[string]any
	if strings.Contains(r.Header.Get("Content-Type"), "application/json") {
		_ = json.NewDecoder(r.Body).Decode(&payload)
	}

	payloadJSON := marshalPayload(payload)
	resp, err := h.service.{{ api.rpc_name }}(r.Context(), &pb.{{ api.request_message }}{
		PayloadJson: payloadJSON,
		HttpMethod:  "{{ api.method }}",
		HttpPath:    "{{ api.path }}",
		Headers:     requestHeaders(r.Header),
	})
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]any{"error": err.Error()})
		return
	}

	writeRPCResponse(w, resp.GetPayloadJson(), resp.GetMessage())
}

{% endfor %}
func writeMethodNotAllowed(w http.ResponseWriter, allow string) {
	w.Header().Set("Allow", allow)
	writeJSON(w, http.StatusMethodNotAllowed, map[string]any{"error": "method not allowed"})
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if body == nil {
		return
	}
	_ = json.NewEncoder(w).Encode(body)
}

func writeRPCResponse(w http.ResponseWriter, payloadJSON string, message string) {
	if payloadJSON != "" {
		var body any
		if err := json.Unmarshal([]byte(payloadJSON), &body); err == nil {
			writeJSON(w, http.StatusOK, body)
			return
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"message": message, "payload_json": payloadJSON})
}

func requestHeaders(header http.Header) map[string]string {
	result := make(map[string]string, len(header))
	for key, values := range header {
		if len(values) == 0 {
			continue
		}
		result[key] = values[0]
	}
	return result
}

func marshalPayload(payload map[string]any) string {
	if payload == nil {
		return "{}"
	}
	data, err := json.Marshal(payload)
	if err != nil {
		return "{}"
	}
	return string(data)
}
