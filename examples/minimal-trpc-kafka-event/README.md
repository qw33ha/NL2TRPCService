# Minimal tRPC-Go Kafka event example

This example exposes `POST /events`, publishes the JSON event to Kafka, and consumes the same topic with the public tRPC-Go Kafka plugin. The broker is configured for Aiven's public TLS endpoint, but every deployment-specific value comes from environment variables.

## Configure

Rotate the password shown in the shared screenshot before testing. Then copy `.env.example` to `.env`, put the replacement password in `.env`, and save the CA certificate downloaded from Aiven as `ca.pem` in this example directory. Never commit `.env` or private credentials.

Required variables:

- `KAFKA_BROKERS`: comma-separated Kafka bootstrap addresses
- `KAFKA_TOPIC`: `test-topic`
- `KAFKA_GROUP`: `nl2trpc-example`
- `KAFKA_USERNAME`: Aiven service user
- `KAFKA_PASSWORD`: rotated Aiven service-user password

The configuration uses `SASL_SSL` with the `PLAIN` SASL mechanism. Do not work around certificate errors by disabling TLS verification.

## Run with Docker

The Docker build reads `ca.pem` from this directory and installs it only in the runtime image. It does not modify the host trust store. The CA certificate is public trust material; credentials remain runtime environment variables.

```sh
cp .env.example .env
# Edit .env with the rotated password and place ca.pem in this directory.
docker compose up --build
```

In another terminal, publish an event:

```sh
curl -i -X POST http://127.0.0.1:8080/events \
  -H 'Content-Type: application/json' \
  -d '{"id":"event-1","message":"hello from tRPC-Go"}'
```

The request should return `202 Accepted`. The service log should then show the consumed event, partition, and offset.
