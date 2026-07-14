{% if db_type == "redis" %}
package handler

import (
	"context"
	"time"
	"trpc.group/trpc-go/trpc-database/redis"
)

type RedisClient struct {
	proxy redis.Client
}

func NewRedisClient() *RedisClient {
	return &RedisClient{
		proxy: redis.NewClientProxy("trpc.redis.{{ group }}.{{ app }}.{{ server }}"),
	}
}

func (c *RedisClient) Get(ctx context.Context, key string) (string, error) {
	reply, err := c.proxy.Do(ctx, "GET", key)
	if err != nil {
		return "", err
	}
	if reply == nil {
		return "", nil
	}
	return redis.String(reply, err)
}

func (c *RedisClient) Set(ctx context.Context, key string, value interface{}, ttl time.Duration) error {
	if ttl > 0 {
		_, err := c.proxy.Do(ctx, "SET", key, value, "EX", int(ttl.Seconds()))
		return err
	}
	_, err := c.proxy.Do(ctx, "SET", key, value)
	return err
}

func (c *RedisClient) Del(ctx context.Context, keys ...string) (int64, error) {
	args := make([]interface{}, len(keys))
	for i, k := range keys {
		args[i] = k
	}
	return redis.Int64(c.proxy.Do(ctx, "DEL", args...))
}
{% endif %}
