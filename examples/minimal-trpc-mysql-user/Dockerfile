FROM golang:1.22 AS builder

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -o /out/minimal-trpc-mysql-user ./

FROM gcr.io/distroless/base-debian12

WORKDIR /app
COPY --from=builder /out/minimal-trpc-mysql-user /app/minimal-trpc-mysql-user
COPY trpc_go.yaml /app/trpc_go.yaml

ENTRYPOINT ["/app/minimal-trpc-mysql-user"]
CMD ["-conf=/app/trpc_go.yaml"]
