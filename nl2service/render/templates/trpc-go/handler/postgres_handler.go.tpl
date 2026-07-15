{% if db_enabled and db_type == "postgres" %}
package handler

import (
	"context"
	"fmt"

	"gorm.io/gorm"
	trpcgorm "trpc.group/trpc-go/trpc-database/gorm"
)

// PostgreSQLHandler owns PostgreSQL operations so transport and business
// handlers do not need to know how the GORM client is configured.
type PostgreSQLHandler struct {
	db *gorm.DB
}

func NewPostgreSQLHandler() (*PostgreSQLHandler, error) {
	db, err := trpcgorm.NewClientProxy("{{ db_service_name }}")
	if err != nil {
		return nil, fmt.Errorf("create PostgreSQL client: %w", err)
	}
	return &PostgreSQLHandler{db: db}, nil
}

{% for table in db_tables %}
type {{ table | go_ident }} struct {
	ID int64 `gorm:"column:id;primaryKey" json:"id"`
	// [LLM: add the remaining {{ table }} fields with explicit gorm column tags]
}

func ({{ table | go_ident }}) TableName() string {
	return "{{ table }}"
}

// Insert{{ table | go_ident }} writes one record using GORM's parameterized statements.
func (h *PostgreSQLHandler) Insert{{ table | go_ident }}(ctx context.Context, record *{{ table | go_ident }}) (int64, error) {
	if err := h.db.WithContext(ctx).Create(record).Error; err != nil {
		return 0, fmt.Errorf("insert {{ table }}: %w", err)
	}
	return record.ID, nil
}

// Query{{ table | go_ident }} executes a parameterized PostgreSQL query and scans its rows.
func (h *PostgreSQLHandler) Query{{ table | go_ident }}(ctx context.Context, dest interface{}, query string, args ...interface{}) error {
	if err := h.db.WithContext(ctx).Raw(query, args...).Scan(dest).Error; err != nil {
		return fmt.Errorf("query {{ table }}: %w", err)
	}
	return nil
}

// Execute{{ table | go_ident }} runs a parameterized update or other write statement.
func (h *PostgreSQLHandler) Execute{{ table | go_ident }}(ctx context.Context, query string, args ...interface{}) (int64, error) {
	return h.execute{{ table | go_ident }}(ctx, "execute", query, args...)
}

// Delete{{ table | go_ident }} runs a parameterized delete statement.
func (h *PostgreSQLHandler) Delete{{ table | go_ident }}(ctx context.Context, query string, args ...interface{}) (int64, error) {
	return h.execute{{ table | go_ident }}(ctx, "delete", query, args...)
}

func (h *PostgreSQLHandler) execute{{ table | go_ident }}(ctx context.Context, operation, query string, args ...interface{}) (int64, error) {
	result := h.db.WithContext(ctx).Exec(query, args...)
	if result.Error != nil {
		return 0, fmt.Errorf("%s {{ table }}: %w", operation, result.Error)
	}
	return result.RowsAffected, nil
}
{% endfor %}
{% endif %}
