package handler

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/Shopify/sarama"
	trpckafka "trpc.group/trpc-go/trpc-database/kafka"
	"trpc.group/trpc-go/trpc-go/log"
)

const kafkaProducerServiceName = "trpc.kafka.producer.service"

type Event struct {
	ID      string `json:"id"`
	Message string `json:"message"`
}

type KafkaProducer struct {
	client trpckafka.Client
}

func NewKafkaProducer() *KafkaProducer {
	return &KafkaProducer{client: trpckafka.NewClientProxy(kafkaProducerServiceName)}
}

func (p *KafkaProducer) Publish(ctx context.Context, event Event) error {
	payload, err := json.Marshal(event)
	if err != nil {
		return fmt.Errorf("encode event: %w", err)
	}
	if err := p.client.Produce(ctx, []byte(event.ID), payload); err != nil {
		return fmt.Errorf("publish event: %w", err)
	}
	return nil
}

type KafkaConsumer struct{}

func NewKafkaConsumer() *KafkaConsumer {
	return &KafkaConsumer{}
}

func (*KafkaConsumer) Handle(_ context.Context, message *sarama.ConsumerMessage) error {
	var event Event
	if err := json.Unmarshal(message.Value, &event); err != nil {
		return fmt.Errorf("decode event at partition %d offset %d: %w", message.Partition, message.Offset, err)
	}
	log.Infof("consumed kafka event id=%s message=%q partition=%d offset=%d", event.ID, event.Message, message.Partition, message.Offset)
	return nil
}
