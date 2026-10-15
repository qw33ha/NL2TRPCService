"""Deterministic backend bindings; all variable implementation is Agent-authored."""
from nl2service.render.official_mysql import OfficialMySQLRenderer,MAIN,CONFIG,PLACEHOLDER,PROTO
from nl2service.render.renderer import ProtoContractError
from pathlib import Path


class OfficialBackendRenderer(OfficialMySQLRenderer):
    def __init__(self,backend):
        if backend not in ('redis','kafka'): raise ValueError('Unsupported backend.')
        self.backend=backend
        self.generation_contract={**OfficialMySQLRenderer.generation_contract}
        if backend=='kafka': self.generation_contract['additional_symbol']='storageService.HandleEvent(context.Context,*sarama.ConsumerMessage) (json.RawMessage,error)'

    def render_tree(self,spec):
        if spec.service.enable_http or not spec.service.enable_trpc or spec.database.enabled:
            raise ProtoContractError('This backend prototype requires RPC-only capability without a database.')
        if not spec.service.proto_file or Path(spec.service.proto_file).read_text().strip()!=PROTO.read_text().strip():
            raise ProtoContractError('Only the pinned official Greeter wire contract is supported.')
        if self.backend=='redis':
            if not spec.redis.enabled or spec.kafka.enabled: raise ProtoContractError('Redis-only capability required.')
            main=MAIN.replace('mysql "trpc.group/trpc-go/trpc-database/mysql"','goredis "trpc.group/trpc-go/trpc-database/goredis"\n redis "github.com/redis/go-redis/v9"')
            main=main.replace('db mysql.Client','cache redis.UniversalClient')
            main=main.replace('database:=mysql.NewClientProxy("trpc.mysql.nl2service.storage",client.WithTarget(os.Getenv("NL2SERVICE_MYSQL_TARGET")))','cache,err:=goredis.New("trpc.redis.nl2service.cache",client.WithTarget(os.Getenv("NL2SERVICE_BACKEND_TARGET")));if err!=nil {panic(err)};defer cache.Close()')
            main=main.replace('&storageService{db:database}','&storageService{cache:cache}')
            dependencies='trpc.group/trpc-go/trpc-database/goredis v1.0.0\n github.com/redis/go-redis/v9 v9.0.4'
            config=CONFIG;placeholder=PLACEHOLDER
        else:
            if not spec.kafka.enabled or spec.redis.enabled: raise ProtoContractError('Kafka-only capability required.')
            if spec.kafka.tls is True or spec.kafka.ca_file or spec.kafka.secret_name:
                raise ProtoContractError('This initial official Kafka binding is plaintext without credentials; TLS/authentication is not implemented in this path.')
            main=MAIN.replace('mysql "trpc.group/trpc-go/trpc-database/mysql"','kafka "trpc.group/trpc-go/trpc-database/kafka"\n "github.com/Shopify/sarama"')
            main=main.replace('db mysql.Client','producer kafka.Client')
            main=main.replace('server:=trpc.NewServer()','if os.Getenv("NL2SERVICE_RPC_REQUEST")=="" { cfg,err:=kafka.ParseAddress(os.Getenv("NL2SERVICE_KAFKA_ADDRESS"));if err!=nil {panic(err)};cfg.MaxRetry=-1;cfg.Initial=sarama.OffsetOldest;kafka.RegisterAddrConfig(os.Getenv("NL2SERVICE_KAFKA_ADDRESS"),cfg) };server:=trpc.NewServer()')
            main=main.replace('database:=mysql.NewClientProxy("trpc.mysql.nl2service.storage",client.WithTarget(os.Getenv("NL2SERVICE_MYSQL_TARGET")))','producer:=kafka.NewClientProxy("trpc.kafka.nl2service.producer",client.WithTarget(os.Getenv("NL2SERVICE_BACKEND_TARGET")),client.WithTimeout(2*time.Second));impl:=&storageService{producer:producer}')
            main=main.replace('pb.RegisterGreeterService(server,&storageService{db:database})','pb.RegisterGreeterService(server,impl)\n kafka.RegisterKafkaHandlerService(server.Service("trpc.kafka.consumer.service"),func(ctx context.Context,msg *sarama.ConsumerMessage)error { result,err:=impl.HandleEvent(ctx,msg);if err!=nil {fmt.Println("EVENT_ERROR");return err};fmt.Println("EVENT_RESULT "+string(result));return nil })')
            config=CONFIG.replace('plugins:\n','    - name: trpc.kafka.consumer.service\n      address: ${NL2SERVICE_KAFKA_ADDRESS}\n      protocol: kafka\n      timeout: 2000\nplugins:\n')
            dependencies='trpc.group/trpc-go/trpc-database/kafka v1.0.0\n github.com/Shopify/sarama v1.29.1'
            placeholder=PLACEHOLDER.replace('"errors")','"errors";"github.com/Shopify/sarama")')+'\nfunc(s *storageService) HandleEvent(ctx context.Context,msg *sarama.ConsumerMessage)(json.RawMessage,error){return nil,errors.New("Agent must implement confirmed consumer requirement")}\n'
        return {'main.go':main,'service.go':placeholder,'trpc_go.yaml':config,'go.mod':'module '+spec.service.module+'\n\ngo 1.24\n\nrequire (\n trpc.group/trpc-go/trpc-go v1.0.3\n '+dependencies+'\n)\n'}
