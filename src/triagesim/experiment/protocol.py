"""The structured answers agents must give, and how they are parsed.

Engine-owned: researchers edit the prompts, but not these formats, so every
experiment is parsed the same way.
"""
from __future__ import annotations

import json
import re

NURSE_TURN = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["ask", "decide"]},
        "message": {"type": "string"},
        "esi": {"type": ["integer", "null"], "minimum": 1, "maximum": 5},
    },
    "required": ["action", "message", "esi"],
}
NURSE_TURN_INSTRUCTIONS = (
    "\n\nReply ONLY with JSON in one of these two forms:\n"
    '{"action": "ask", "message": "<your next question to the patient>", "esi": null}\n'
    '{"action": "decide", "message": "<one or two sentences explaining your decision>", "esi": <1-5>}\n'
    "Ask one question at a time. Never ask a question and decide in the same reply."
)

DECISION = {
    "type": "object",
    "properties": {"esi": {"type": "integer", "minimum": 1, "maximum": 5}, "reasoning": {"type": "string"}},
    "required": ["esi", "reasoning"],
}
DECISION_INSTRUCTIONS = '\n\nReply ONLY with JSON: {"esi": <1-5>, "reasoning": "<one or two sentences>"}'

MULTIPLE_CHOICE = {
    "type": "object",
    "properties": {"answer": {"type": "string", "enum": list("ABCDE")}, "reasoning": {"type": "string"}},
    "required": ["answer", "reasoning"],
}
MULTIPLE_CHOICE_INSTRUCTIONS = '\n\nReply ONLY with JSON: {"answer": "<A-E>", "reasoning": "<one or two sentences>"}'

SELF_REVIEW = {
    "type": "object",
    "properties": {"esi": {"type": "integer", "minimum": 1, "maximum": 5}, "changed": {"type": "boolean"},
                   "reasoning": {"type": "string"}},
    "required": ["esi", "changed", "reasoning"],
}
SELF_REVIEW_INSTRUCTIONS = ('\n\nReply ONLY with JSON: {"esi": <1-5, your final level>, '
                            '"changed": <true if different from before>, "reasoning": "<one or two sentences>"}')

EVALUATION = {
    "type": "object",
    "properties": {
        "history_taking": {"type": "integer", "minimum": 0, "maximum": 10},
        "risk_identification": {"type": "integer", "minimum": 0, "maximum": 10},
        "decision": {"type": "integer", "minimum": 0, "maximum": 10},
        "feedback": {"type": "string"},
    },
    "required": ["history_taking", "risk_identification", "decision", "feedback"],
}
EVALUATION_INSTRUCTIONS = ('\n\nReply ONLY with JSON: {"history_taking": <0-10>, "risk_identification": <0-10>, '
                           '"decision": <0-10>, "feedback": "<short feedback>"}')

LETTER_TO_ESI = dict(zip("ABCDE", range(1, 6)))


class ProtocolError(ValueError):
    """A reply that does not follow the required format."""


def parse_json(text: str) -> dict:
    """Parse a JSON object, tolerating code fences or text around it."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ProtocolError("no JSON object in the reply")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ProtocolError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProtocolError("the reply is not a JSON object")
    return data


def _esi(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ProtocolError("esi must be a number from 1 to 5")
    try:
        esi = int(float(value))
    except ValueError as exc:
        raise ProtocolError("esi must be a number from 1 to 5") from exc
    if esi != float(value) or not 1 <= esi <= 5:
        raise ProtocolError("esi must be a whole number from 1 to 5")
    return esi


def parse_nurse_turn(text: str) -> dict:
    data = parse_json(text)
    action, message = data.get("action"), str(data.get("message", "")).strip()
    if action == "ask":
        if not message:
            raise ProtocolError("an 'ask' reply needs a question")
        return {"action": "ask", "message": message, "esi": None}
    if action == "decide":
        return {"action": "decide", "message": message, "esi": _esi(data.get("esi"))}
    raise ProtocolError("action must be 'ask' or 'decide'")


def parse_decision(text: str) -> dict:
    data = parse_json(text)
    return {"esi": _esi(data.get("esi")), "reasoning": str(data.get("reasoning", ""))}


def parse_multiple_choice(text: str) -> dict:
    data = parse_json(text)
    letter = str(data.get("answer", "")).strip().upper()[:1]
    if letter not in LETTER_TO_ESI:
        raise ProtocolError("answer must be one of A-E")
    return {"esi": LETTER_TO_ESI[letter], "answer": letter, "reasoning": str(data.get("reasoning", ""))}


def parse_self_review(text: str) -> dict:
    data = parse_json(text)
    return {"esi": _esi(data.get("esi")), "reasoning": str(data.get("reasoning", ""))}


def parse_evaluation(text: str) -> dict:
    data = parse_json(text)
    scores = {}
    for key in ("history_taking", "risk_identification", "decision"):
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 10:
            raise ProtocolError(f"{key} must be a score from 0 to 10")
        scores[key] = int(value)
    return {"scores": scores, "feedback": str(data.get("feedback", ""))}
