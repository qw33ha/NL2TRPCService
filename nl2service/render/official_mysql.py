"""Opt-in deterministic wire skeleton; variable SQL implementation belongs to the Agent."""
from pathlib import Path
from nl2service.render.renderer import ServiceRenderer, ProtoContractError

PROTO = Path(__file__).parents[1] / "knowledge/sources/helloworld.proto"

MAIN = '''package main
import (
 "context"
 "encoding/json"
 "fmt"
 "os"
 "time"
 trpc "trpc.group/trpc-go/trpc-go"
 "trpc.group/trpc-go/trpc-go/client"
 "trpc.group/trpc-go/trpc-go/errs"
 mysql "trpc.group/trpc-go/trpc-database/mysql"
 pb "trpc.group/trpc-go/trpc-go/testdata/trpc/helloworld"
)
type storageService struct { db mysql.Client }
func (s *storageService) SayHello(ctx context.Context, request *pb.HelloRequest) (*pb.HelloReply,error) {
 result,err:=s.Execute(ctx,json.RawMessage(request.Msg))
 if err!=nil { return nil,errs.NewFrameError(errs.RetServerSystemErr,"storage operation failed") }
 return &pb.HelloReply{Msg:string(result)},nil
}
func (s *storageService) SayHi(ctx context.Context, request *pb.HelloRequest) (*pb.HelloReply,error) { return s.SayHello(ctx,request) }
func main() {
 server:=trpc.NewServer()
 if request:=os.Getenv("NL2SERVICE_RPC_REQUEST"); request!="" {
  proxy:=pb.NewGreeterClientProxy()
  reply,err:=proxy.SayHello(context.Background(), &pb.HelloRequest{Msg:request},client.WithTarget(os.Getenv("NL2SERVICE_RPC_TARGET")),client.WithTimeout(5*time.Second))
  if err!=nil { fmt.Fprintln(os.Stderr,err);os.Exit(2) }
  fmt.Println(reply.Msg);return
 }
 database:=mysql.NewClientProxy("trpc.mysql.nl2service.storage",client.WithTarget(os.Getenv("NL2SERVICE_MYSQL_TARGET")))
 pb.RegisterGreeterService(server,&storageService{db:database})
 if err:=server.Serve();err!=nil { fmt.Fprintln(os.Stderr,err);os.Exit(2) }
}
'''
CONFIG = '''global:
  namespace: development
  env_name: local-evaluation
server:
  app: nl2service
  server: officialmysql
  bin_path: .
  conf_path: .
  data_path: .
  service:
    - name: trpc.test.helloworld.Greeter
      ip: 127.0.0.1
      port: ${NL2SERVICE_RPC_PORT}
      network: tcp
      protocol: trpc
      timeout: 5000
plugins:
  log:
    default:
      - writer: console
        level: error
'''
PLACEHOLDER = '''package main
import ("context"; "encoding/json"; "errors")
func(s *storageService) Execute(ctx context.Context,payload json.RawMessage)(json.RawMessage,error) {
 return nil,errors.New("Agent must implement the confirmed database requirement")
}
'''


class OfficialMySQLRenderer(ServiceRenderer):
    immutable_paths = ("main.go", "go.mod", "trpc_go.yaml")
    generation_contract = {"implementation_file":"service.go","implementation_symbol":"storageService.Execute",
                           "managed_files":["main.go","go.mod","trpc_go.yaml","go.sum"],
                           "supporting_files":"authored Go helpers only"}

    def render_tree(self, spec):
        if spec.service.enable_http or not spec.service.enable_trpc or spec.database.type != "mysql" or not spec.database.enabled:
            raise ProtoContractError("Official MySQL prototype requires RPC-only MySQL capability.")
        if not spec.service.proto_file or Path(spec.service.proto_file).read_text(encoding="utf-8").strip() != PROTO.read_text(encoding="utf-8").strip():
            raise ProtoContractError("This initial path supports only the pinned official Greeter wire contract; custom proto generation remains separate.")
        self.generation_contract={**OfficialMySQLRenderer.generation_contract,'database_mapping':{
            'column_tag':'db','wire_tag':'json','struct_reads_require_explicit_column_mapping':True,
            'directly_serialized_row_structs_require_both_tags':True,
            'columns_by_table':{table.name:[column.name for column in table.columns] for table in spec.database.tables}}}
        return {"main.go": MAIN, "service.go": PLACEHOLDER, "trpc_go.yaml": CONFIG,
                "go.mod": "module " + spec.service.module + "\n\ngo 1.24\n\nrequire (\n trpc.group/trpc-go/trpc-go v1.0.3\n trpc.group/trpc-go/trpc-database/mysql v1.0.0\n)\n"}
