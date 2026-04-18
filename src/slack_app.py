from __future__ import annotations

import logging
import re
import threading
from threading import Event

from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web import WebClient

from config import settings
from src.agent import BuildAgents, format_slack_response
from src.perf_tools import K6Workspace

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
LOGGER = logging.getLogger(__name__)

agent = BuildAgents()
k6_workspace = K6Workspace()


def _build_web_client() -> WebClient | None:
    """Create the Slack Web API client when the bot token is configured."""
    if not settings.slack_bot_token:
        return None
    return WebClient(token=settings.slack_bot_token)


def _normalize_question(text: str) -> str:
    """Strip bot mentions and surrounding whitespace from incoming Slack text."""
    return re.sub(r"<@[^>]+>", "", text or "").strip()


def _is_supported_event(event: dict) -> bool:
    """Accept only user-authored app mentions and direct messages."""
    return event.get("type") in {"app_mention", "message"} and not event.get("bot_id")


def _is_allowed_channel(event: dict) -> bool:
    """Optionally restrict the bot to a single configured channel."""
    return not settings.slack_allowed_channel or event.get("channel") == settings.slack_allowed_channel


def _post_placeholder_message(event: dict, client: WebClient) -> str | None:
    """Post an immediate placeholder so Slack shows visible activity in the chat."""
    try:
        response = client.chat_postMessage(
            channel=event["channel"],
            text="Processing...",
        )
        placeholder_ts = response.get("ts")
        LOGGER.info(
            "Posted placeholder message to channel=%s ts=%s",
            event.get("channel"),
            placeholder_ts,
        )
        return placeholder_ts
    except Exception as exc:  # pragma: no cover - network-bound fallback
        LOGGER.exception("Failed to post placeholder message: %s", exc)
        return None


def _conversation_id_for_event(event: dict) -> str:
    """Prefer Slack thread continuity; otherwise scope memory to the channel."""
    channel = event.get("channel", "unknown")
    thread_ts = event.get("thread_ts")
    if thread_ts:
        return f"{channel}:thread:{thread_ts}"
    return f"{channel}:channel"


def _process_event_async(
    event: dict,
    question: str,
    client: WebClient,
    placeholder_ts: str | None,
) -> None:
    """Run retrieval and answer generation outside the socket event callback."""
    try:
        LOGGER.info("Running agent for question: %r", question[:200])
        conversation_id = _conversation_id_for_event(event)
        result = agent.answer(question, conversation_id=conversation_id)
        reply_text = format_slack_response(result)
        LOGGER.info("Agent finished with %s citations.", len(result.citations))

        if placeholder_ts:
            client.chat_update(
                channel=event["channel"],
                ts=placeholder_ts,
                text=reply_text,
            )
            LOGGER.info(
                "Updated placeholder successfully. channel=%s ts=%s",
                event.get("channel"),
                placeholder_ts,
            )
        else:
            client.chat_postMessage(channel=event["channel"], text=reply_text)
            LOGGER.info("Posted final reply without placeholder.")
    except Exception as exc:  # pragma: no cover - network-bound fallback
        LOGGER.exception("Failed to process Slack event asynchronously: %s", exc)


def handle_slack_event(event: dict, client: WebClient) -> None:
    """Validate a Slack event payload and hand work to a background thread."""
    LOGGER.info(
        "Slack event type=%s channel=%s user=%s text=%r",
        event.get("type"),
        event.get("channel"),
        event.get("user"),
        (event.get("text") or "")[:200],
    )

    if not _is_supported_event(event):
        LOGGER.info("Ignoring unsupported or bot-originated event.")
        return
    if not _is_allowed_channel(event):
        LOGGER.info(
            "Ignoring channel=%s because SLACK_ALLOWED_CHANNEL=%s",
            event.get("channel"),
            settings.slack_allowed_channel,
        )
        return

    question = _normalize_question(event.get("text", ""))
    if not question:
        LOGGER.info("Ignoring empty question after mention cleanup.")
        return

    placeholder_ts = _post_placeholder_message(event, client)
    worker = threading.Thread(
        target=_process_event_async,
        args=(event, question, client, placeholder_ts),
        daemon=True,
    )
    worker.start()
    LOGGER.info("Accepted Slack event and started background worker %s.", worker.name)


def process_socket_mode_request(client: SocketModeClient, request: SocketModeRequest) -> None:
    """Acknowledge the socket envelope immediately, then process the Slack event."""
    if request.type != "events_api":
        return

    client.send_socket_mode_response(SocketModeResponse(envelope_id=request.envelope_id))
    payload = request.payload or {}
    event = payload.get("event", {})
    handle_slack_event(event, client.web_client)


def start_socket_mode() -> None:
    """Start the bot in Slack Socket Mode."""
    if not settings.slack_bot_token:
        raise RuntimeError("SLACK_BOT_TOKEN is required for Socket Mode.")
    if not settings.slack_app_token:
        raise RuntimeError("SLACK_APP_TOKEN is required for Socket Mode.")

    web_client = _build_web_client()
    if web_client is None:
        raise RuntimeError("Failed to create Slack WebClient.")

    socket_client = SocketModeClient(
        app_token=settings.slack_app_token,
        web_client=web_client,
    )
    socket_client.socket_mode_request_listeners.append(process_socket_mode_request)

    LOGGER.info(
        "Starting Slack Socket Mode client. bot_token_set=%s app_token_set=%s allowed_channel=%r k6_configured=%s k6_project_root=%s",
        bool(settings.slack_bot_token),
        bool(settings.slack_app_token),
        settings.slack_allowed_channel,
        k6_workspace.configured,
        k6_workspace.project_root,
    )
    socket_client.connect()
    Event().wait()


if __name__ == "__main__":
    start_socket_mode()
