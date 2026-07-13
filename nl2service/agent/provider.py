from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class LLMProvider:
    """Shared provider for creating and reusing chat models."""

    _models: dict[str, Any] = field(default_factory=dict)
    temperature: float = 0.0

    def get_model(self, model_name: str) -> Any:
        if model_name in self._models:
            return self._models[model_name]

        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "LangChain OpenAI integration is not installed. Run `pip install -e .` or install project dependencies first."
            ) from exc

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")

        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "model": model_name,
            "temperature": self.temperature,
        }
        base_url = os.getenv("OPENAI_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        organization = os.getenv("OPENAI_ORG_ID")
        if organization:
            kwargs["organization"] = organization
        project = os.getenv("OPENAI_PROJECT_ID")
        if project:
            kwargs["project"] = project

        model = ChatOpenAI(**kwargs)
        self._models[model_name] = model
        return model
