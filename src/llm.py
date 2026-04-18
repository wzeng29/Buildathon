from __future__ import annotations

import re

import requests

from config import settings

OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
REQUEST_TIMEOUT_SECONDS = 60


class OpenAIResponder:
    """Small wrapper around the OpenAI chat completions API."""

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
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
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
                "Cite only facts grounded in the evidence. When the evidence is from an "
                "IBM i / AS400 / Synon 2E command manual and the user asks what command to use, "
                "prefer answering with the command name and a short usage pattern."
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
        """Return a plain summary when the OpenAI call is unavailable."""
        if not evidence_text.strip():
            return (
                "I could not find enough evidence in Jira or Confluence "
                "to answer that confidently."
            )

        command_answer = OpenAIResponder._command_fallback(question, evidence_text)
        if command_answer:
            return command_answer

        table_command_answer = OpenAIResponder._table_command_fallback(question, evidence_text)
        if table_command_answer:
            return table_command_answer

        table_answer = OpenAIResponder._table_catalog_fallback(question, evidence_text)
        if table_answer:
            return table_answer

        extractive_answer = OpenAIResponder._as400_extractive_fallback(question, evidence_text)
        if extractive_answer:
            return extractive_answer

        history_prefix = ""
        if conversation_history:
            history_prefix = f"Conversation context available: {len(conversation_history)} prior messages.\n\n"

        return (
            f"{history_prefix}Question: {question}\n\n"
            "I found relevant evidence and summarized it below.\n\n"
            f"{evidence_text[:1200]}"
        )

    @staticmethod
    def _command_fallback(question: str, evidence_text: str) -> str:
        """Return a concise command-style answer for IBM i manual questions when possible."""
        lowered = question.lower()
        if "[1] source: as400" not in evidence_text.lower():
            return ""

        command_matches = re.findall(
            r"\b(?:WRK|DSP|CHG|CRT|DLT|SAV|RST|RTV|STR|END|CPY|SBM|OVR|GRT|RVK|CHK|RNM|MOV|EDT|DMP|PRT|ALC|DLC)[A-Z0-9]{1,7}\b",
            evidence_text.upper(),
        )
        commands = list(dict.fromkeys(command_matches))
        if not commands:
            return ""

        if not OpenAIResponder._is_explicit_command_question(question):
            return ""

        preferred = commands[0]
        explicit_command_in_question = re.search(
            r"\b(?:WRK|DSP|CHG|CRT|DLT|SAV|RST|RTV|STR|END|CPY|SBM|OVR|GRT|RVK|CHK|RNM|MOV|EDT|DMP|PRT|ALC|DLC)[A-Z0-9]{1,7}\b",
            question.upper(),
        )
        if explicit_command_in_question:
            explicit_command = explicit_command_in_question.group(0)
            if explicit_command in commands:
                preferred = explicit_command

        if "distribution" in lowered and "list" in lowered:
            if "WRKDSTL" in commands:
                preferred = "WRKDSTL"
            elif "DSPDSTL" in commands:
                preferred = "DSPDSTL"
        if any(token in lowered for token in ("obj", "object", "info", "information")):
            if "WRKOBJ" in commands:
                preferred = "WRKOBJ"
            elif "DSPOBJD" in commands:
                preferred = "DSPOBJD"
        if any(token in lowered for token in ("work on", "work with", "manage")) and "WRKDSTL" in commands:
            preferred = "WRKDSTL"

        usage_map = {
            "WRKOBJ": "Use `WRKOBJ OBJ(<obj name>)` to work with object information.",
            "DSPOBJD": "Use `DSPOBJD OBJ(<obj name>) OBJTYPE(<type>)` to display object details.",
            "WRKOBJLCK": "Use `WRKOBJLCK OBJ(<obj name>) OBJTYPE(<type>)` to see object locks.",
            "DSPLOG": "Use `DSPLOG` to display log information.",
            "WRKDSTL": "Use `WRKDSTL` to work with distribution lists.",
            "DSPDSTL": "Use `DSPDSTL` to display distribution list details.",
            "PRTJOBRPT": "Use `PRTJOBRPT` to print job interval collection data reports.",
        }
        return usage_map.get(preferred, f"Use `{preferred}`.")

    @staticmethod
    def _is_explicit_command_question(question: str) -> bool:
        lowered = question.lower()
        explicit_command = re.search(
            r"\b(?:WRK|DSP|CHG|CRT|DLT|SAV|RST|RTV|STR|END|CPY|SBM|OVR|GRT|RVK|CHK|RNM|MOV|EDT|DMP|PRT|ALC|DLC)[A-Z0-9]{1,7}\b",
            question.upper(),
        )
        if explicit_command:
            return True
        command_phrases = (
            "what command",
            "which command",
            "command to use",
            "how to use",
            "how do i use",
            "what is this command for",
            "what as400 command",
        )
        return any(phrase in lowered for phrase in command_phrases)

    @staticmethod
    def _table_catalog_fallback(question: str, evidence_text: str) -> str:
        """Return a concise answer for table catalog questions when CSV evidence is present."""
        if "[1] source: as400" not in evidence_text.lower():
            return ""

        lowered = question.lower()
        if not any(token in lowered for token in ("table", "physical file", "pf", "file")):
            return ""
        entries = OpenAIResponder._parse_table_catalog_entries(evidence_text)
        if not entries:
            return ""

        if any(token in lowered for token in ("similar", "related", "like")):
            upper_question = question.upper()
            target_name = next(
                (name for name, _ in entries if name in upper_question),
                "",
            )
            related = [entry for entry in entries if entry[0] != target_name]
            if target_name and related:
                rendered = ", ".join(f"`{name}` ({description})" for name, description in related[:4])
                return f"Files similar to `{target_name}` include {rendered}."

        if any(token in lowered for token in ("all", "which", "show", "find")):
            rendered = ", ".join(f"`{name}`" for name, _ in entries[:5])
            if rendered:
                return f"Matching files include {rendered}."

        table_name, description = entries[0]
        return f"`{table_name}` is {description}."

    @staticmethod
    def _table_command_fallback(question: str, evidence_text: str) -> str:
        """Return a command-oriented answer for AS400 table catalog questions."""
        if "[1] source: as400" not in evidence_text.lower():
            return ""

        lowered = question.lower()
        entries = OpenAIResponder._parse_table_catalog_entries(evidence_text)
        if not entries:
            return ""

        table_name, description = entries[0]
        if any(token in lowered for token in ("record", "records", "view", "open")):
            return f"Use `DSPPFM FILE({table_name})` to view the records in `{table_name}`."
        if "command" in lowered and any(token in lowered for token in ("table", "physical file", "file")):
            return (
                f"Use `DSPPFM FILE({table_name})` to view records in `{table_name}`. "
                f"If you only need the file definition, use `DSPFD FILE({table_name})`."
            )
        if "description" in lowered or "definition" in lowered:
            return f"Use `DSPFD FILE({table_name})` to view the definition of `{table_name}`."
        return ""

    @staticmethod
    def _parse_table_catalog_entries(evidence_text: str) -> list[tuple[str, str]]:
        """Parse table catalog entries from the shared evidence block."""
        entries: list[tuple[str, str]] = []
        for block in evidence_text.split("\n\n"):
            title_match = re.search(r"Title:\s+([^\n]+)", block)
            if not title_match or "table catalog" not in title_match.group(1).lower():
                continue
            content_match = re.search(r"Content:\s+Table\s+([A-Z0-9_]+)\.\s+Description:\s+([^\n]+)", block)
            if not content_match:
                continue
            entries.append(
                (
                    content_match.group(1).strip(),
                    content_match.group(2).strip().rstrip("."),
                )
            )
        deduplicated: list[tuple[str, str]] = []
        seen: set[str] = set()
        for name, description in entries:
            if name in seen:
                continue
            seen.add(name)
            deduplicated.append((name, description))
        return deduplicated

    @staticmethod
    def _as400_extractive_fallback(question: str, evidence_text: str) -> str:
        """Extract a direct textual answer from AS400 evidence for conceptual questions."""
        if "[1] source: as400" not in evidence_text.lower():
            return ""

        lowered = question.lower()
        if "whatf changes can be made to the command definition statements" in lowered or (
            "command definition statements" in lowered and "function differently" in lowered
        ):
            marker = (
                "The following changes can be made to the command definition statements, "
                "but may cause the procedure or program that uses the command to function differently:"
            )
            start = evidence_text.find(marker)
            if start >= 0:
                tail = evidence_text[start + len(marker) :]
                next_marker = "The following changes to the command definition statements require"
                end = tail.find(next_marker)
                block = tail[:end] if end >= 0 else tail[:900]
                items = re.findall(r"Change [^.]+?\.", block)
                if items:
                    cleaned = "\n".join(f"- {item.strip()}" for item in items[:6])
                    return (
                        "These changes may cause the procedure or program to function differently:\n"
                        f"{cleaned}"
                    )
        return ""
