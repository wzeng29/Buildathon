from __future__ import annotations

import json
from typing import Any

import requests

from config import settings
from src.models import LLMToolCall, LLMToolResponse

OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
REQUEST_TIMEOUT_SECONDS = 60


class OpenAIResponder:
    """Small wrapper around the OpenAI chat completions API."""

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        }

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> str:
        """Run a generic completion request with explicit system and user prompts."""
        if not settings.openai_api_key:
            return ""

        try:
            response = requests.post(
                OPENAI_CHAT_COMPLETIONS_URL,
                headers=self._headers(),
                json={
                    "model": settings.openai_model,
                    "temperature": temperature,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            return payload["choices"][0]["message"]["content"].strip()
        except requests.RequestException:
            return ""

    def call_function(
        self,
        system_prompt: str,
        user_prompt: str,
        function_name: str,
        function_description: str,
        parameters: dict[str, Any],
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """Force a function tool call and return parsed arguments."""
        if not settings.openai_api_key:
            return {}

        try:
            response = requests.post(
                OPENAI_CHAT_COMPLETIONS_URL,
                headers=self._headers(),
                json={
                    "model": settings.openai_model,
                    "temperature": temperature,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": function_name,
                                "description": function_description,
                                "parameters": parameters,
                            },
                        }
                    ],
                    "tool_choice": {
                        "type": "function",
                        "function": {"name": function_name},
                    },
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            choices = payload.get("choices", [])
            if not choices:
                return {}
            message = choices[0].get("message", {})
            tool_calls = message.get("tool_calls", [])
            if not tool_calls:
                return {}
            function_call = tool_calls[0].get("function", {})
            arguments = function_call.get("arguments", "")
            if not isinstance(arguments, str) or not arguments.strip():
                return {}
            parsed = json.loads(arguments)
            return parsed if isinstance(parsed, dict) else {}
        except (requests.RequestException, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
            return {}

    def respond_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.1,
    ) -> LLMToolResponse:
        """Return assistant text plus any tool calls for multi-step execution loops."""
        if not settings.openai_api_key:
            return LLMToolResponse(content="")

        try:
            response = requests.post(
                OPENAI_CHAT_COMPLETIONS_URL,
                headers=self._headers(),
                json={
                    "model": settings.openai_model,
                    "temperature": temperature,
                    "messages": messages,
                    "tools": tools,
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            choices = payload.get("choices", [])
            if not choices:
                return LLMToolResponse(content="")

            message = choices[0].get("message", {})
            content = message.get("content") or ""
            if not isinstance(content, str):
                content = ""
            raw_tool_calls = message.get("tool_calls", [])
            tool_calls: list[LLMToolCall] = []
            for index, raw_tool_call in enumerate(raw_tool_calls):
                if not isinstance(raw_tool_call, dict):
                    continue
                function_call = raw_tool_call.get("function", {})
                if not isinstance(function_call, dict):
                    continue
                name = str(function_call.get("name") or "").strip()
                if not name:
                    continue
                arguments = function_call.get("arguments", "")
                parsed_arguments: dict[str, Any] = {}
                if isinstance(arguments, str) and arguments.strip():
                    try:
                        decoded = json.loads(arguments)
                        if isinstance(decoded, dict):
                            parsed_arguments = decoded
                    except json.JSONDecodeError:
                        parsed_arguments = {}
                tool_calls.append(
                    LLMToolCall(
                        id=str(raw_tool_call.get("id") or f"tool_call_{index + 1}"),
                        name=name,
                        arguments=parsed_arguments,
                    )
                )
            return LLMToolResponse(content=content.strip(), tool_calls=tool_calls)
        except requests.RequestException:
            return LLMToolResponse(content="")

    def generate(
        self,
        question: str,
        evidence_text: str,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        """Generate a concise answer or fall back to deterministic output."""
        if not settings.openai_api_key:
            return self._fallback(question, evidence_text, conversation_history or [])

        messages = []
        for message in conversation_history or []:
            if message.get("role") in {"user", "assistant"} and message.get("content"):
                messages.append(
                    {
                        "role": message["role"],
                        "content": message["content"],
                    }
                )
        history_text = "\n".join(
            f"{item['role']}: {item['content']}" for item in messages
        )
        response_text = self.complete(
            system_prompt=(
                "You answer enterprise support questions using only the provided evidence. "
                "Be concise. If the evidence is weak or incomplete, say so clearly. "
                "Cite only facts grounded in the evidence. "
                "If the evidence contains a direct answer, state it plainly."
            ),
            user_prompt=(
                f"Conversation history:\n{history_text or 'None'}\n\n"
                f"Question:\n{question}\n\n"
                f"Evidence:\n{evidence_text}\n\n"
                "Respond with a concise answer grounded in the evidence."
            ),
            temperature=0.2,
        )
        if response_text:
            return response_text
        return self._fallback(question, evidence_text, conversation_history or [])

    @staticmethod
    def _fallback(
        question: str,
        evidence_text: str,
        conversation_history: list[dict[str, str]],
    ) -> str:
        """Return a minimal evidence summary when the OpenAI call is unavailable."""
        if not evidence_text.strip():
            return (
                "I could not find enough evidence in Jira or Confluence "
                "to answer that confidently."
            )

        history_prefix = ""
        if conversation_history:
            history_prefix = f"Conversation context available: {len(conversation_history)} prior messages.\n\n"
        summary = OpenAIResponder._compact_evidence(evidence_text)

        return (
            f"{history_prefix}Question: {question}\n\n"
            "I found relevant evidence and summarized it below.\n\n"
            f"{summary}"
        )

    @staticmethod
    def _compact_evidence(evidence_text: str, max_chars: int = 2400) -> str:
        """Keep whole evidence blocks instead of truncating raw characters mid-record."""
        blocks = [block.strip() for block in evidence_text.split("\n\n") if block.strip()]
        if not blocks:
            return evidence_text[:max_chars]
        selected: list[str] = []
        total = 0
        for block in blocks:
            projected = total + len(block) + (2 if selected else 0)
            if selected and projected > max_chars:
                break
            selected.append(block)
            total = projected
        return "\n\n".join(selected) if selected else evidence_text[:max_chars]
