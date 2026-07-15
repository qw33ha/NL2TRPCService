package handler

import (
	"fmt"
	"os"
	"strings"

	"github.com/Shopify/sarama"
	trpckafka "trpc.group/trpc-go/trpc-database/kafka"
)

const (
	kafkaConsumerAddress = "kafka-consumer-config"
	kafkaProducerAddress = "kafka-producer-config"
)

func RegisterKafkaConfigFromEnv() error {
	brokers := strings.Split(requiredEnv("KAFKA_BROKERS"), ",")
	topic := requiredEnv("KAFKA_TOPIC")
	group := requiredEnv("KAFKA_GROUP")
	username := requiredEnv("KAFKA_USERNAME")
	password := requiredEnv("KAFKA_PASSWORD")
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
	producer.ClientID = "nl2trpc-example-producer"
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

func requiredEnv(name string) string {
	return strings.TrimSpace(os.Getenv(name))
}
