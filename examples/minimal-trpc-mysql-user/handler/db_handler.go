package handler

import (
	"context"
	"errors"
	"fmt"
	"time"

	mysql "trpc.group/trpc-go/trpc-database/mysql"
)

const mysqlServiceName = "demo.minimaltrpcmysqluser.mysql"

var ErrUserNotFound = errors.New("user not found")

type User struct {
	ID        int64     `db:"id" json:"id"`
	Name      string    `db:"name" json:"name"`
	Email     string    `db:"email" json:"email"`
	CreatedAt time.Time `db:"created_at" json:"created_at"`
}

// MySQLHandler owns database operations. Transport handlers call it without
// knowing how the MySQL client is configured or how records are persisted.
type MySQLHandler struct {
	client mysql.Client
}

func NewMySQLHandler() *MySQLHandler {
	return &MySQLHandler{
		client: mysql.NewClientProxy(mysqlServiceName),
	}
}

func (h *MySQLHandler) CreateUser(ctx context.Context, name, email string) (*User, error) {
	result, err := h.client.Exec(ctx,
		"INSERT INTO users (name, email) VALUES (?, ?)",
		name,
		email,
	)
	if err != nil {
		return nil, fmt.Errorf("insert user: %w", err)
	}

	id, err := result.LastInsertId()
	if err != nil {
		return nil, fmt.Errorf("read inserted user id: %w", err)
	}

	return h.GetUser(ctx, id)
}

func (h *MySQLHandler) GetUser(ctx context.Context, id int64) (*User, error) {
	user := &User{}
	if err := h.client.Get(ctx, user,
		"SELECT id, name, email, created_at FROM users WHERE id = ?",
		id,
	); err != nil {
		if mysql.IsNoRowsError(err) {
			return nil, ErrUserNotFound
		}
		return nil, fmt.Errorf("get user: %w", err)
	}
	return user, nil
}

func (h *MySQLHandler) UpdateUser(ctx context.Context, id int64, name, email string) (*User, error) {
	result, err := h.client.Exec(ctx,
		"UPDATE users SET name = ?, email = ? WHERE id = ?",
		name,
		email,
		id,
	)
	if err != nil {
		return nil, fmt.Errorf("update user: %w", err)
	}
	rows, err := result.RowsAffected()
	if err != nil {
		return nil, fmt.Errorf("read updated rows: %w", err)
	}
	if rows == 0 {
		return nil, ErrUserNotFound
	}
	return h.GetUser(ctx, id)
}

func (h *MySQLHandler) DeleteUser(ctx context.Context, id int64) error {
	result, err := h.client.Exec(ctx, "DELETE FROM users WHERE id = ?", id)
	if err != nil {
		return fmt.Errorf("delete user: %w", err)
	}
	rows, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("read deleted rows: %w", err)
	}
	if rows == 0 {
		return ErrUserNotFound
	}
	return nil
}
