{% if db_type == "redis" %}
package handler

import (
	goredis "trpc.group/trpc-go/trpc-database/goredis"
)

const RedisServiceName = "{{ db_service_name }}"

func NewRedisClient() (any, error) {
	return goredis.New(RedisServiceName)
}
{% endif %}
