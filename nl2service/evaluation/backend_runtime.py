"""Disposable loopback Redis and real Apache Kafka; no persistent credentials."""
import json,subprocess,time,uuid
from nl2service.evaluation.mysql_runtime import free_port,RPCService

REDIS_IMAGE='redis@sha256:fbdbaea47b9ae4ecc2082ecdb4e1cea81e32176ffb1dcf643d422ad07427e5d9'
KAFKA_IMAGE='apache/kafka@sha256:4ceccc577f03f51f6af8dbfda55194d0d892f4fa7913ffbded567ce3895622ed'


class BackendRuntime:
    password='unused-no-password'
    def __init__(self,kind): self.kind=kind;self.name='nl2service-'+kind+'-'+uuid.uuid4().hex[:12];self.port=free_port();self.paused=False
    def __enter__(self):
        cmd=['docker','run','--rm','-d','--name',self.name,'-p',f'127.0.0.1:{self.port}:'+('6379' if self.kind=='redis' else '9092')]
        if self.kind=='redis': cmd += [REDIS_IMAGE,'redis-server','--save','','--appendonly','no']
        else:
            values={'KAFKA_NODE_ID':'1','KAFKA_PROCESS_ROLES':'broker,controller','KAFKA_LISTENERS':'EXTERNAL://:9092,INTERNAL://:9094,CONTROLLER://:9093','KAFKA_ADVERTISED_LISTENERS':f'EXTERNAL://127.0.0.1:{self.port},INTERNAL://localhost:9094','KAFKA_LISTENER_SECURITY_PROTOCOL_MAP':'EXTERNAL:PLAINTEXT,INTERNAL:PLAINTEXT,CONTROLLER:PLAINTEXT','KAFKA_INTER_BROKER_LISTENER_NAME':'INTERNAL','KAFKA_CONTROLLER_LISTENER_NAMES':'CONTROLLER','KAFKA_CONTROLLER_QUORUM_VOTERS':'1@localhost:9093','KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR':'1','KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR':'1','KAFKA_TRANSACTION_STATE_LOG_MIN_ISR':'1','KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS':'0'}
            for key,value in values.items():cmd+=['-e',key+'='+value]
            cmd+=[KAFKA_IMAGE]
        try:
            subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",check=True,timeout=120)
            deadline=time.monotonic()+120
            while True:
                try:
                    if self.kind=='redis': assert self.redis('PING')=='PONG'
                    else:self.kafka('kafka-topics.sh','--list')
                    break
                except Exception:
                    if time.monotonic()>deadline:raise RuntimeError(self.kind+' readiness timeout')
                    time.sleep(1)
            self.reset();return self
        except Exception:self.__exit__();raise
    def redis(self,*args):
        return subprocess.run(['docker','exec',self.name,'redis-cli','--raw',*map(str,args)],capture_output=True,text=True,encoding="utf-8",check=True,timeout=10).stdout.strip()
    def kafka(self,script,*args,input=None,timeout=20):
        result=subprocess.run(['docker','exec','-i',self.name,'/opt/kafka/bin/'+script,'--bootstrap-server','localhost:9094',*map(str,args)],input=input,capture_output=True,text=True,encoding="utf-8",timeout=timeout)
        if result.returncode and not (script=='kafka-console-consumer.sh' and 'TimeoutException' in result.stderr):raise RuntimeError(result.stderr[-1500:])
        return result.stdout.strip()
    def reset(self):
        if self.kind=='redis':
            self.redis('FLUSHDB');self.target=f'redis://127.0.0.1:{self.port}/0?max_retries=-1&dial_timeout=500&read_timeout=500&write_timeout=500'
        else:
            self.topic='nl2eval_'+uuid.uuid4().hex[:12];self.group='group_'+uuid.uuid4().hex[:12]
            self.kafka('kafka-topics.sh','--create','--topic',self.topic,'--partitions','1','--replication-factor','1')
            self.target=f'kafka://127.0.0.1:{self.port}?topic={self.topic}&clientid=nl2eval&version=2.1.0&async=0'
            self.address=f'127.0.0.1:{self.port}?topics={self.topic}&group={self.group}&version=2.1.0'
    def messages(self):
        text=self.kafka('kafka-console-consumer.sh','--topic',self.topic,'--from-beginning','--timeout-ms','1500','--property','print.key=true','--property','key.separator=\t',timeout=15)
        return [line.split('\t',1) for line in text.splitlines() if '\t' in line]
    def inject(self,value):self.kafka('kafka-console-producer.sh','--topic',self.topic,input=value+'\n')
    def pause(self):subprocess.run(['docker','pause',self.name],capture_output=True,check=True);self.paused=True
    def unpause(self):
        if self.paused:subprocess.run(['docker','unpause',self.name],capture_output=True,check=True);self.paused=False
    def __exit__(self,*args):self.unpause();subprocess.run(['docker','stop','-t','5',self.name],capture_output=True,timeout=30)


class BackendRPCService(RPCService):
    def __init__(self,root,backend):
        super().__init__(root,backend);self.backend=backend
        self.env.pop('NL2SERVICE_MYSQL_TARGET',None);self.env['NL2SERVICE_BACKEND_TARGET']=backend.target
        if backend.kind=='kafka':self.env['NL2SERVICE_KAFKA_ADDRESS']=backend.address
    def consumer_ready(self):
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            try:
                text=self.backend.kafka('kafka-consumer-groups.sh','--describe','--group',self.backend.group,'--state')
                if 'Stable' in text:return
            except Exception:pass
            time.sleep(.5)
        raise RuntimeError('Official Kafka consumer group did not stabilize.')
    def events(self):
        self.log.flush();text=(self.root/'rpc-runtime.log').read_text(encoding='utf-8',errors='replace')
        return [json.loads(line.split('EVENT_RESULT ',1)[1]) for line in text.splitlines() if line.startswith('EVENT_RESULT ')]
    def wait_event(self,expected):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if expected in self.events():return True
            time.sleep(.1)
        return False
