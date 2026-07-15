package main

import (
	"log"

	"github.com/qw33ha/minimal-trpc-mysql-user/handler"
	trpc "trpc.group/trpc-go/trpc-go"
	thttp "trpc.group/trpc-go/trpc-go/http"
)

const httpServiceName = "demo.minimaltrpcmysqluser.HTTP"

func main() {
	server := trpc.NewServer()
	mysqlHandler := handler.NewMySQLHandler()
	httpHandler := handler.NewHTTPHandler(mysqlHandler)

	httpHandler.Register()
	thttp.RegisterNoProtocolService(server.Service(httpServiceName))

	if err := server.Serve(); err != nil {
		log.Fatalf("server exited: %v", err)
	}
}
