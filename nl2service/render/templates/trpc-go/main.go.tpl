package main

import (
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
{% if rpc_enabled or kafka_consumer_enabled %}

	trpc "trpc.group/trpc-go/trpc-go"
	trpclog "trpc.group/trpc-go/trpc-go/log"
{% endif %}
{% if kafka_consumer_enabled %}
	trpckafka "trpc.group/trpc-go/trpc-database/kafka"
{% endif %}
{% if rpc_enabled %}
	pb "{{ module_path }}/pb"
{% endif %}
	"{{ module_path }}/handler"
)

const serviceName = "{{ trpc_service_name }}"

func main() {
{% if db_enabled %}
	initDatabaseClients()
{% endif %}
{% if kafka_producer_enabled %}
	initKafkaProducer()
{% endif %}
	serviceHandler := handler.New{{ handler_type_name }}()
{% if rpc_enabled or kafka_consumer_enabled %}
	s := trpc.NewServer()
{% endif %}
{% if rpc_enabled %}
	pb.Register{{ rpc_service_name }}Service(s.Service(serviceName), serviceHandler)
{% endif %}
{% if kafka_consumer_enabled %}
	registerKafkaConsumers(s)
{% endif %}
{% if rpc_enabled or kafka_consumer_enabled %}
	go serveTRPC(s)
{% endif %}
{% if http_enabled %}
	go serveHTTP(serviceHandler)
{% endif %}
	waitForShutdown()
}
{% if db_enabled %}

func initDatabaseClients() {
{% if db_type == "mysql" %}
	_ = handler.NewMySQLProxy()
	// [LLM: inject the MySQL proxy into the business handlers that need persistence.]
{% elif db_type == "redis" %}
	_, _ = handler.NewRedisClient()
	// [LLM: inject the Redis client into the business handlers that need caching or KV access.]
{% endif %}
}
{% endif %}
{% if kafka_producer_enabled %}

func initKafkaProducer() {
	_ = handler.NewKafkaProducerProxy()
	// [LLM: inject the Kafka producer proxy into the business handlers that publish events.]
}
{% endif %}
{% if kafka_consumer_enabled %}

func registerKafkaConsumers(s *trpc.Server) {
	trpckafka.RegisterKafkaHandlerService(s.Service("{{ kafka_service_name }}"), handler.HandleKafkaMessage)
}
{% endif %}
{% if rpc_enabled or kafka_consumer_enabled %}

func serveTRPC(s *trpc.Server) {
	trpclog.Infof("starting %s trpc runtime", serviceName)
	if err := s.Serve(); err != nil {
		trpclog.Error(err)
	}
}
{% endif %}
{% if http_enabled %}

func serveHTTP(serviceHandler *handler.{{ handler_type_name }}) {
	port := getenv("PORT", "8080")
	mux := http.NewServeMux()
	handler.NewHTTPHandler(serviceHandler).Register(mux)

	srv := &http.Server{
		Addr:              ":" + port,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}

	log.Printf("starting %s http bridge on :%s", serviceName, port)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("http server failed: %v", err)
	}
}
{% endif %}

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
