from __future__ import annotations

import argparse
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
    print(f"Starting local chat. Conversation ID: {conversation_id}")
    print(f"Memory backend: {agent.memory.backend_label}")
    print("Type 'exit' or 'quit' to leave.\n")

    while True:
        try:
            question = input("You: ").strip()
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print("\nExiting chat.")
            return 0

        if not question:
            continue
        if question.lower() in {"exit", "quit"}:
            print("Exiting chat.")
            return 0

        result = agent.answer(question, conversation_id=conversation_id)
        print(f"\nBot:\n{format_slack_response(result)}\n")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point used for quick local testing without Slack."""
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
    print(format_slack_response(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
