FROM golang:1.22 AS builder
WORKDIR /src

COPY go.mod ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /out/minimal-trpc-http-echo ./

FROM gcr.io/distroless/base-debian12
WORKDIR /app

COPY --from=builder /out/minimal-trpc-http-echo /app/minimal-trpc-http-echo
COPY --from=builder /src/trpc_go.yaml /app/trpc_go.yaml

ENV PORT=8080
EXPOSE 8080 9000

ENTRYPOINT ["/app/minimal-trpc-http-echo"]
