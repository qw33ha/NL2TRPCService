package main

import (
	"log"

	"github.com/qw33ha/minimal-trpc-kafka-event/handler"
	trpckafka "trpc.group/trpc-go/trpc-database/kafka"
	trpc "trpc.group/trpc-go/trpc-go"
	thttp "trpc.group/trpc-go/trpc-go/http"
)

const httpServiceName = "demo.minimaltrpckafkaevent.HTTP"

func main() {
	if err := handler.RegisterKafkaConfigFromEnv(); err != nil {
		log.Fatalf("configure Kafka: %v", err)
	}
	server := trpc.NewServer()
	producer := handler.NewKafkaProducer()
	httpHandler := handler.NewHTTPHandler(producer)

	httpHandler.Register()
	thttp.RegisterNoProtocolService(server.Service(httpServiceName))
	trpckafka.RegisterKafkaConsumerService(server, handler.NewKafkaConsumer())

	if err := server.Serve(); err != nil {
		log.Fatalf("server exited: %v", err)
	}
}
