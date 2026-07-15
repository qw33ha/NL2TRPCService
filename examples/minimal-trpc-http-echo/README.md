# minimal-trpc-http-echo

This example shows the smallest open-source-friendly split:

- `builder` stage uses the public `golang` image to compile a Go binary with the `trpc-go` dependency.
- `runtime` stage uses a small public base image and does not preinstall any separate `trpc` system command.

The resulting container exposes:

- `POST /echo` on port `8080`
- `GET /health` on port `8080`
- a minimal `trpc-go` runtime configured on port `9000`

Build:

```bash
docker build -t minimal-trpc-http-echo .
```

Run:

```bash
docker run --rm -p 8080:8080 -p 9000:9000 minimal-trpc-http-echo
```

Try:

```bash
curl -X POST http://localhost:8080/echo -H "Content-Type: application/json" -d "{\"message\":\"hello\"}"
```
