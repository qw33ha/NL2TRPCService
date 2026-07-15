{% if kafka_enabled %}
package handler

import (
	"fmt"
	"os"
	"strings"

	"github.com/Shopify/sarama"
	trpckafka "trpc.group/trpc-go/trpc-database/kafka"
)

const (
	kafkaConsumerAddress = "{{ kafka_consumer_address }}"
	kafkaProducerAddress = "{{ kafka_producer_address }}"
)

func RegisterKafkaConfigFromEnv() error {
	brokers := strings.Split(getenv("KAFKA_BROKERS", "{{ kafka_producer_brokers }}"), ",")
	topic := getenv("KAFKA_TOPIC", "{{ kafka_consumer_topic }}")
	group := getenv("KAFKA_GROUP", "{{ kafka_consumer_group }}")
	username := strings.TrimSpace(os.Getenv("KAFKA_USERNAME"))
	password := strings.TrimSpace(os.Getenv("KAFKA_PASSWORD"))
	if brokers[0] == "" || topic == "" || group == "" || username == "" || password == "" {
		return fmt.Errorf("KAFKA_BROKERS, KAFKA_TOPIC, KAFKA_GROUP, KAFKA_USERNAME, and KAFKA_PASSWORD are required")
	}

	consumer := trpckafka.GetDefaultConfig()
	consumer.Brokers = brokers
	consumer.Topics = []string{topic}
	consumer.Group = group
	consumer.Initial = sarama.OffsetOldest
	consumer.ScramClient = saslConfig(username, password)
	trpckafka.RegisterAddrConfig(kafkaConsumerAddress, consumer)

	producer := trpckafka.GetDefaultConfig()
	producer.Brokers = brokers
	producer.Topic = topic
	producer.ClientID = "{{ server }}-producer"
	producer.Partitioner = sarama.NewHashPartitioner
	producer.ScramClient = saslConfig(username, password)
	trpckafka.RegisterAddrConfig(kafkaProducerAddress, producer)
	return nil
}

func saslConfig(username, password string) *trpckafka.LSCRAMClient {
	return &trpckafka.LSCRAMClient{
		User:      username,
		Password:  password,
		Mechanism: string(sarama.SASLTypePlaintext),
		Protocol:  trpckafka.SASLTypeSSL,
	}
}

func getenv(name, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(name)); value != "" {
		return value
	}
	return fallback
}
{% endif %}
