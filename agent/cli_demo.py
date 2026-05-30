"""
SentryPay — CLI Demo
======================
Tests the SentryPay agent against three carefully crafted demo
scenarios that demonstrate all three possible verdicts:

  Scenario 1 — Supplier Fraud (BLOCK)
      A realistic Business Email Compromise email claiming a supplier
      has changed their bank account. The payment amount is far above
      Sarah Chen's normal range, the account is unknown, and the email
      matches the BEC typology closely. Expected: BLOCK.

  Scenario 2 — Borderline Invoice (FRICTION)
      A slightly unusual invoice from an unfamiliar contact requesting
      a moderately large payment. Only one or two signals are suspicious.
      Expected: FRICTION.

  Scenario 3 — Legitimate Payment (ALLOW)
      A routine monthly invoice from a known vendor for a typical amount.
      The account is known, the amount is within the user's normal range,
      and the email text does not match any fraud patterns.
      Expected: ALLOW.

Running all three scenarios in the demo video shows judges that
SentryPay does not simply block everything — it makes nuanced,
evidence-based decisions across the full spectrum.

Usage:
    python agent/cli_demo.py              # run all 3 scenarios
    python agent/cli_demo.py --scenario 1 # run one specific scenario
"""

import sys
import json
import argparse
from pathlib import Path
from colorama import Fore, Style, init

sys.path.insert(0, str(Path(__file__).parent.parent))
from agent.gemini_agent import SentryPayAgent

init(autoreset=True)


# ── Demo scenarios ────────────────────────────────────────────────────────────

SCENARIOS = [
    {
        "id":          1,
        "name":        "Supplier Banking Details Update (BEC)",
        "expected":    "BLOCK",
        "user_id":     "demo_user_001",
        "email": """
Hi Sarah,

Hope you're well. Just a quick note — we've recently switched our
business banking over to Metro Business Bank following our acquisition
by Hartwell Group. As a result, all future payments should be directed
to our new account with immediate effect.

New banking details:
  Account name:   Apex Scaffolding Ltd
  Account number: GB94METRO00000087654321
  Sort code:      60-15-42

Could you please update your records and ensure the next invoice
(Invoice #4821, £47,000 due this Friday) goes to the new account?
We've already notified our other clients — just need to confirm
you've received this update.

Many thanks,
Michael Harrington
Accounts Director — Apex Scaffolding Ltd
""",
        "amount":         47000,
        "recipient_name": "Apex Scaffolding Ltd",
        "account_number": "GB94METRO00000087654321",
        "payment_type":   "Wire"
    },
    {
        "id":          2,
        "name":        "Borderline Unfamiliar Invoice (FRICTION)",
        "expected":    "FRICTION",
        "user_id":     "demo_user_001",
        "email": """
Hi,

Please find attached invoice #INV-2094 for consulting services
provided during April — $9,500 net 30.

Payment details:
  Payable to:     BuildRight Advisory Services
  Account:        US44FIRST00000112233445
  Routing:        021000089

Let me know if you need anything else.

Thanks,
Derek Walsh
BuildRight Advisory Services
""",
        "amount":         9500,
        "recipient_name": "BuildRight Advisory Services",
        "account_number": "US44FIRST00000112233445",
        "payment_type":   "ACH"
    },
    {
        "id":          3,
        "name":        "Routine Monthly Invoice (ALLOW)",
        "expected":    "ALLOW",
        "user_id":     "demo_user_001",
        "email": """
Hi Sarah,

Please see attached Invoice #7042 for office supplies delivered
on 12th May — $847.50 as agreed on our standard monthly account.

No changes to our payment details. Same account as always.
  City Office Supplies Ltd
  Account: GB82WEST12345698765432
  Sort:    60-16-13

Thanks as always,
Jenny
City Office Supplies
""",
        "amount":         847.50,
        "recipient_name": "City Office Supplies",
        "account_number": "GB82WEST12345698765432",
        "payment_type":   "ACH"
    }
]


# ── Verdict display ───────────────────────────────────────────────────────────

VERDICT_COLOURS = {
    "BLOCK":    Fore.RED,
    "FRICTION": Fore.YELLOW,
    "ALLOW":    Fore.GREEN
}

VERDICT_ICONS = {
    "BLOCK":    "🔴",
    "FRICTION": "🟡",
    "ALLOW":    "🟢"
}


