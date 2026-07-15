package main

import (
	"log"

	"github.com/qw33ha/minimal-trpc-http-echo/handler"
	pb "github.com/qw33ha/minimal-trpc-http-echo/pb"
	trpc "trpc.group/trpc-go/trpc-go"
	thttp "trpc.group/trpc-go/trpc-go/http"
)

const (
	trpcServiceName = "demo.minimaltrpchttpecho.EchoService"
	httpServiceName = "demo.minimaltrpchttpecho.HTTP"
)

func main() {
	server := trpc.NewServer()
	service := handler.NewEchoHandler()

	pb.RegisterEchoServiceService(server.Service(trpcServiceName), service)

	httpHandler := handler.NewHTTPHandler(service)
	httpHandler.Register()
	thttp.RegisterNoProtocolService(server.Service(httpServiceName))

	if err := server.Serve(); err != nil {
		log.Fatalf("server exited: %v", err)
	}
}
