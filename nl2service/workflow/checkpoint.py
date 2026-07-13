from dataclasses import dataclass


@dataclass(slots=True)
class WorkflowCheckpoint:
    name: str
    completed: bool = False
    detail: str = ""
