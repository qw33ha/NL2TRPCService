# NL2Service

`NL2Service` is an MVP for turning natural-language backend requests into a validated service specification and deterministic delivery artifacts.

## MVP scope

- Pydantic `ServiceSpec` models
- Rule-based validation and clarification prompts
- Gate summary generation for risky operations
- Jinja-based artifact renderer
- Typer CLI for local rendering from YAML specs

## Quick start

```bash
pip install -e .[dev]
nl2service render --spec examples/dau-service.yaml --out generated/dau-service
```

## Layout

```text
nl2service/
  agent/
  render/
  spec/
  tools/
  workflow/
tests/
examples/
```