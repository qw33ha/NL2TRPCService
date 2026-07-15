{% if kafka_consumer_enabled %}
package handler

import (
	"context"
	"encoding/json"

	"github.com/Shopify/sarama"
	"trpc.group/trpc-go/trpc-go/log"
)

type KafkaConsumer struct{}

func NewKafkaConsumer() *KafkaConsumer {
	return &KafkaConsumer{}
}

func (*KafkaConsumer) Handle(_ context.Context, msg *sarama.ConsumerMessage) error {
	var payload map[string]interface{}
	if err := json.Unmarshal(msg.Value, &payload); err != nil {
		return err
	}

	// [LLM: implement business logic for consumed Kafka messages]
	log.Infof("consumed Kafka message topic=%s partition=%d offset=%d payload=%v", msg.Topic, msg.Partition, msg.Offset, payload)
	return nil
}
{% endif %}
