"""
SentryPay — Langfuse Observability (v3.1.0)
=============================================
Instruments the SentryPay agent with Langfuse cloud tracing.
Tested with Langfuse 3.1.0.

What gets recorded per analysis:
    - Full trace per request (verdict, confidence, metadata)
    - Child span per tool call (input, output, latency)
    - Generation record (prompt, response, tokens, latency)
    - User feedback scores (TRUE_POSITIVE / FALSE_POSITIVE)

Setup:
    Add to .env:
        LANGFUSE_PUBLIC_KEY=pk-lf-...
        LANGFUSE_SECRET_KEY=sk-lf-...
        LANGFUSE_BASE_URL=https://cloud.langfuse.com
"""

import os
from datetime import datetime
from dotenv import load_dotenv
from colorama import Fore, init

load_dotenv()
init(autoreset=True)

LANGFUSE_AVAILABLE = False
_langfuse          = None

# ── Langfuse client ───────────────────────────────────────────────────────────

try:
    from langfuse import Langfuse

    _langfuse = Langfuse(
        public_key = os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key = os.getenv("LANGFUSE_SECRET_KEY"),
        host       = os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")
    )
    LANGFUSE_AVAILABLE = True
    print(Fore.GREEN + "Langfuse observability ready")

except Exception as e:
    print(Fore.YELLOW + f"Langfuse not available (non-fatal): {e}")


# ── In-memory store (always available) ───────────────────────────────────────

class InMemoryTraceStore:
    """
    Lightweight in-memory trace store.
    Always available regardless of Langfuse configuration.
    Powers /traces and /stats API endpoints.
    Stores last 1,000 traces (FIFO eviction).
    """

    def __init__(self, max_size: int = 1000):
        self._traces   = []
        self._max_size = max_size

    def record(self, trace_data: dict):
        """Add a trace. Evicts oldest if at capacity."""
        trace_data['recorded_at'] = datetime.now().isoformat()
        self._traces.append(trace_data)
        if len(self._traces) > self._max_size:
            self._traces.pop(0)

    def get_recent(self, n: int = 20) -> list:
        """Return n most recent traces, newest first."""
        return list(reversed(self._traces[-n:]))

    def get_stats(self) -> dict:
        """Compute aggregate stats across all stored traces."""
        if not self._traces:
            return {"total": 0}

        verdicts    = [t.get('verdict') for t in self._traces]
        latencies   = [t.get('total_ms', 0) for t in self._traces]
        confidences = [t.get('confidence', 0) for t in self._traces]
        typologies  = [t.get('typology_matched') for t in self._traces
                       if t.get('typology_matched')]

        return {
            "total": len(self._traces),
            "verdict_counts": {
                "BLOCK":    verdicts.count('BLOCK'),
                "FRICTION": verdicts.count('FRICTION'),
                "ALLOW":    verdicts.count('ALLOW')
            },
            "avg_confidence": round(sum(confidences) / len(confidences), 3)
                              if confidences else 0,
            "avg_latency_ms": round(sum(latencies) / len(latencies))
                              if latencies else 0,
            "top_typologies": list(set(typologies))[:5]
        }


# Global in-memory store
trace_store = InMemoryTraceStore()


# ── Langfuse trace helpers ────────────────────────────────────────────────────

def start_trace(
    decision_id:    str,
    user_id:        str,
    amount:         float,
    recipient_name: str,
    payment_type:   str
):
    """
    Start a Langfuse trace for one agent analysis request.

    The decision_id is used as trace ID so BigQuery decisions
    and Langfuse traces are always correlated by the same ID.

    Args:
        decision_id (str): unique ID used as Langfuse trace ID
        user_id (str): user making the payment request
        amount (float): payment amount
        recipient_name (str): intended recipient
        payment_type (str): ACH / Wire / RTP / Zelle / Check

    Returns:
        Langfuse span object or None if unavailable
    """
    if not LANGFUSE_AVAILABLE:
        return None

    try:
        span = _langfuse.start_span(
            name     = "sentry_pay_analysis",
            input    = {
                "user_id":        user_id,
                "amount":         amount,
                "recipient_name": recipient_name,
                "payment_type":   payment_type,
                "decision_id":    decision_id
            }
        )
        return span
    except Exception as e:
        print(Fore.YELLOW + f"Langfuse trace start failed: {e}")
        return None


