"""Abstract LLM provider interface for BitGN agent."""

from abc import ABC, abstractmethod

from src.models import NextStep


class LLMProvider(ABC):
    @abstractmethod
    def get_next_step(self, messages: list[dict], system_prompt: str) -> NextStep:
        """Given conversation history and system prompt, return the next agent action."""
        ...

    @abstractmethod
    def provider_name(self) -> str: ...
