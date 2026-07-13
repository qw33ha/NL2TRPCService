FROM golang:1.22 AS build
WORKDIR /src
COPY . .
RUN chmod +x build.sh devops_build.sh start.sh && ./build.sh

FROM gcr.io/distroless/base-debian12
WORKDIR /app
COPY --from=build /src/{{ server_bin }} /app/{{ server_bin }}
COPY --from=build /src/trpc_go.yaml /app/trpc_go.yaml
ENTRYPOINT ["/app/{{ server_bin }}"]
