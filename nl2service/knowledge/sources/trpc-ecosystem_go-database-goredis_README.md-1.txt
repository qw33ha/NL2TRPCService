# tRPC-Go go-redis plugin

English | [中文](README_CN.md)

## Principle
Use hook technology to expand the open source github.com/go-redis/redis.

## Use
### 1 Configure trpc_go.yaml file
```yaml
client:                                            # Backend configuration for client.
  service:                                         # The service provided by the business service can have multiple.
    - name: trpc.gamecenter.test.redis            # The service name of the backend service.
      target: redis://127.0.0.1:6379              # Request service address format：redis://<user>:<password>@<host>:<port>/<db_number>
      timeout: 60000
```

### 2 Test case
```go
// Test_New redis initialization
func Test_New(t *testing.T) {
	// Extended interface.
	cli, err := New("trpc.gamecenter.test.redis")
	if err != nil {
		t.Fatalf("new fail err=[%v]", err)
	}
	// go-redis Set
	result, err := cli.Set(trpc.BackgroundContext(), "key", "value", 0).Result()
	if err != nil {
		t.Fatalf("set fail err=[%v]", err)
	}
	t.Logf("Set result=[%v]", result)
	// go-redis Get
	value, err := cli.Get(trpc.BackgroundContext(), "key").Result()
	if err != nil {
		t.Fatalf("get fail err=[%v]", err)
	}
	t.Logf("Get value=[%v]", value)
}
```

# url format
```html
  A: <scheme>://<user>:<password>@<host>:<port>/<db_number>?<is_proxy=true><?min_idle_conns=10>
```

