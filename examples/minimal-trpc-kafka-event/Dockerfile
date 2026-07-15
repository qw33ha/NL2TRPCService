FROM golang:1.22 AS builder
WORKDIR /src

COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /out/minimal-trpc-kafka-event ./

FROM gcr.io/distroless/base-debian12
WORKDIR /app

COPY --from=builder /out/minimal-trpc-kafka-event /app/minimal-trpc-kafka-event
COPY --from=builder /src/trpc_go.yaml /app/trpc_go.yaml
COPY ca.pem /etc/ssl/certs/aiven-ca.pem

ENV SSL_CERT_FILE=/etc/ssl/certs/aiven-ca.pem

EXPOSE 8080

ENTRYPOINT ["/app/minimal-trpc-kafka-event"]
