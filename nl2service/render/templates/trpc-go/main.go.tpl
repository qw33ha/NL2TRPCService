package main

import (
	"os"
	"os/signal"
	"syscall"
{% if rpc_enabled or http_enabled or kafka_consumer_enabled %}

	trpc "trpc.group/trpc-go/trpc-go"
	trpclog "trpc.group/trpc-go/trpc-go/log"
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

const serviceName = "{{ trpc_service_name }}"

func main() {
{% if db_enabled %}
	initDatabaseClients()
{% endif %}
{% if kafka_producer_enabled %}
	initKafkaProducer()
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
{% if rpc_enabled or http_enabled or kafka_consumer_enabled %}

func serveTRPC(s *trpc.Server) {
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
