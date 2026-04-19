from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InterpretedRequest:
    """Legacy compatibility container kept for older imports."""

    original_question: str
    retrieval_question: str
    preferred_sources: list[str] = field(default_factory=list)
    wants_command_answer: bool = False


class RequirementUnderstandingAgent:
    """Legacy compatibility shim.

    This module is no longer part of the active routing path.
    """

    def analyze(self, question: str, last_reference=None) -> InterpretedRequest:
        return InterpretedRequest(
            original_question=question,
            retrieval_question=question,
            preferred_sources=[],
            wants_command_answer=False,
        )


class RetrievalAgent:
    """Legacy compatibility shim."""

    def select_connectors(
        self,
        connectors: list,
        interpreted: InterpretedRequest,
        connector_hints: dict[str, tuple[str, ...]],
        last_reference=None,
    ) -> list:
        return [connector for connector in connectors if getattr(connector, "configured", False)]


class AnswerSynthesisAgent:
    """Legacy compatibility shim."""

    def compose(
        self,
        responder,
        question: str,
        evidence_text: str,
        conversation_history: list[dict[str, str]],
    ) -> str:
        return responder.generate(question, evidence_text, conversation_history)
