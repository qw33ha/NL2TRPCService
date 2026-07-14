{% if kafka_producer_enabled %}
package handler

import (
	"context"
	"encoding/json"

	"trpc.group/trpc-go/trpc-database/kafka"
)

type KafkaProducer struct {
	cli kafka.Client
}

func NewKafkaProducer() *KafkaProducer {
	return &KafkaProducer{
		cli: kafka.NewClientProxy("trpc.kafka.{{ group }}.{{ app }}.{{ server }}"),
	}
}

func (p *KafkaProducer) Send(ctx context.Context, key string, value interface{}) error {
	data, err := json.Marshal(value)
	if err != nil {
		return err
	}
	if err := p.cli.Produce(ctx, []byte(key), data); err != nil {
		log.Errorf("kafka produce failed topic={{ kafka_producer_topic }} key=%s err=%v", key, err)
		return err
	}
	log.Infof("kafka produce success topic={{ kafka_producer_topic }} key=%s", key)
	return nil
}
{% endif %}
