package main

import (
	"os"
	"os/signal"
	"syscall"
{% if rpc_enabled or http_enabled or kafka_consumer_enabled %}

	trpc "trpc.group/trpc-go/trpc-go"
	trpclog "trpc.group/trpc-go/trpc-go/log"
	trpcserver "trpc.group/trpc-go/trpc-go/server"
{% endif %}
{% if http_enabled %}
	thttp "trpc.group/trpc-go/trpc-go/http"
{% endif %}
{% if kafka_consumer_enabled %}
	trpckafka "trpc.group/trpc-go/trpc-database/kafka"
{% endif %}
{% if rpc_enabled %}
	pb "{{ module_path }}/pb"
{% endif %}
	"{{ module_path }}/handler"
)

const serviceName = "{{ primary_service_name }}"

func main() {
{% if kafka_enabled %}
	if err := handler.RegisterKafkaConfigFromEnv(); err != nil {
		trpclog.Fatalf("configure Kafka: %v", err)
	}
{% endif %}
{% if db_enabled %}
	initDatabaseClients()
{% endif %}
{% if rpc_enabled %}
	serviceHandler := handler.New{{ handler_type_name }}()
{% endif %}
{% if rpc_enabled or http_enabled or kafka_consumer_enabled %}
	s := trpc.NewServer()
{% endif %}
{% if rpc_enabled %}
	pb.Register{{ rpc_service_name }}Service(s.Service(serviceName), serviceHandler)
{% endif %}
{% if kafka_consumer_enabled %}
	registerKafkaConsumers(s)
{% endif %}
{% if native_http_enabled %}
	httpHandler := handler.NewHTTPHandler()
	httpHandler.Register()
	thttp.RegisterNoProtocolService(s.Service("{{ http_service_name }}"))
{% elif http_enabled %}
	httpHandler := handler.NewHTTPHandler(serviceHandler)
	httpHandler.Register()
	thttp.RegisterNoProtocolService(s.Service("{{ http_service_name }}"))
{% endif %}
{% if rpc_enabled or http_enabled or kafka_consumer_enabled %}
	serveTRPC(s)
{% else %}
	waitForShutdown()
{% endif %}
}
{% if db_enabled %}

func initDatabaseClients() {
{% if db_type == "mysql" %}
	_ = handler.NewMySQLHandler()
	// [LLM: inject the MySQL handler into the transport or business handlers that need persistence.]
{% elif db_type == "postgres" %}
	if _, err := handler.NewPostgreSQLHandler(); err != nil {
		trpclog.Fatalf("initialize PostgreSQL handler: %v", err)
	}
	// [LLM: inject the PostgreSQL handler into the transport or business handlers that need persistence.]
{% endif %}
}
{% endif %}
{% if kafka_consumer_enabled %}

func registerKafkaConsumers(s *trpcserver.Server) {
	trpckafka.RegisterKafkaConsumerService(s, handler.NewKafkaConsumer())
}
{% endif %}
{% if rpc_enabled or http_enabled or kafka_consumer_enabled %}

func serveTRPC(s *trpcserver.Server) {
	trpclog.Infof("starting %s trpc runtime", serviceName)
	if err := s.Serve(); err != nil {
		trpclog.Error(err)
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
