FROM golang:1.22 AS builder

WORKDIR /src
COPY go.mod go.sum* ./
RUN go mod download

COPY . .

{% if rpc_enabled %}
RUN go install trpc.group/trpc-go/trpc-cmdline/trpc@v1.0.9 \
    && bash scripts/generate_stub.sh
{% endif %}

RUN go mod tidy \
    && CGO_ENABLED=0 go build \
        -trimpath \
        -o /out/{{ server_bin }} \
        ./

FROM gcr.io/distroless/base-debian12

WORKDIR /app

COPY --from=builder /out/{{ server_bin }} /app/{{ server_bin }}
COPY trpc_go.yaml /app/trpc_go.yaml

ENTRYPOINT ["/app/{{ server_bin }}"]
CMD ["-conf=/app/trpc_go.yaml"]
