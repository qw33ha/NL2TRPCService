{% if db_enabled and db_type == "mysql" %}
package handler

import (
	"context"
	"fmt"

	mysql "trpc.group/trpc-go/trpc-database/mysql"
)

// MySQLHandler owns MySQL operations so transport and business handlers do not
// need to know how the database client is configured.
type MySQLHandler struct {
	client mysql.Client
}

func NewMySQLHandler() *MySQLHandler {
	return &MySQLHandler{
		client: mysql.NewClientProxy("{{ db_service_name }}"),
	}
}

{% for table in db_tables %}
type {{ table | go_ident }} struct {
	ID int64 `db:"id" json:"id"`
	// [LLM: add the remaining {{ table }} fields]
}

// Insert{{ table | go_ident }} writes one {{ table }} record using parameterized values.
func (h *MySQLHandler) Insert{{ table | go_ident }}(ctx context.Context, record *{{ table | go_ident }}) (int64, error) {
	result, err := h.client.Exec(ctx,
		"INSERT INTO {{ table }} (...) VALUES (...)",
		// [LLM: fill the remaining {{ table }} fields]
	)
	if err != nil {
		return 0, fmt.Errorf("insert {{ table }}: %w", err)
	}
	id, err := result.LastInsertId()
	if err != nil {
		return 0, fmt.Errorf("read inserted {{ table }} id: %w", err)
	}
	return id, nil
}

// Query{{ table | go_ident }} reads rows into dest. Callers must use placeholders
// for all external values supplied through args.
func (h *MySQLHandler) Query{{ table | go_ident }}(ctx context.Context, dest interface{}, query string, args ...interface{}) error {
	if err := h.client.QueryToStructs(ctx, dest, query, args...); err != nil {
		return fmt.Errorf("query {{ table }}: %w", err)
	}
	return nil
}

// Execute{{ table | go_ident }} runs a parameterized update or other write statement.
func (h *MySQLHandler) Execute{{ table | go_ident }}(ctx context.Context, query string, args ...interface{}) (int64, error) {
	return h.execute{{ table | go_ident }}(ctx, "execute", query, args...)
}

// Delete{{ table | go_ident }} runs a parameterized delete statement.
func (h *MySQLHandler) Delete{{ table | go_ident }}(ctx context.Context, query string, args ...interface{}) (int64, error) {
	return h.execute{{ table | go_ident }}(ctx, "delete", query, args...)
}

func (h *MySQLHandler) execute{{ table | go_ident }}(ctx context.Context, operation, query string, args ...interface{}) (int64, error) {
	result, err := h.client.Exec(ctx, query, args...)
	if err != nil {
		return 0, fmt.Errorf("%s {{ table }}: %w", operation, err)
	}
	rows, err := result.RowsAffected()
	if err != nil {
		return 0, fmt.Errorf("read affected {{ table }} rows: %w", err)
	}
	return rows, nil
}
{% endfor %}
{% endif %}
