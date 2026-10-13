"""Run one case through an experiment as a LangGraph graph.

Interview:   open -> patient -> nurse -(ask)-> patient ...
                                     -(decide)-> evaluate -> end
                                     -(question limit)-> force -> evaluate -> end
Chart review / multiple choice:  read_chart -> evaluate -> end

Every message is passed to ``emit`` as it happens, so a run can be watched live.
"""
from __future__ import annotations

import time
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from ..llm.base import ChatModel, Message
from . import protocol as P
from .agents import (LLMPatient, RetrievalPatient, Usage, ask_structured, choose_persona,
                     system_message)
from .config import ExperimentConfig
from .fields import case_values

Emit = Callable[[dict], None]


class Stopped(Exception):
    """The run was asked to stop."""


class CaseState(TypedDict, total=False):
    transcript: list[dict]
    questions: int
    nurse_history: list[Message]
    pending: dict | None        # the nurse's last parsed reply
    decision: dict | None       # the nurse's decision: esi, reasoning, forced
    evaluation: dict | None


def run_case(case: dict, config: ExperimentConfig, models: dict[str, ChatModel], *,
             emit: Emit = lambda e: None, should_stop: Callable[[], bool] = lambda: False,
             embed=None) -> dict:
    """Run one case and return its result record."""
    started = time.time()
    usage = {"nurse": Usage(), "patient": Usage(), "evaluator": Usage()}
    persona_name = choose_persona(config.patient, case["case_id"], config.sampling.seed) if config.patient else None
    persona_text = config.patient.personas.get(persona_name, "") if config.patient else ""
    values = case_values(case, persona=persona_text)
    nurse_cfg = config.nurse
    nurse_model = models[nurse_cfg.model.name]

    def say(state: CaseState, speaker: str, text: str, **extra) -> list[dict]:
        if should_stop():
            raise Stopped()
        entry = {"speaker": speaker, "text": text, "turn": state.get("questions", 0), **extra}
        emit({"type": "message", "case_id": case["case_id"], **entry})
        return state.get("transcript", []) + [entry]

    # ---- interview nodes -----------------------------------------------------------
    patient = None
    if nurse_cfg.mode == "interview":
        if config.patient.mode == "retrieval":
            if embed is None:
                raise ValueError("A retrieval patient needs an embedding function.")
            patient = RetrievalPatient(config.patient, models[config.patient.model.name], values,
                                       usage["patient"], embed)
        else:
            patient = LLMPatient(config.patient, models[config.patient.model.name], values, usage["patient"])

    def open_(state: CaseState) -> CaseState:
        opening = nurse_cfg.opening_message
        history = [system_message(nurse_cfg, values, P.NURSE_TURN_INSTRUCTIONS),
                   Message("assistant", '{"action": "ask", "message": "%s", "esi": null}' % opening.replace('"', "'"))]
        return {"transcript": say(state, "nurse", opening), "questions": 1, "nurse_history": history,
                "pending": {"action": "ask", "message": opening}}

    def patient_(state: CaseState) -> CaseState:
        answer = patient.reply(state["pending"]["message"])
        extra = {"retrieved": list(patient.last_retrieved)} if isinstance(patient, RetrievalPatient) else {}
        return {"transcript": say(state, "patient", answer, **extra),
                "nurse_history": state["nurse_history"] + [Message("user", answer)]}

    def nurse_(state: CaseState) -> CaseState:
        parsed, raw = ask_structured(nurse_model, nurse_cfg.model, state["nurse_history"], P.NURSE_TURN,
                                     P.parse_nurse_turn, usage["nurse"])
        history = state["nurse_history"] + [Message("assistant", raw)]
        if parsed is None:
            return {"nurse_history": history, "pending": {"action": "invalid"},
                    "transcript": say(state, "system", "The nurse's reply was not in the required format twice.")}
        if parsed["action"] == "decide":
            decision = {"esi": parsed["esi"], "reasoning": parsed["message"], "forced": False}
            emit({"type": "decision", "case_id": case["case_id"], **decision})
            return {"nurse_history": history, "pending": parsed, "decision": decision,
                    "transcript": say(state, "nurse", parsed["message"], decision=parsed["esi"])}
        questions = state["questions"] + 1
        if questions > nurse_cfg.max_turns:
            return {"nurse_history": history, "pending": {"action": "limit"}}
        return {"nurse_history": history, "pending": parsed, "questions": questions,
                "transcript": say({**state, "questions": questions}, "nurse", parsed["message"])}

    def route_after_nurse(state: CaseState) -> str:
        action = state["pending"]["action"]
        return {"ask": "patient", "decide": "evaluate"}.get(action, "force")

    def force_(state: CaseState) -> CaseState:
        note = (f"You have reached the limit of {nurse_cfg.max_turns} questions. Decide now "
                "based on what you know.")
        transcript = say(state, "system", note)
        messages = [system_message(nurse_cfg, values, "")] + state["nurse_history"][1:] + \
                   [Message("user", note + P.DECISION_INSTRUCTIONS)]
        parsed, _ = ask_structured(nurse_model, nurse_cfg.model, messages, P.DECISION, P.parse_decision,
                                   usage["nurse"])
        if parsed is None:
            return {"transcript": transcript, "decision": None}
        decision = {"esi": parsed["esi"], "reasoning": parsed["reasoning"], "forced": True}
        emit({"type": "decision", "case_id": case["case_id"], **decision})
        return {"transcript": say({**state, "transcript": transcript}, "nurse", parsed["reasoning"],
                                  decision=parsed["esi"]), "decision": decision}

    # ---- chart review / multiple choice ------------------------------------------------
    def read_chart(state: CaseState) -> CaseState:
        mcq = nurse_cfg.mode == "multiple_choice"
        system = system_message(nurse_cfg, values, P.MULTIPLE_CHOICE_INSTRUCTIONS if mcq else P.DECISION_INSTRUCTIONS)
        ask = Message("user", "Give your answer." if mcq else "Assign the ESI level.")
        parsed, raw = ask_structured(nurse_model, nurse_cfg.model, [system, ask],
                                     P.MULTIPLE_CHOICE if mcq else P.DECISION,
                                     P.parse_multiple_choice if mcq else P.parse_decision, usage["nurse"])
        history = [system, ask, Message("assistant", raw)]
        if parsed is None:
            return {"nurse_history": history, "decision": None,
                    "transcript": say(state, "system", "The nurse's reply was not in the required format twice.")}
        decision = {"esi": parsed["esi"], "reasoning": parsed["reasoning"], "forced": False}
        emit({"type": "decision", "case_id": case["case_id"], **decision})
        return {"nurse_history": history, "decision": decision,
                "transcript": say(state, "nurse", parsed["reasoning"], decision=parsed["esi"])}

    # ---- shared tail ----------------------------------------------------------------------
    def evaluate(state: CaseState) -> CaseState:
        ev = config.evaluator
        if not ev or not ev.enabled:
            return {"evaluation": None}
        final = state.get("decision")
        transcript = "\n".join(f"{m['speaker'].capitalize()}: {m['text']}" for m in state.get("transcript", [])
                               if m["speaker"] != "system")
        ev_values = {**values, "transcript": transcript, "decision": str(final["esi"]) if final else "none"}
        messages = [system_message(ev, ev_values, P.EVALUATION_INSTRUCTIONS), Message("user", "Evaluate the nurse.")]
        parsed, _ = ask_structured(models[ev.model.name], ev.model, messages, P.EVALUATION, P.parse_evaluation,
                                   usage["evaluator"])
        if should_stop():
            raise Stopped()
        emit({"type": "evaluation", "case_id": case["case_id"], "evaluation": parsed})
        return {"evaluation": parsed}

    graph = StateGraph(CaseState)
    if nurse_cfg.mode == "interview":
        graph.add_node("open", open_)
        graph.add_node("patient", patient_)
        graph.add_node("nurse", nurse_)
        graph.add_node("force", force_)
        graph.add_edge(START, "open")
        graph.add_edge("open", "patient")
        graph.add_edge("patient", "nurse")
        graph.add_conditional_edges("nurse", route_after_nurse, ["patient", "evaluate", "force"])
        graph.add_edge("force", "evaluate")
    else:
        graph.add_node("read_chart", read_chart)
        graph.add_edge(START, "read_chart")
        graph.add_edge("read_chart", "evaluate")
    graph.add_node("evaluate", evaluate)
    graph.add_edge("evaluate", END)

    emit({"type": "case_start", "case_id": case["case_id"], "persona": persona_name})
    state = graph.compile().invoke({"transcript": [], "questions": 0},
                                   {"recursion_limit": 4 * nurse_cfg.max_turns + 20})
    decision = state.get("decision")
    result: dict[str, Any] = {
        "case_id": case["case_id"], "stay_id": case["stay_id"], "experiment": config.name,
        "mode": nurse_cfg.mode, "persona": persona_name,
        "reference_esi": case["reference"]["esi"], "head_injury": case["reference"].get("head_injury_icd"),
        "disposition": case["reference"].get("disposition"),
        "esi": decision["esi"] if decision else None,
        "decided": decision is not None, "forced": bool(decision and decision["forced"]),
        "questions": state.get("questions", 0) if nurse_cfg.mode == "interview" else 0,
        "evaluation": state.get("evaluation"),
        "format_retries": sum(u.format_retries for u in usage.values()),
        "format_failures": sum(u.format_failures for u in usage.values()),
        "tokens": sum(u.prompt_tokens + u.completion_tokens for u in usage.values()),
        "model_calls": sum(u.calls for u in usage.values()),
        "seconds": round(time.time() - started, 2),
        "transcript": state.get("transcript", []),
    }
    emit({"type": "case_done", "case_id": case["case_id"],
          **{k: result[k] for k in ("esi", "reference_esi", "decided", "questions")}})
    return result
