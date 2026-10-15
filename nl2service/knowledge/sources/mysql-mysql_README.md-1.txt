# tRPC-Go mysql plugin

English | [中文](README_CN.md)

## Wrapping Standard Library Native Sql

## Client config

```yaml
client: #Back-end configuration for client calls.
  service: #Configuration for a single back-end.
    - name: trpc.mysql.xxx.xxx
      target: dsn://${username}:${passwd}@tcp(${vip}:${port})/${db}?timeout=1s&parseTime=true&interpolateParams=true #mdb needs to add &interpolateParams=true to use multiple instances of the domain.
    - name: trpc.mysql.xxx.xxx
      #mysql+polaris means target is uri, where host in uri will be parsed by Polaris to get address(host:port) and replace polaris_name.
      target: mysql+polaris://${username}:${passwd}@tcp(${polaris_name})/${db}?timeout=1s&parseTime=true&interpolateParams=true
```

## Unsafe Mode

For example, when the execution sql is `select id, name, age from users limit 1;` and the defined `struct` has only `id` and `name` fields, the execution query will report the error ` missing destination age in *User`.

To solve the problem mentioned above, you can get a Client with sqlx unsafe mode enabled through `NewUnsafeClient()` to make a query call, so that if the fields and structures do not match, no error will be reported and only the fields that meet the conditions will be checked. Please refer to the [sqlx Safety documentation](https://jmoiron.github.io/sqlx/#safety) for details.

Unsafe mode does not work with native `Exec` / `Query` / `QueryRow` / `Transaction`, which do not map model structs to table data, nor does Unsafe mode have side effects on these methods.

> **`Note: Unsafe mode may hide unintended field definition errors and should be used with caution.`**

## Usage
```go
package main

