from __future__ import annotations

import argparse
import sys
import uuid

from src.agent import BuildAgents, format_slack_response


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for one-shot and interactive local testing."""
    parser = argparse.ArgumentParser(
        description="Query the RAG bot once or open an interactive local chat session."
    )
    parser.add_argument("question", nargs="*", help="One-shot question to ask the agent.")
    parser.add_argument(
        "--repl",
        action="store_true",
        help="Start an interactive chat session in the terminal.",
    )
    parser.add_argument(
        "--conversation-id",
        default="",
        help="Reuse a stable memory key across turns or runs.",
    )
    return parser


def _run_repl(agent: BuildAgents, conversation_id: str) -> int:
    """Run a simple terminal chat loop that keeps Redis-backed memory alive."""
    _safe_print(f"Starting local chat. Conversation ID: {conversation_id}")
    _safe_print(f"Memory backend: {agent.memory.backend_label}")
    _safe_print("Type 'exit' or 'quit' to leave.\n")

    while True:
        try:
            question = input("You: ").strip()
        except EOFError:
            _safe_print()
            return 0
        except KeyboardInterrupt:
            _safe_print("\nExiting chat.")
            return 0

        if not question:
            continue
        if question.lower() in {"exit", "quit"}:
            _safe_print("Exiting chat.")
            return 0

        result = agent.answer(question, conversation_id=conversation_id)
        _safe_print(f"\nBot:\n{format_slack_response(result)}\n")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point used for quick local testing without Slack."""
    _configure_stdout()
    parser = _build_parser()
    args = parser.parse_args(argv)
    question = " ".join(args.question).strip()
    conversation_id = args.conversation_id or f"cli-{uuid.uuid4().hex}"
    agent = BuildAgents()

    if args.repl:
        return _run_repl(agent, conversation_id)
    if not question:
        parser.print_usage()
        return 1

    result = agent.answer(question, conversation_id=conversation_id)
    _safe_print(format_slack_response(result))
    return 0


def _safe_print(text: str = "") -> None:
    """Print text safely on Windows terminals with narrow legacy encodings."""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        sanitized = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(sanitized)


def _configure_stdout() -> None:
    """Prefer UTF-8 console output when the runtime supports reconfiguration."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            return


if __name__ == "__main__":
    raise SystemExit(main())
