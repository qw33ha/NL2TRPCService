package handler

import (
	"context"

	pb "github.com/qw33ha/minimal-trpc-http-echo/pb"
)

// EchoHandler implements the generated tRPC EchoService contract.
type EchoHandler struct{}

func NewEchoHandler() *EchoHandler {
	return &EchoHandler{}
}

func (h *EchoHandler) Echo(ctx context.Context, req *pb.EchoRequest) (*pb.EchoResponse, error) {
	_ = ctx
	return &pb.EchoResponse{
		PayloadJson: req.GetPayloadJson(),
		Message:     "echoed by shared service handler",
	}, nil
}
