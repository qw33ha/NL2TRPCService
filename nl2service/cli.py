from pathlib import Path
from typing import Optional

import typer

from nl2service.agent.provider import LLMProvider
from nl2service.spec.io import dump_spec, load_spec_file
from nl2service.spec.validator import ServiceSpecValidator
from nl2service.workflow.runner import WorkflowRunner
from nl2service.workflow.session_store import WorkflowSessionStore

app = typer.Typer(help="Natural-language to service delivery scaffolding.")
session_store = WorkflowSessionStore()



def _print_state(state: dict) -> None:
    if state.get("error"):
        typer.echo(f"Workflow failed: {state['error']}")
        raise typer.Exit(code=1)

    spec = state.get("draft_spec")
    if spec is not None:
        typer.echo(f"Draft spec (model: {state.get('model') or 'default'}):")
        typer.echo(dump_spec(spec).strip())

    extracted_fields = state.get("extracted_fields", [])
    if extracted_fields:
        typer.echo("\nExtracted fields:")
        for field_name in extracted_fields:
            typer.echo(f"- {field_name}")

    notes = state.get("notes", [])
    if notes:
        typer.echo("\nSafety notes:")
        for note in notes:
            typer.echo(f"- {note}")

    status = state.get("status")
    if status == "awaiting_clarification":
        typer.echo("\nClarification questions:")
        for item in state.get("clarification_items", []):
            typer.echo(f"- {item['question']} ({item['field']}: {item['reason']})")
        return

    if state.get("gate_summary_lines"):
        typer.echo("\nGate summary:")
        for line in state["gate_summary_lines"]:
            typer.echo(f"- {line}")

    if status == "awaiting_gate_confirmation":
        typer.echo("\nAwaiting gate confirmation.")
        return

    if status == "awaiting_proto":
        typer.echo("\nProtocol required before formal tRPC generation:")
        for line in state.get("proto_summary_lines", []):
            typer.echo(f"- {line}")
        return

    if status == "awaiting_github_delivery":
        if state.get("output_dir"):
            typer.echo(f"\nRefined {len(state.get('rendered_files', {}))} files in {state['output_dir']}")
        verification_lines = state.get("verification_summary_lines", [])
        if verification_lines:
            typer.echo("\nBuild verification:")
            for line in verification_lines:
                typer.echo(f"- {line}")
        typer.echo("\nGitHub delivery summary:")
        for line in state.get("github_summary_lines", []):
            typer.echo(f"- {line}")
        return

    if status == "awaiting_github_actions":
        ci_run = state.get("ci_run", {})
        typer.echo("\nGitHub Actions is still running:")
        typer.echo(f"- Status: {ci_run.get('status')}")
        if ci_run.get("url"):
            typer.echo(f"- Run: {ci_run['url']}")
        typer.echo("Resume this session to check the same commit again.")
        return

    if status == "complete":
        report = state.get("delivery_report", {})
        typer.echo("\nDeployment completed successfully:")
        for label, key in [
            ("Repository", "repository_url"),
            ("Commit", "commit_sha"),
            ("GitHub Actions", "action_run_url"),
            ("Image", "image"),
            ("Environment", "environment"),
            ("Deployment", "deployment"),
            ("Endpoint", "endpoint"),
        ]:
            if report.get(key):
                typer.echo(f"- {label}: {report[key]}")
        return

    if status in {"rendered", "refined", "verified", "build_verification_failed", "repaired_from_build_feedback"}:
        rendered_files = state.get("rendered_files", {})
        output_dir = state.get("output_dir")
        label_map = {
            "rendered": "Rendered",
            "refined": "Refined",
            "verified": "Verified",
            "build_verification_failed": "Refined",
            "repaired_from_build_feedback": "Repaired",
        }
        label = label_map.get(status, "Rendered")
        if output_dir:
            typer.echo(f"\n{label} {len(rendered_files)} files to {output_dir}")
        else:
            typer.echo(f"\n{label} {len(rendered_files)} files")
        verification_lines = state.get("verification_summary_lines", [])
        if verification_lines:
            typer.echo("\nBuild verification:")
            for line in verification_lines:
                typer.echo(f"- {line}")
        refinement_notes = state.get("refinement_notes", [])
        if refinement_notes:
            typer.echo("\nRefinement notes:")
            for note in refinement_notes:
                typer.echo(f"- {note}")
        return

    if status == "delivered":
        delivery = state.get("github_delivery", {})
        verification_lines = state.get("verification_summary_lines", [])
        if verification_lines:
            typer.echo("\nBuild verification:")
            for line in verification_lines:
                typer.echo(f"- {line}")
        refinement_notes = state.get("refinement_notes", [])
        if refinement_notes:
            typer.echo("\nRefinement notes:")
            for note in refinement_notes:
                typer.echo(f"- {note}")
        typer.echo("\nGitHub delivery complete:")
        typer.echo(f"- Repository: {delivery.get('repository_full_name')}")
        typer.echo(f"- Branch: {delivery.get('branch')}")
        typer.echo(f"- Commit: {delivery.get('commit_sha')}")
        typer.echo(f"- URL: {delivery.get('repository_url')}")



