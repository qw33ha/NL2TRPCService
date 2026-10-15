## producer client

```yaml
client:                                            # Backend configuration for client calls.
  service:                                         # Configuration for the backend.
    - name: trpc.app.server.producer               # producer service name,define by yourself.        
      target: kafka://ip1:port1,ip2:port2?topic=YOUR_TOPIC&clientid=xxx&compression=xxx
      timeout: 800                                 # The maximum processing time of the current request.
```

```go
package main

import (
  "time"
  "context"

  "trpc.group/trpc-go/trpc-database/kafka"
  "trpc.group/trpc-go/trpc-go/client"
)

func (s *server) SayHello(ctx context.Context, req *pb.ReqBody, rsp *pb.RspBody)( err error ) {
  proxy := kafka.NewClientProxy("trpc.app.server.producer") // The service name is customized 
  // and is mainly used for monitoring reporting and addressing configuration items.
  
  // kafka function call.
  err := proxy.Produce(ctx, key, value)

  // producer native interface, return offset、partition.
  partition, offset, err := proxy.SendSaramaMessage(ctx, sarama.ProducerMessage{
    Topic: "your_topic",
    Value: sarama.ByteEncoder(msg),
  })

  // Business logic
  // ...
}
```
