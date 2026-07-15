package handler

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"

	thttp "trpc.group/trpc-go/trpc-go/http"
)

type HTTPHandler struct {
	mysql *MySQLHandler
}

func NewHTTPHandler(mysql *MySQLHandler) *HTTPHandler {
	return &HTTPHandler{mysql: mysql}
}

func (h *HTTPHandler) Register() {
	thttp.HandleFunc("/health", h.health)
	thttp.HandleFunc("/users", h.users)
}

func (h *HTTPHandler) health(w http.ResponseWriter, _ *http.Request) error {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	return nil
}

func (h *HTTPHandler) users(w http.ResponseWriter, r *http.Request) error {
	switch r.Method {
	case http.MethodPost:
		return h.createUser(w, r)
	case http.MethodGet:
		return h.getUser(w, r)
	case http.MethodPut:
		return h.updateUser(w, r)
	case http.MethodDelete:
		return h.deleteUser(w, r)
	default:
		w.Header().Set("Allow", "POST, GET, PUT, DELETE")
		writeJSON(w, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
		return nil
	}
}

type userInput struct {
	Name  string `json:"name"`
	Email string `json:"email"`
}

func (h *HTTPHandler) createUser(w http.ResponseWriter, r *http.Request) error {
	input, ok := decodeUserInput(w, r)
	if !ok {
		return nil
	}
	user, err := h.mysql.CreateUser(r.Context(), input.Name, input.Email)
	if err != nil {
		writeUserError(w, err)
		return nil
	}
	writeJSON(w, http.StatusCreated, user)
	return nil
}

func (h *HTTPHandler) getUser(w http.ResponseWriter, r *http.Request) error {
	id, ok := userID(w, r)
	if !ok {
		return nil
	}
	user, err := h.mysql.GetUser(r.Context(), id)
	if err != nil {
		writeUserError(w, err)
		return nil
	}
	writeJSON(w, http.StatusOK, user)
	return nil
}

func (h *HTTPHandler) updateUser(w http.ResponseWriter, r *http.Request) error {
	id, ok := userID(w, r)
	if !ok {
		return nil
	}
	input, ok := decodeUserInput(w, r)
	if !ok {
		return nil
	}
	user, err := h.mysql.UpdateUser(r.Context(), id, input.Name, input.Email)
	if err != nil {
		writeUserError(w, err)
		return nil
	}
	writeJSON(w, http.StatusOK, user)
	return nil
}

func (h *HTTPHandler) deleteUser(w http.ResponseWriter, r *http.Request) error {
	id, ok := userID(w, r)
	if !ok {
		return nil
	}
	if err := h.mysql.DeleteUser(r.Context(), id); err != nil {
		writeUserError(w, err)
		return nil
	}
	w.WriteHeader(http.StatusNoContent)
	return nil
}

func decodeUserInput(w http.ResponseWriter, r *http.Request) (userInput, bool) {
	var input userInput
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&input); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid JSON body"})
		return userInput{}, false
	}
	input.Name = strings.TrimSpace(input.Name)
	input.Email = strings.TrimSpace(input.Email)
	if input.Name == "" || input.Email == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "name and email are required"})
		return userInput{}, false
	}
	return input, true
}

func userID(w http.ResponseWriter, r *http.Request) (int64, bool) {
	id, err := strconv.ParseInt(r.URL.Query().Get("id"), 10, 64)
	if err != nil || id <= 0 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "a positive integer id is required"})
		return 0, false
	}
	return id, true
}

func writeUserError(w http.ResponseWriter, err error) {
	if errors.Is(err, ErrUserNotFound) {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": ErrUserNotFound.Error()})
		return
	}
	writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
}

func writeJSON(w http.ResponseWriter, status int, value interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