def _interactive_resume(runner: WorkflowRunner, state: dict) -> dict:
    current = state
    while True:
        status = current.get("status")
        if status == "awaiting_clarification":
            answers: dict[str, str] = {}
            for item in current.get("clarification_items", []):
                answer = typer.prompt(f"{item['question']} [{item['field']}]")
                answers[item["field"]] = answer.strip()
                current.setdefault("clarification_history", []).append(
                    {"question": item["question"], "answer": answer.strip()}
                )
            current = runner.resume_with_answers(current, answers).state
            _print_state(current)
            continue

        if status == "awaiting_gate_confirmation":
            confirmed = typer.confirm("Approve gate and continue to render and refine?", default=True)
            if not confirmed:
                return current
            out_dir = typer.prompt("Output directory", default=str(Path("generated")))
            deliver = typer.confirm("Continue with GitHub delivery after refinement?", default=True)
            target_phase = "deliver" if deliver else "render"
            current = runner.resume_with_gate_confirmation(
                current,
                True,
                out_dir=out_dir,
                target_phase=target_phase,
            ).state
            _print_state(current)
            continue

        if status == "awaiting_proto":
            default_proto = ""
            spec = current.get("draft_spec")
            if spec is not None:
                default_proto = spec.service.proto_file or ""
            proto_file = typer.prompt("Path to the required .proto file", default=default_proto)
            current = runner.resume_with_proto_file(current, proto_file.strip()).state
            _print_state(current)
            continue

        if status == "awaiting_github_delivery":
            spec = current.get("draft_spec")
            default_owner = ""
            default_repo = ""
            if spec is not None:
                default_owner = spec.repo.owner or ""
                default_repo = spec.repo.name or ""
            owner = typer.prompt("GitHub owner or org", default=default_owner)
            repo = typer.prompt("GitHub repository name", default=default_repo)
            create_repo = typer.confirm("Create the repository before upload if needed?", default=True)
            commit_message = typer.prompt(
                "Commit message",
                default="Add generated NL2Service scaffold",
            )
            current = runner.resume_with_github_delivery(
                current,
                owner=owner.strip(),
                repo=repo.strip(),
                create_repo=create_repo,
                commit_message=commit_message.strip(),
            ).state
            _print_state(current)
            continue

        return current


@app.command()
def create(
    prompt: str = typer.Argument(..., help="Natural-language service request."),
    model: Optional[str] = typer.Option(None, help="LLM model name used for spec extraction and post-render refinement. Defaults to NL2SERVICE_OPENAI_MODEL or the workflow default."),
    context: Optional[list[str]] = typer.Option(None, "--context", help="Additional context lines to include in the same workflow state."),
    session_out: Optional[Path] = typer.Option(None, help="Optional path to save the workflow session state."),
    interactive: bool = typer.Option(True, "--interactive/--no-interactive", help="Use interactive mode to let the graph continue after clarification, gate, required-proto, build verification, refinement, and GitHub delivery pauses."),
) -> None:
    runner = WorkflowRunner(model=model, provider=LLMProvider())
    state = runner.create(prompt, additional_context=context or []).state
    _print_state(state)
    if interactive:
        state = _interactive_resume(runner, state)
    if session_out:
        session_store.save(state, session_out)
        typer.echo(f"\nSaved session to {session_out}")


@app.command()
def clarify(
    spec: Path = typer.Option(..., exists=True, dir_okay=False, help="Path to a draft YAML or JSON ServiceSpec."),
    model: Optional[str] = typer.Option(None, help="Optional workflow model name for consistency with the graph runner."),
    interactive: bool = typer.Option(True, "--interactive/--no-interactive", help="Use interactive mode to let the graph continue after clarification, gate, required-proto, build verification, refinement, and GitHub delivery pauses."),
    session_out: Optional[Path] = typer.Option(None, help="Optional path to save the workflow session state."),
) -> None:
    runner = WorkflowRunner(model=model, provider=LLMProvider())
    state = runner.clarify(load_spec_file(spec)).state
    _print_state(state)
    if interactive:
        state = _interactive_resume(runner, state)
    if session_out:
        session_store.save(state, session_out)
        typer.echo(f"\nSaved session to {session_out}")


@app.command()
def resume(
    session: Path = typer.Option(..., exists=True, dir_okay=False, help="Path to a saved workflow session."),
    interactive: bool = typer.Option(True, "--interactive/--no-interactive", help="Use interactive mode to let the graph continue after clarification, gate, required-proto, build verification, refinement, and GitHub delivery pauses."),
) -> None:
    state = session_store.load(session)
    runner = WorkflowRunner(model=state.get("model"), provider=LLMProvider())
    _print_state(state)
    if interactive:
        state = _interactive_resume(runner, state)
        session_store.save(state, session)
        typer.echo(f"\nUpdated session saved to {session}")


@app.command()
def validate(
    spec: Path = typer.Option(..., exists=True, dir_okay=False, help="Path to YAML or JSON ServiceSpec."),
) -> None:
    service_spec = load_spec_file(spec)
    validation = ServiceSpecValidator().validate(service_spec, require_proto=True)
    if validation.is_valid:
        typer.echo("Spec is valid.")
        return
    typer.echo("Validation failed:")
    for issue in validation.issues:
        typer.echo(f"- [{issue.severity}] {issue.field}: {issue.message}")
    raise typer.Exit(code=1)


@app.command()
def render(
    spec: Path = typer.Option(..., exists=True, dir_okay=False, help="Path to YAML or JSON ServiceSpec."),
    out: Path = typer.Option(Path("generated"), file_okay=False, help="Output directory."),
    model: Optional[str] = typer.Option(None, help="Optional workflow model name for consistency with the graph runner."),
) -> None:
    runner = WorkflowRunner(model=model, provider=LLMProvider())
    state = runner.render(load_spec_file(spec), out_dir=str(out)).state
    _print_state(state)


if __name__ == "__main__":
    app()
