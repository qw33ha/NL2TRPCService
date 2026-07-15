package handler

import (
	"encoding/json"
	"net/http"

	pb "github.com/qw33ha/minimal-trpc-http-echo/pb"
	thttp "trpc.group/trpc-go/trpc-go/http"
)

// HTTPHandler translates native HTTP requests into calls to the shared service.
type HTTPHandler struct {
	service *EchoHandler
}

func NewHTTPHandler(service *EchoHandler) *HTTPHandler {
	return &HTTPHandler{service: service}
}

func (h *HTTPHandler) Register() {
	thttp.HandleFunc("/health", h.Health)
	thttp.HandleFunc("/echo", h.Echo)
}

func (h *HTTPHandler) Health(w http.ResponseWriter, r *http.Request) error {
	if r.Method != http.MethodGet {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]any{"error": "method not allowed"})
		return nil
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": "ok"})
	return nil
}

func (h *HTTPHandler) Echo(w http.ResponseWriter, r *http.Request) error {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]any{"error": "method not allowed"})
		return nil
	}

	var payload map[string]any
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid json"})
		return nil
	}

	payloadJSON, err := json.Marshal(payload)
	if err != nil {
		return err
	}

	response, err := h.service.Echo(r.Context(), &pb.EchoRequest{
		PayloadJson: string(payloadJSON),
		HttpMethod:  r.Method,
		HttpPath:    r.URL.Path,
	})
	if err != nil {
		return err
	}

	var body any
	if err := json.Unmarshal([]byte(response.GetPayloadJson()), &body); err != nil {
		body = map[string]any{
			"message":      response.GetMessage(),
			"payload_json": response.GetPayloadJson(),
		}
	}
	writeJSON(w, http.StatusOK, body)
	return nil
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	if body != nil {
		_ = json.NewEncoder(w).Encode(body)
	}
}
