{% if db_enabled and db_type == "mysql" %}
package handler

import (
	mysql "trpc.group/trpc-go/trpc-database/mysql"
)

type DBClient struct {
	proxy mysql.Client
}

func NewDBClient() *DBClient {
	return &DBClient{
		proxy: mysql.NewClientProxy("trpc.mysql.{{ group }}.{{ app }}.{{ server }}"),
	}
}

{% for table in db_tables %}
type {{ table | capitalize }} struct {
	ID int64 `json:"id"`
	// [LLM: add the remaining {{ table }} fields]
}

func (c *DBClient) Insert{{ table | capitalize }}(ctx context.Context, record *{{ table | capitalize }}) (int64, error) {
	result, err := c.proxy.Exec(ctx,
		"INSERT INTO {{ table }} (...) VALUES (...)",
		// [LLM: fill the remaining {{ table }} fields]
	)
	if err != nil {
		return 0, fmt.Errorf("Writing into {{ table }} failed: %w", err)
	}
	id, _ := result.LastInsertId()
	return id, nil
}

func (c *DBClient) Query{{ table | capitalize }}(ctx context.Context, dest interface{}, query string, args ...interface{}) error {
	return c.proxy.QueryToStructs(ctx, dest, query, args...)
}

func (c *DBClient) Exec{{ table | capitalize }}(ctx context.Context, query string, args ...interface{}) (int64, error) {
	result, err := c.proxy.Exec(ctx, query, args...)
	if err != nil {
		return 0, fmt.Errorf("Execution failed on {{ table }}: %w", err)
	}
	return result.RowsAffected()
}
{% endfor %}
{% endif %}
