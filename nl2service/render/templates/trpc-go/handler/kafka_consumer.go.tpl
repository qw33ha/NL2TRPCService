{% if kafka_consumer_enabled %}
package handler

import (
	"context"
	"encoding/json"

	"github.com/IBM/sarama"
)

func HandleKafkaMessage(ctx context.Context, msg *sarama.ConsumerMessage) error {
	_ = ctx

	var payload map[string]any
	if err := json.Unmarshal(msg.Value, &payload); err != nil {
		return nil
	}

	// [LLM: implement business logic for consumed Kafka messages]
	_ = payload
	return nil
}
{% endif %}
