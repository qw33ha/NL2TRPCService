# minimal-trpc-mysql-user

This example uses the public tRPC-Go MySQL plugin. `MySQLHandler` in `handler/db_handler.go` owns persistence, while `handler/http_handler.go` only translates HTTP requests. `main.go` wires the handlers together.

The database handler demonstrates parameterized create, read, update, and delete operations.

The MySQL instance and `users` table are supplied by the user. The service does not create infrastructure or run schema migrations.

Required schema:

```sql
CREATE TABLE IF NOT EXISTS users (
    id BIGINT NOT NULL AUTO_INCREMENT,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);
```

Set the connection values in your shell. Do not commit real credentials:

```bash
export MYSQL_HOST=127.0.0.1
export MYSQL_PORT=3306
export MYSQL_DATABASE=Messages
export MYSQL_USER=example_user
export MYSQL_PASSWORD=replace_me
```

Run:

```bash
go run . -conf=trpc_go.yaml
```

Create a user:

```bash
curl -X POST http://localhost:8081/users \
  -H "Content-Type: application/json" \
  -d '{"name":"Ada Lovelace","email":"ada@example.com"}'
```

A successful request returns the row written to MySQL with HTTP status `201`.

Read the user:

```bash
curl "http://localhost:8081/users?id=1"
```

Update the user:

```bash
curl -X PUT "http://localhost:8081/users?id=1" \
  -H "Content-Type: application/json" \
  -d '{"name":"Ada Byron","email":"ada.byron@example.com"}'
```

Delete the user:

```bash
curl -i -X DELETE "http://localhost:8081/users?id=1"
```

Successful deletion returns HTTP status `204`. Reading the same ID afterwards returns `404`.

The same example can be built as a container:

```bash
docker build -t minimal-trpc-mysql-user .
docker run --rm -p 8081:8081 --env-file .env minimal-trpc-mysql-user
```
