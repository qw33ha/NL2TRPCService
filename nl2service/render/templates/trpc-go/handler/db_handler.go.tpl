{% if db_enabled and db_type == "mysql" %}
package handler

import (
	mysql "trpc.group/trpc-go/trpc-database/mysql"
)

const MySQLServiceName = "{{ db_service_name }}"

func NewMySQLProxy() any {
	return mysql.NewClientProxy(MySQLServiceName)
}

{% for table in db_tables %}
type {{ table | capitalize }}Record struct {
	ID int64 `json:"id"`
	// [LLM: add the remaining {{ table }} fields]
}
{% endfor %}
{% endif %}