def record_tool_span(
    trace,
    tool_name:   str,
    tool_input:  dict,
    tool_output: dict,
    latency_ms:  int
):
    """
    Record one Elastic tool call as a child span.

    Uses start_span() + update() + end() pattern which works
    correctly in Langfuse 3.1.0.

    Args:
        trace: Langfuse span from start_trace()
        tool_name (str): tool function name
        tool_input (dict): arguments passed to the tool
        tool_output (dict): result returned by the tool
        latency_ms (int): tool execution time in milliseconds
    """
    if not trace or not LANGFUSE_AVAILABLE:
        return

    try:
        child = _langfuse.start_span(
            name  = tool_name,
            input = {**tool_input, "latency_ms": latency_ms}
        )
        child.update(output=tool_output)
        child.end()
    except Exception as e:
        print(Fore.YELLOW + f"Langfuse span failed: {e}")


def record_generation(
    trace,
    prompt:            str,
    response:          str,
    model:             str,
    prompt_tokens:     int,
    completion_tokens: int,
    latency_ms:        int
):
    """
    Record the Gemini reasoning call as a Langfuse generation.

    Uses start_span() + update() + end() pattern.
    Powers token usage charts and prompt debugging in dashboard.

    Args:
        trace: Langfuse span from start_trace()
        prompt (str): full prompt sent to Gemini
        response (str): Gemini's raw response text
        model (str): Gemini model identifier
        prompt_tokens (int): input token count
        completion_tokens (int): output token count
        latency_ms (int): Gemini call duration in milliseconds
    """
    if not trace or not LANGFUSE_AVAILABLE:
        return

    try:
        gen = _langfuse.start_span(
            name  = "gemini_reasoning",
            input = prompt[:2000]
        )
        gen.update(
            output   = response,
            metadata = {
                "model":             model,
                "prompt_tokens":     prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens":      prompt_tokens + completion_tokens,
                "latency_ms":        latency_ms
            }
        )
        gen.end()
    except Exception as e:
        print(Fore.YELLOW + f"Langfuse generation failed: {e}")


def end_trace(
    trace,
    verdict:          str,
    confidence:       float,
    typology_matched: str | None,
    total_ms:         int
):
    """
    Finalise the Langfuse trace with verdict and flush to cloud.

    Updates the root span with final outcome metadata, then
    ends it and flushes to the Langfuse API.

    Args:
        trace: Langfuse span from start_trace()
        verdict (str): ALLOW / FRICTION / BLOCK
        confidence (float): agent confidence score
        typology_matched (str | None): matched fraud pattern
        total_ms (int): total processing time in milliseconds
    """
    if not trace or not LANGFUSE_AVAILABLE:
        return

    try:
        trace.update(
            output   = verdict,
            metadata = {
                "verdict":          verdict,
                "confidence":       round(confidence, 4),
                "typology_matched": typology_matched,
                "total_ms":         total_ms
            }
        )
        trace.end()
        _langfuse.flush()
        print(Fore.GREEN + f"Langfuse trace sent: {verdict} ({confidence:.0%})")
    except Exception as e:
        print(Fore.YELLOW + f"Langfuse trace end failed: {e}")


def record_user_feedback(decision_id: str, feedback: str, comment: str = ""):
    """
    Record user feedback as a Langfuse score.

    Args:
        decision_id (str): the trace ID to score
        feedback (str): TRUE_POSITIVE or FALSE_POSITIVE
        comment (str): optional explanation
    """
    if not LANGFUSE_AVAILABLE:
        return

    try:
        _langfuse.score(
            trace_id = decision_id,
            name     = "user_feedback",
            value    = 1.0 if feedback == "TRUE_POSITIVE" else 0.0,
            comment  = comment or feedback
        )
        _langfuse.flush()
        print(Fore.GREEN + f"Langfuse feedback: {feedback}")
    except Exception as e:
        print(Fore.YELLOW + f"Langfuse feedback failed: {e}")


def record_trace(
    decision_id:      str,
    verdict:          str,
    confidence:       float,
    tool_latencies:   dict,
    total_ms:         int,
    token_count:      dict,
    typology_matched: str | None = None
):
    """
    Record to in-memory store. Always called after every decision.

    Args:
        decision_id (str): unique decision identifier
        verdict (str): ALLOW / FRICTION / BLOCK
        confidence (float): agent confidence score
        tool_latencies (dict): milliseconds per tool call
        total_ms (int): total processing time
        token_count (dict): Gemini token usage
        typology_matched (str | None): matched fraud pattern
    """
    trace_store.record({
        "decision_id":      decision_id,
        "verdict":          verdict,
        "confidence":       confidence,
        "tool_latencies":   tool_latencies,
        "total_ms":         total_ms,
        "token_count":      token_count,
        "typology_matched": typology_matched
    })