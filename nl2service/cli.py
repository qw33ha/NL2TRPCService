from pathlib import Path
from typing import Optional

import typer

from nl2service.agent.provider import LLMProvider
from nl2service.agent.events import AgentTurn
from nl2service.agent.runtime import AgentSession
from nl2service.runtime.github_worker import GitHubActionsWorker

app = typer.Typer(help="Natural-language to service delivery scaffolding.")


def _print_agent_turn(turn: AgentTurn) -> None:
    for event in turn.events:
        prefix = {
            "question": "Agent",
            "approval": "Agent",
            "progress": "Status",
            "external_wait": "Status",
            "completed": "Complete",
            "error": "Error",
        }.get(event.kind, "Agent")
        typer.echo(f"{prefix}: {event.text}")
        if event.kind == "completed":
            for key in [
                "repository_url",
                "commit_sha",
                "action_run_url",
                "image",
                "image_digest",
                "environment",
                "deployment",
                "endpoint",
            ]:
                if event.data.get(key):
                    typer.echo(f"  {key}: {event.data[key]}")


@app.command()
def chat(
    request: Optional[str] = typer.Argument(None, help="Initial natural-language service request."),
    thread: Optional[str] = typer.Option(None, help="Existing conversation thread ID to continue."),
    model: Optional[str] = typer.Option(None, help="LLM model used by the service agent."),
    database: Path = typer.Option(
        Path.home() / ".nl2service" / "agent.db",
        help="SQLite checkpoint database used for durable conversations.",
    ),
) -> None:
    """Talk to the persistent service-delivery agent in one conversation."""
    session = AgentSession(model=model, provider=LLMProvider(), database_path=database)
    thread_id = thread or session.new_thread_id()
    typer.echo(f"Conversation: {thread_id}")
    message = request or typer.prompt("You")
    try:
        while True:
            turn = session.handle_message(thread_id, message)
            _print_agent_turn(turn)

            if turn.waiting_for == "external_wait":
                worker = GitHubActionsWorker(session)
                turn = worker.run_until_terminal(thread_id, on_turn=_print_agent_turn)

            if turn.status in {"complete", "cancelled", "error", "verified"} and not turn.waiting_for:
                break
            message = typer.prompt("You")
    except (KeyboardInterrupt, EOFError):
        typer.echo(f"\nConversation paused. Continue later with: nl2service chat --thread {thread_id}")
    finally:
        session.close()


if __name__ == "__main__":
    app()
