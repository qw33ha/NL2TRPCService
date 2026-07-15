package handler

import (
	"encoding/json"
	"net/http"
	"strings"

	thttp "trpc.group/trpc-go/trpc-go/http"
)

type HTTPHandler struct {
	producer *KafkaProducer
}

func NewHTTPHandler(producer *KafkaProducer) *HTTPHandler {
	return &HTTPHandler{producer: producer}
}

func (h *HTTPHandler) Register() {
	thttp.HandleFunc("/health", h.health)
	thttp.HandleFunc("/events", h.events)
}

func (*HTTPHandler) health(w http.ResponseWriter, _ *http.Request) error {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	return nil
}

func (h *HTTPHandler) events(w http.ResponseWriter, r *http.Request) error {
	if r.Method != http.MethodPost {
		w.Header().Set("Allow", http.MethodPost)
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
		return nil
	}

	var event Event
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&event); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid JSON body"})
		return nil
	}
	event.ID = strings.TrimSpace(event.ID)
	event.Message = strings.TrimSpace(event.Message)
	if event.ID == "" || event.Message == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "id and message are required"})
		return nil
	}
	if err := h.producer.Publish(r.Context(), event); err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": err.Error()})
		return nil
	}
	writeJSON(w, http.StatusAccepted, event)
	return nil
}

func writeJSON(w http.ResponseWriter, status int, value interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
