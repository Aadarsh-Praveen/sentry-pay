"""
SentryPay — Gemini Agent Core
================================
The central reasoning engine of SentryPay. Uses Gemini 2.5 Flash with
function calling to orchestrate the three Elastic tool queries and
synthesise their results into a structured verdict.

How the agent works:
    1. Receives a payment analysis request (email text + payment details)
    2. Gemini reads the full context and decides which tools to call
    3. Tools query Elasticsearch and return structured evidence
    4. Gemini synthesises all evidence and produces a JSON verdict
    5. The verdict is logged to BigQuery and returned to the caller

Decision thresholds (enforced via system prompt):
    BLOCK    — confidence > 0.85 AND at least 2 of 3 checks suspicious
    FRICTION — confidence 0.50-0.85 OR only 1 check suspicious
    ALLOW    — confidence < 0.50 AND no checks flag anything
             — OR velocity check all clear AND typology score < 0.85

The agent is designed to be conservative:
    - It never blocks a payment based on a single suspicious signal
    - It always calls all three tools before deciding
    - It provides specific, actionable reasoning rather than vague warnings
"""

import os
import sys
import json
import time
import re
from pathlib import Path
from dotenv import load_dotenv
from colorama import Fore, Style, init
from google import genai
from google.genai import types

sys.path.insert(0, str(Path(__file__).parent.parent))
from agent.tools import (
    search_scam_typologies,
    check_beneficiary_account,
    check_payment_velocity
)
from agent.bigquery_logger import log_decision

load_dotenv()
init(autoreset=True)

GCP_PROJECT = os.getenv("GCP_PROJECT_ID")
GCP_REGION  = os.getenv("GCP_REGION", "us-central1")

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are SentryPay, an AI fraud detection agent protecting small businesses
and community bank customers from payment scams.

Your job is to analyse a payment request — including the email or message
that triggered it — and decide whether it is safe, suspicious, or fraudulent.

STEP 1 — Always call ALL THREE tools before deciding:
  1. search_scam_typologies    — find matching fraud patterns
  2. check_beneficiary_account — score the destination account
  3. check_payment_velocity    — check if this payment is unusual for this user

STEP 2 — Apply these decision rules IN ORDER:

  ALLOW — use this when ALL of the following are true:
    - velocity check shows: is_new_account=false AND is_new_vendor=false
      AND is_amount_anomalous=false (payment is within normal range)
    - AND typology similarity score is below 0.85
    - This means: known vendor, known account, normal amount = safe

  BLOCK — use this when ALL of the following are true:
    - confidence > 0.85
    - AND at least 2 of these 3 checks are suspicious:
        * typology top_score > 0.80
        * beneficiary is_flagged=true OR risk_score > 0.70
        * velocity shows is_amount_anomalous=true AND (is_new_account=true OR is_new_vendor=true)

  FRICTION — use this for everything in between:
    - Only 1 check is suspicious
    - OR confidence is 0.50-0.85
    - OR new vendor but normal amount and low typology score

STEP 3 — Respond with ONLY this JSON object (no markdown, no extra text):
{
  "verdict": "ALLOW" or "FRICTION" or "BLOCK",
  "confidence": 0.0 to 1.0,
  "typology_matched": "name of matched scam or null",
  "reasoning": "2-3 sentences referencing specific details from the email and tool results",
  "red_flags": ["specific concern 1", "specific concern 2"],
  "recommended_action": "what the user should do next",
  "sar_required": true or false
}

CRITICAL: Return the complete JSON. Do not truncate. Do not add any text before or after the JSON.
"""

# ── Tool definitions ──────────────────────────────────────────────────────────

TOOL_DEFINITIONS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="search_scam_typologies",
            description="Search fraud pattern database for matches to the email text.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "email_text":      types.Schema(type=types.Type.STRING, description="The suspicious email text"),
                    "payment_context": types.Schema(type=types.Type.STRING, description="Amount, recipient, payment type")
                },
                required=["email_text", "payment_context"]
            )
        ),
        types.FunctionDeclaration(
            name="check_beneficiary_account",
            description="Check if the destination account is flagged or high risk.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "account_number": types.Schema(type=types.Type.STRING, description="Destination account number"),
                    "recipient_name": types.Schema(type=types.Type.STRING, description="Payment recipient name")
                },
                required=["account_number", "recipient_name"]
            )
        ),
        types.FunctionDeclaration(
            name="check_payment_velocity",
            description="Compare payment against user's historical behaviour to detect anomalies.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "user_id":        types.Schema(type=types.Type.STRING,  description="User identifier"),
                    "amount":         types.Schema(type=types.Type.NUMBER,  description="Payment amount in USD"),
                    "recipient_name": types.Schema(type=types.Type.STRING,  description="Recipient name"),
                    "account_number": types.Schema(type=types.Type.STRING,  description="Destination account number"),
                    "payment_type":   types.Schema(type=types.Type.STRING,  description="ACH / Wire / RTP / Zelle / Check")
                },
                required=["user_id", "amount", "recipient_name", "account_number", "payment_type"]
            )
        )
    ]
)

TOOL_FUNCTIONS = {
    "search_scam_typologies":    search_scam_typologies,
    "check_beneficiary_account": check_beneficiary_account,
    "check_payment_velocity":    check_payment_velocity
}


# ── Agent ─────────────────────────────────────────────────────────────────────

class SentryPayAgent:
    """
    The core SentryPay agent that orchestrates Gemini function calling
    and produces fraud verdicts.
    """

    def __init__(self):
        """Initialise the Gemini client."""
        if not GCP_PROJECT:
            print(Fore.RED + "ERROR: GCP_PROJECT_ID not set in .env")
            sys.exit(1)

        self.client = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_REGION)
        self.model  = "gemini-2.5-flash"
        print(Fore.GREEN + f"  SentryPay agent ready (model: {self.model})")

    def analyse(
        self,
        email_text:     str,
        amount:         float,
        recipient_name: str,
        account_number: str,
        payment_type:   str,
        user_id:        str  = "demo_user_001",
        verbose:        bool = True
    ) -> dict:
        """
        Analyse a payment request and return a structured fraud verdict.

        Runs the Gemini function calling loop, executes all three tool
        calls, then parses the final JSON verdict and logs it to BigQuery.

        Args:
            email_text (str): the suspicious email or message text
            amount (float): payment amount in USD
            recipient_name (str): intended payment recipient
            account_number (str): destination account number
            payment_type (str): ACH / Wire / RTP / Zelle / Check
            user_id (str): identifier of the user making the request
            verbose (bool): if True, prints tool call progress

        Returns:
            dict: verdict with keys: verdict, confidence, typology_matched,
                  reasoning, red_flags, recommended_action, sar_required,
                  decision_id, processing_ms
        """
        start_time = time.time()

        user_message = f"""
