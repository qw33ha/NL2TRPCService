package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	pb "github.com/qw33ha/minimal-trpc-http-echo/pb"
	trpc "trpc.group/trpc-go/trpc-go"
	trpclog "trpc.group/trpc-go/trpc-go/log"
)

func main() {
	go serveTRPC()
	go serveHTTP()
	waitForShutdown()
}

func serveTRPC() {
	service := &EchoService{}
	server := trpc.NewServer()
	pb.RegisterEchoServiceService(server.Service("demo.minimaltrpchttpecho.EchoService"), service)
	trpclog.Infof("starting minimal trpc runtime on configured trpc port")
	if err := server.Serve(); err != nil {
		trpclog.Errorf("trpc runtime exited: %v", err)
	}
}

func serveHTTP() {
	service := &EchoService{}
	port := getenv("PORT", "8080")
	mux := http.NewServeMux()
	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/echo", echoHandler(service))

	srv := &http.Server{
		Addr:              ":" + port,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}

	log.Printf("starting http echo server on :%s", port)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("http server failed: %v", err)
	}
}

type EchoService struct{}

func (s *EchoService) Echo(ctx context.Context, req *pb.EchoRequest) (*pb.EchoResponse, error) {
	_ = ctx
	return &pb.EchoResponse{
		PayloadJson: req.GetPayloadJson(),
		Message:     "echoed by trpc service",
	}, nil
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeJSON(w, http.StatusMethodNotAllowed, map[string]any{"error": "method not allowed"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": "ok"})
}

func echoHandler(service *EchoService) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			writeJSON(w, http.StatusMethodNotAllowed, map[string]any{"error": "method not allowed"})
			return
		}

		var payload map[string]any
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]any{"error": "invalid json"})
			return
		}

		payloadJSON := marshalPayload(payload)
		resp, err := service.Echo(r.Context(), &pb.EchoRequest{
			PayloadJson: payloadJSON,
			HttpMethod:  r.Method,
			HttpPath:    r.URL.Path,
		})
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]any{"error": err.Error()})
			return
		}

		writeRPCResponse(w, resp.GetPayloadJson(), resp.GetMessage())
	}
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
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

func waitForShutdown() {
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
}

func getenv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}
