"""A stand-in for the Claude client, so tests never touch the network."""

import json
from types import SimpleNamespace

import anthropic
import httpx2

GOOD_DRAFT = {
    "status": "Model Atlas v2.1 is not ready: 1 blocker. Target date 2026-11-14. "
              "Latest decision: No-go on 2026-10-30 by Morgan T.",
    "blockers_and_risks": ["Tool-use safety eval (Safety, Dana K.) failed and is overdue."],
    "decisions": ["No-go on 2026-10-30 by Morgan T. (VP, Product): tool-use safety eval failed."],
    "next_steps": ["Re-run the eval after the fix; revisit at next week's review."],
}


def response(data=None, stop_reason="end_turn", text=None, model="claude-opus-5-5"):
    body = text if text is not None else json.dumps(GOOD_DRAFT if data is None else data)
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=body)],
        model=model,
        _request_id="req_test",
    )


class FakeMessages:
    def __init__(self, result=None, error=None):
        self.result = result if result is not None else response()
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


class FakeClient:
    """Has only .messages. No .beta, so any beta call (e.g. fallbacks) would fail loudly."""

    def __init__(self, result=None, error=None):
        self.messages = FakeMessages(result, error)


_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def status_error(cls, code):
    return cls(f"error {code}", response=httpx2.Response(code, request=_REQUEST), body=None)


def api_errors():
    """(error, expected message, expected status code) for each failure the app handles."""
    return [
        (status_error(anthropic.AuthenticationError, 401),
         "The API key was rejected. Check ANTHROPIC_API_KEY.", 503),
        (status_error(anthropic.PermissionDeniedError, 403),
         "The API key isn't allowed to use this model. Check ANTHROPIC_API_KEY.", 503),
        (status_error(anthropic.RateLimitError, 429),
         "Too many requests right now. Try again in a minute.", 503),
        (status_error(anthropic.InternalServerError, 500), "Couldn't reach Claude. Try again.", 502),
        (anthropic.APIConnectionError(request=_REQUEST), "Couldn't reach Claude. Try again.", 503),
        (anthropic.APITimeoutError(request=_REQUEST), "Couldn't reach Claude. Try again.", 503),
    ]