def print_verdict(scenario: dict, result: dict):
    """
    Print a formatted verdict summary for one scenario.

    Displays the verdict prominently alongside the key evidence signals
    that led to the decision: typology match, confidence, red flags,
    and the agent's plain English reasoning.

    Args:
        scenario (dict): the scenario definition including expected verdict
        result (dict): the agent's structured verdict
    """
    verdict     = result.get('verdict', 'UNKNOWN')
    colour      = VERDICT_COLOURS.get(verdict, Fore.WHITE)
    icon        = VERDICT_ICONS.get(verdict, '⚪')
    expected    = scenario['expected']
    correct     = "✓ CORRECT" if verdict == expected else f"✗ EXPECTED {expected}"
    correct_col = Fore.GREEN if verdict == expected else Fore.RED

    print(Fore.CYAN + "\n" + "─" * 60)
    print(f"  Scenario {scenario['id']}: {scenario['name']}")
    print("─" * 60 + Style.RESET_ALL)

    print(f"\n  {icon}  {colour}VERDICT: {verdict}{Style.RESET_ALL}   "
          f"{correct_col}{correct}{Style.RESET_ALL}")

    print(f"\n  Confidence:    {result.get('confidence', 0):.0%}")
    print(f"  Typology:      {result.get('typology_matched') or 'None'}")
    print(f"  SAR required:  {result.get('sar_required', False)}")
    print(f"  Processing:    {result.get('processing_ms', 0):,}ms")
    print(f"  Decision ID:   {result.get('decision_id', 'N/A')[:8]}...")

    if result.get('red_flags'):
        print(f"\n  Red flags:")
        for flag in result['red_flags']:
            print(f"    • {flag}")

    if result.get('reasoning'):
        print(f"\n  Reasoning:")
        # Word-wrap at 55 characters
        words, line = result['reasoning'].split(), ""
        for word in words:
            if len(line) + len(word) + 1 > 55:
                print(f"    {line}")
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            print(f"    {line}")

    if result.get('recommended_action'):
        print(f"\n  Action:  {result['recommended_action']}")

    print()


# ── Main ─────────────────────────────────────────────────────────────────────

def run(scenario_id: int | None = None):
    """
    Run one or all demo scenarios through the SentryPay agent.

    Args:
        scenario_id (int | None): if provided, run only this scenario
                                   (1, 2, or 3). If None, run all three.
    """
    print(Fore.CYAN + "SentryPay — CLI Demo")

    agent     = SentryPayAgent()
    scenarios = SCENARIOS if scenario_id is None else [
        s for s in SCENARIOS if s['id'] == scenario_id
    ]

    if not scenarios:
        print(Fore.RED + f"  Scenario {scenario_id} not found. Choose 1, 2, or 3.")
        sys.exit(1)

    results   = []
    correct   = 0

    for scenario in scenarios:
        print(Fore.CYAN + f"\n  Running scenario {scenario['id']}: {scenario['name']}")
        print(f"  Expected verdict: {scenario['expected']}\n")

        result = agent.analyse(
            email_text     = scenario['email'],
            amount         = scenario['amount'],
            recipient_name = scenario['recipient_name'],
            account_number = scenario['account_number'],
            payment_type   = scenario['payment_type'],
            user_id        = scenario['user_id'],
            verbose        = True
        )

        print_verdict(scenario, result)

        if result.get('verdict') == scenario['expected']:
            correct += 1

        results.append({"scenario": scenario['id'], "result": result})

    # Summary
    if len(scenarios) > 1:
        print(Fore.CYAN + "─" * 60)
        print(f"\n  Scenarios run:     {len(scenarios)}")
        print(f"  Correct verdicts:  {Fore.GREEN}{correct}/{len(scenarios)}")
        accuracy = correct / len(scenarios) * 100
        colour   = Fore.GREEN if accuracy >= 66 else Fore.RED
        print(f"  Accuracy:          {colour}{accuracy:.0f}%{Style.RESET_ALL}")
        print()

        if accuracy == 100:
            print(Fore.GREEN + "All scenarios correct. Agent is working as expected.\n")
        else:
            print(Fore.YELLOW + "Some scenarios incorrect. Review the system prompt.\n")

    # Save results to file for inspection
    output = Path("data/processed/demo_results.json")
    with open(output, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(Fore.CYAN + f"  Full results saved: {output}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SentryPay CLI Demo")
    parser.add_argument(
        "--scenario", type=int, choices=[1, 2, 3], default=None,
        help="Run a specific scenario (1=BLOCK, 2=FRICTION, 3=ALLOW)"
    )
    args = parser.parse_args()
    run(scenario_id=args.scenario)