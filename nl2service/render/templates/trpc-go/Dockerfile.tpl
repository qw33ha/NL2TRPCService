ARG TRPC_GO_BASE_IMAGE=trpc-go-runtime:latest
FROM ${TRPC_GO_BASE_IMAGE}

COPY {{ server_bin }} /usr/local/trpc/bin/
COPY trpc_go.yaml /usr/local/trpc/bin/trpc_go.yaml
COPY start.sh /root/

WORKDIR /root
ENTRYPOINT ["/root/start.sh"]
