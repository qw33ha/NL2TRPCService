{% if kafka_producer_enabled %}
package handler

import trpckafka "trpc.group/trpc-go/trpc-database/kafka"

const KafkaProducerServiceName = "{{ kafka_service_name }}"

func NewKafkaProducerProxy() any {
	return trpckafka.NewClientProxy(KafkaProducerServiceName)
}
{% endif %}