Analyse this payment request for fraud risk.

EMAIL / MESSAGE:
{email_text}

PAYMENT DETAILS:
  Amount:       ${amount:,.2f}
  Recipient:    {recipient_name}
  Account:      {account_number}
  Payment type: {payment_type}
  User ID:      {user_id}

Call all three tools then return your verdict as a single JSON object.
"""
        messages       = [{"role": "user", "parts": [{"text": user_message}]}]
        final_verdict  = None
        max_iterations = 8

        if verbose:
            print(Fore.CYAN + "\n Agent analysing payment \n")

        for _ in range(max_iterations):
            response  = self.client.models.generate_content(
                model=self.model,
                contents=messages,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    tools=[TOOL_DEFINITIONS],
                    temperature=0.1,
                    max_output_tokens=8192   # large enough for complete JSON
                )
            )

            candidate = response.candidates[0]
            part      = candidate.content.parts[0]

            if hasattr(part, 'function_call') and part.function_call:
                fn_call = part.function_call
                fn_name = fn_call.name
                fn_args = dict(fn_call.args)

                if verbose:
                    print(f"  → Calling tool: {Fore.YELLOW}{fn_name}{Style.RESET_ALL}")
                    for k, v in fn_args.items():
                        val_str = str(v)[:60] + "..." if len(str(v)) > 60 else str(v)
                        print(f"    {k}: {val_str}")

                tool_result = TOOL_FUNCTIONS.get(fn_name, lambda **_: {"error": "Unknown tool"})(**fn_args)

                if verbose:
                    print(f"  ← Result: {Fore.GREEN}{json.dumps(tool_result, default=str)[:150]}...")

                messages.append({"role": "model",  "parts": [{"function_call": {"name": fn_name, "args": fn_args}}]})
                messages.append({"role": "user",   "parts": [{"function_response": {"name": fn_name, "response": tool_result}}]})

            else:
                response_text = part.text if hasattr(part, 'text') else ""
                if verbose:
                    print(Fore.CYAN + f"\n Agent verdict \n")
                    print(response_text[:800])

                final_verdict = self._parse_verdict(response_text)
                break

        # Fallback if parsing failed or loop exhausted
        if not final_verdict:
            final_verdict = {
                "verdict":            "FRICTION",
                "confidence":         0.5,
                "typology_matched":   None,
                "reasoning":          "Agent could not complete analysis — manual review required.",
                "red_flags":          ["Analysis incomplete"],
                "recommended_action": "Do not proceed without manual verification.",
                "sar_required":       False
            }

        processing_ms = int((time.time() - start_time) * 1000)

        decision_id = log_decision(
            user_id          = user_id,
            verdict          = final_verdict.get('verdict', 'FRICTION'),
            confidence       = final_verdict.get('confidence', 0.5),
            typology_matched = final_verdict.get('typology_matched'),
            reasoning        = final_verdict.get('reasoning', ''),
            red_flags        = final_verdict.get('red_flags', []),
            amount           = amount,
            recipient_name   = recipient_name,
            account_number   = account_number,
            email_text       = email_text,
            sar_required     = final_verdict.get('sar_required', False),
            processing_ms    = processing_ms
        )

        final_verdict['decision_id']   = decision_id
        final_verdict['processing_ms'] = processing_ms
        return final_verdict

    def _parse_verdict(self, response_text: str) -> dict | None:
        """
        Extract and parse the JSON verdict from Gemini's text response.

        Tries multiple extraction strategies in order:
          1. Direct JSON parse of the full response
          2. Strip markdown fences then parse
          3. Regex search for a JSON object within the text

        Returns None if all strategies fail so the caller applies
        the fallback verdict.

        Args:
            response_text (str): raw text from Gemini

        Returns:
            dict | None: parsed verdict or None on failure
        """
        if not response_text:
            return None

        # Strategy 1 — direct parse
        try:
            return json.loads(response_text.strip())
        except json.JSONDecodeError:
            pass

        # Strategy 2 — strip markdown fences
        try:
            raw = re.sub(r'^```json\s*', '', response_text.strip())
            raw = re.sub(r'^```\s*',     '', raw)
            raw = re.sub(r'\s*```$',     '', raw)
            return json.loads(raw.strip())
        except json.JSONDecodeError:
            pass

        # Strategy 3 — find JSON object anywhere in the text
        try:
            match = re.search(r'\{[^{}]*"verdict"[^{}]*\}', response_text, re.DOTALL)
            if match:
                return json.loads(match.group())
        except json.JSONDecodeError:
            pass

        return None