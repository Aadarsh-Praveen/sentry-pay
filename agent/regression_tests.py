"""
SentryPay — Regression Test Suite
====================================
20 fixed test cases with known correct verdicts used to detect
model drift after any Gemini update or system prompt change.

Why regression testing matters:
    Google updates Gemini periodically. A system prompt that produces
    correct verdicts today may behave differently after a model update.
    By running these 20 fixed cases after every deployment or model
    change, we can immediately detect if the agent's behaviour has
    shifted and act before real users are affected.

    This is the SentryPay equivalent of unit testing — except instead
    of testing code logic, we are testing the agent's reasoning quality.

Test case design:
    The 20 cases are deliberately varied across:
      - All three verdict types (BLOCK, FRICTION, ALLOW)
      - Different fraud typologies (BEC, romance, investment, tech support)
      - Different user profiles (demo_user_001, 002, 003)
      - Different payment amounts (below, near, and above anomaly threshold)
      - Edge cases (new vendor but normal amount, known account but large amount)

Pass criteria:
    - Individual test: verdict matches expected exactly
    - Suite pass: 17/20 or above (85%+)
    - Suite warning: 14-16/20 (70-84%) — review system prompt
    - Suite fail: below 14/20 — model drift detected, do not deploy

Usage:
    python agent/regression_tests.py
    python agent/regression_tests.py --verbose    # show full agent output
    python agent/regression_tests.py --fast       # skip BigQuery logging
"""

import sys
import time
import argparse
from pathlib import Path
from colorama import Fore, Style, init

sys.path.insert(0, str(Path(__file__).parent.parent))
from agent.gemini_agent import SentryPayAgent

init(autoreset=True)


# ── 20 Fixed test cases ───────────────────────────────────────────────────────

TEST_CASES = [

    # ── BLOCK cases (should be blocked) ──────────────────────────────────────

    {
        "id":          "TC-001",
        "name":        "Classic BEC — supplier bank change",
        "expected":    "BLOCK",
        "user_id":     "demo_user_001",
        "email":       "Hi Sarah, our bank details have changed. Please send all future payments to: Account GB94METRO00000087654321. The next invoice of $47,000 is due Friday. Urgent.",
        "amount":      47000,
        "recipient":   "Apex Scaffolding Ltd",
        "account":     "GB94METRO00000087654321",
        "payment_type": "Wire"
    },
    {
        "id":          "TC-002",
        "name":        "CEO wire fraud — executive impersonation",
        "expected":    "BLOCK",
        "user_id":     "demo_user_001",
        "email":       "Sarah this is urgent. I'm in a board meeting and need you to wire $55,000 immediately to this account: US44FRAUD00000099887766. Do not discuss with anyone. I'll explain later. — CEO",
        "amount":      55000,
        "recipient":   "Confidential Vendor",
        "account":     "US44FRAUD00000099887766",
        "payment_type": "Wire"
    },
    {
        "id":          "TC-003",
        "name":        "Investment scam — guaranteed returns",
        "expected":    "BLOCK",
        "user_id":     "demo_user_002",
        "email":       "Exclusive investment opportunity. Guaranteed 40% returns in 30 days. Send $80,000 to our crypto wallet to secure your position. Limited slots available. Act now.",
        "amount":      80000,
        "recipient":   "Global Wealth Partners",
        "account":     "US99INVEST0000011223344",
        "payment_type": "Wire"
    },
    {
        "id":          "TC-004",
        "name":        "Phantom hacker — tech support impersonation",
        "expected":    "BLOCK",
        "user_id":     "demo_user_001",
        "email":       "Your computer has been hacked. Microsoft Security Team has detected criminal activity on your account. To protect your savings you must immediately transfer $35,000 to a secure government holding account. Account: US88SECURE000009876543.",
        "amount":      35000,
        "recipient":   "Federal Security Holdings",
        "account":     "US88SECURE000009876543",
        "payment_type": "Wire"
    },
    {
        "id":          "TC-005",
        "name":        "Romance scam — emergency funds request",
        "expected":    "BLOCK",
        "user_id":     "demo_user_003",
        "email":       "My darling, I am stuck at the airport in Dubai. My wallet was stolen. I need you to urgently wire $25,000 to this account so I can fly home to you. I will pay you back immediately when I arrive. Account: AE070331234567890123456.",
        "amount":      25000,
        "recipient":   "David Williams",
        "account":     "AE070331234567890123456",
        "payment_type": "Wire"
    },
    {
        "id":          "TC-006",
        "name":        "Overpayment scam — refund requested",
        "expected":    "BLOCK",
        "user_id":     "demo_user_002",
        "email":       "We accidentally overpaid your invoice by $42,000. Please refund the excess immediately to account US55REFUND000087654321. Our accountant requires this today to close the quarter.",
        "amount":      42000,
        "recipient":   "Pacific Rim Trading Co Refund",
        "account":     "US55REFUND000087654321",
        "payment_type": "ACH"
    },
    {
        "id":          "TC-007",
        "name":        "Government impersonation — tax penalty",
        "expected":    "BLOCK",
        "user_id":     "demo_user_001",
        "email":       "FINAL NOTICE from IRS. You owe $18,500 in back taxes. Failure to pay within 24 hours will result in arrest. Pay immediately via wire to: US11IRS000000123456789. Reference: CASE-2026-4421.",
        "amount":      18500,
        "recipient":   "IRS Tax Collection",
        "account":     "US11IRS000000123456789",
        "payment_type": "Wire"
    },

    # ── FRICTION cases (should be flagged but not blocked) ────────────────────

    {
        "id":          "TC-008",
        "name":        "New vendor — consulting invoice",
        "expected":    "FRICTION",
        "user_id":     "demo_user_001",
        "email":       "Hi Sarah, please find attached invoice INV-2094 for consulting services in April — $9,500 net 30. Payment details: BuildRight Advisory Services, Account US44FIRST00000112233445.",
        "amount":      9500,
        "recipient":   "BuildRight Advisory Services",
        "account":     "US44FIRST00000112233445",
        "payment_type": "ACH"
    },
    {
        "id":          "TC-009",
        "name":        "Large payment to known vendor — amount anomalous",
        "expected":    "FRICTION",
        "user_id":     "demo_user_001",
        "email":       "Hi Sarah, attached is our invoice for the emergency scaffolding work on the Canary Wharf project — $38,000. Same account as always. Thanks, Mike at Apex.",
        "amount":      38000,
        "recipient":   "Apex Scaffolding Ltd",
        "account":     "GB29NWBK60161331926819",
        "payment_type": "Wire"
    },
    {
        "id":          "TC-010",
        "name":        "New vendor — IT services invoice",
        "expected":    "FRICTION",
        "user_id":     "demo_user_003",
        "email":       "Dear Maria, invoice #8821 for managed IT services setup — $6,200. This is our first invoice so our account details are enclosed: TechPro Solutions, Account US33TECH00000044556677.",
        "amount":      6200,
        "recipient":   "TechPro Solutions",
        "account":     "US33TECH00000044556677",
        "payment_type": "ACH"
    },
    {
        "id":          "TC-011",
        "name":        "Slightly urgent tone — known supplier",
        "expected":    "FRICTION",
        "user_id":     "demo_user_002",
        "email":       "James, we need payment for shipment #4421 processed today or customs will hold the goods. $52,000 to our usual account. This is time sensitive — please confirm.",
        "amount":      52000,
        "recipient":   "Pacific Rim Trading Co",
        "account":     "US12345678901234567890",
        "payment_type": "Wire"
    },
    {
        "id":          "TC-012",
        "name":        "First payment to new payroll provider",
        "expected":    "FRICTION",
        "user_id":     "demo_user_001",
        "email":       "Hi Sarah, as discussed, we are switching payroll providers from next month. First payment of $28,000 should go to: Streamline Payroll Ltd, Account GB55STREAM00000033221100.",
        "amount":      28000,
        "recipient":   "Streamline Payroll Ltd",
        "account":     "GB55STREAM00000033221100",
        "payment_type": "ACH"
    },
    {
        "id":          "TC-013",
        "name":        "Unverified account — moderate amount",
        "expected":    "FRICTION",
        "user_id":     "demo_user_003",
        "email":       "Maria, please process payment for the window cleaning contract renewal — $4,800. New account this year: Crystal Clear Services, Account US77CRYSTAL0000055443322.",
        "amount":      4800,
        "recipient":   "Crystal Clear Services",
        "account":     "US77CRYSTAL0000055443322",
        "payment_type": "ACH"
    },

    # ── ALLOW cases (should be cleared) ──────────────────────────────────────

    {
        "id":          "TC-014",
        "name":        "Regular monthly invoice — known vendor normal amount",
        "expected":    "ALLOW",
        "user_id":     "demo_user_001",
        "email":       "Hi Sarah, please see attached Invoice #7042 for office supplies delivered 12th May — $847.50. Same account as always. Thanks, Jenny at City Office Supplies.",
        "amount":      847.50,
        "recipient":   "City Office Supplies",
        "account":     "GB82WEST12345698765432",
        "payment_type": "ACH"
    },
    {
        "id":          "TC-015",
        "name":        "Payroll run — known payroll provider",
        "expected":    "ALLOW",
        "user_id":     "demo_user_001",
        "email":       "Monthly payroll reminder: Please process May payroll of $27,800 to Hallmark Payroll Services as usual. Account unchanged.",
        "amount":      27800,
        "recipient":   "Hallmark Payroll Services",
        "account":     "GB76LOYD30114900000000",
        "payment_type": "ACH"
    },
    {
        "id":          "TC-016",
        "name":        "Regular materials invoice — known vendor",
        "expected":    "ALLOW",
        "user_id":     "demo_user_001",
        "email":       "BuildRight invoice #5512 for materials delivered to the Farringdon site — $6,200. Same bank details. Thank you for your continued business.",
        "amount":      6200,
        "recipient":   "BuildRight Materials Inc",
        "account":     "GB33BUKB20201555555555",
        "payment_type": "ACH"
    },
    {
        "id":          "TC-017",
        "name":        "Regular freight invoice — known vendor",
        "expected":    "ALLOW",
        "user_id":     "demo_user_002",
        "email":       "Freightline Logistics — Invoice #9021. April freight charges for three containers: $8,200. Payment to our standard account as usual.",
        "amount":      8200,
        "recipient":   "Freightline Logistics",
        "account":     "US09876543210987654321",
        "payment_type": "ACH"
    },
    {
        "id":          "TC-018",
        "name":        "Insurance renewal — known vendor",
        "expected":    "ALLOW",
        "user_id":     "demo_user_001",
        "email":       "MetroCity Insurance — Q2 premium invoice. Amount due: $4,180. No changes to our payment details. Please process at your earliest convenience.",
        "amount":      4180,
        "recipient":   "MetroCity Insurance Group",
        "account":     "GB06NWBK60161331926820",
        "payment_type": "ACH"
    },
    {
        "id":          "TC-019",
        "name":        "Regular cleaning invoice — known vendor",
        "expected":    "ALLOW",
        "user_id":     "demo_user_003",
        "email":       "CleanPro Janitorial — monthly invoice for May cleaning services. $1,820. Please process to our usual account. No changes.",
        "amount":      1820,
        "recipient":   "CleanPro Janitorial",
        "account":     "US34343434343434343434",
        "payment_type": "ACH"
    },
    {
        "id":          "TC-020",
        "name":        "Regular customs invoice — known vendor",
        "expected":    "FRICTION",
        "user_id":     "demo_user_002",
        "email":       "Delta Customs Brokers — April customs clearance fees. Invoice #DC-4421. Amount: $3,150. Same payment details as always. Thank you.",
        "amount":      3150,
        "recipient":   "Delta Customs Brokers",
        "account":     "US11223344556677889900",
        "payment_type": "ACH"
    }
]


# ── Runner ────────────────────────────────────────────────────────────────────

def run_tests(verbose: bool = False, skip_bq: bool = False):
    """
    Run all 20 regression test cases through the live SentryPay agent.

    For each test case, the full agent pipeline is executed —
    all three Elastic tools are called, Gemini reasons over the
    results, and a verdict is produced. The verdict is compared
    against the expected outcome and the result is recorded.

    Args:
        verbose (bool): if True, print full agent tool call output
        skip_bq (bool): if True, suppress BigQuery logging during tests
                        (set to True for fast local testing)
    """
    print(Fore.CYAN + "SentryPay — Regression Test Suite 20 Fixed Cases")

    agent   = SentryPayAgent()
    results = []
    passed  = 0
    failed  = 0

    # Count by expected verdict type
    block_total    = sum(1 for t in TEST_CASES if t['expected'] == 'BLOCK')
    friction_total = sum(1 for t in TEST_CASES if t['expected'] == 'FRICTION')
    allow_total    = sum(1 for t in TEST_CASES if t['expected'] == 'ALLOW')

    block_pass    = 0
    friction_pass = 0
    allow_pass    = 0

    print(f"  Total cases: {len(TEST_CASES)}")
    print(f"  Expected: {block_total} BLOCK  |  {friction_total} FRICTION  |  {allow_total} ALLOW\n")
    print("─" * 60)

    for i, case in enumerate(TEST_CASES, 1):
        print(f"\n  [{i:02d}/20] {case['id']} — {case['name']}")
        print(f"         Expected: {case['expected']}")

        try:
            result = agent.analyse(
                email_text     = case['email'],
                amount         = case['amount'],
                recipient_name = case['recipient'],
                account_number = case['account'],
                payment_type   = case['payment_type'],
                user_id        = case['user_id'],
                verbose        = verbose
            )

            actual     = result.get('verdict', 'UNKNOWN')
            confidence = result.get('confidence', 0)
            correct    = actual == case['expected']

            if correct:
                passed += 1
                status  = Fore.GREEN + "PASS"
                if case['expected'] == 'BLOCK':    block_pass += 1
                if case['expected'] == 'FRICTION': friction_pass += 1
                if case['expected'] == 'ALLOW':    allow_pass += 1
            else:
                failed += 1
                status  = Fore.RED + f"FAIL (got {actual})"

            print(f"         Result:   {status}{Style.RESET_ALL}  "
                  f"confidence={confidence:.0%}  "
                  f"{result.get('processing_ms', 0):,}ms")

            if not correct:
                print(Fore.YELLOW + f"         Reasoning: {result.get('reasoning', '')[:100]}...")

            results.append({
                "id":         case['id'],
                "name":       case['name'],
                "expected":   case['expected'],
                "actual":     actual,
                "correct":    correct,
                "confidence": confidence,
                "ms":         result.get('processing_ms', 0)
            })

            # Small delay to avoid rate limiting
            time.sleep(2)

        except Exception as e:
            failed += 1
            print(Fore.RED + f"         ERROR: {str(e)[:80]}")
            results.append({
                "id":       case['id'],
                "name":     case['name'],
                "expected": case['expected'],
                "actual":   "ERROR",
                "correct":  False,
                "error":    str(e)
            })

    # ── Final report ──────────────────────────────────────────────────────────
    total    = passed + failed
    accuracy = (passed / total * 100) if total > 0 else 0

    print(Fore.CYAN + "\n" + "="*60)
    print("  REGRESSION TEST RESULTS")
    print("="*60 + "\n")

    print(f"  Total:    {total} tests")
    print(f"  Passed:   {Fore.GREEN}{passed}{Style.RESET_ALL}")
    print(f"  Failed:   {Fore.RED if failed else Fore.GREEN}{failed}{Style.RESET_ALL}")
    print(f"  Accuracy: {accuracy:.0f}%\n")

    print(f"  By verdict type:")
    print(f"    BLOCK    {block_pass}/{block_total}  {'✓' if block_pass == block_total else '✗'}")
    print(f"    FRICTION {friction_pass}/{friction_total}  {'✓' if friction_pass == friction_total else '✗'}")
    print(f"    ALLOW    {allow_pass}/{allow_total}  {'✓' if allow_pass == allow_total else '✗'}")

    print(Fore.CYAN + "\n" + "─"*60)

    if accuracy >= 85:
        print(Fore.GREEN + f"\n  PASS ({accuracy:.0f}%) — Agent behaviour is stable.\n")
        verdict_str = "PASS"
    elif accuracy >= 70:
        print(Fore.YELLOW + f"\n  WARNING ({accuracy:.0f}%) — Review system prompt.\n")
        verdict_str = "WARNING"
    else:
        print(Fore.RED + f"\n FAIL ({accuracy:.0f}%) — Model drift detected.\n")
        verdict_str = "FAIL"

    print("="*60 + "\n")

    # Show failures in detail
    failures = [r for r in results if not r['correct']]
    if failures:
        print(Fore.YELLOW + "  Failed cases:")
        for f in failures:
            print(f"    {f['id']} — {f['name']}")
            print(f"      Expected {f['expected']} → Got {f.get('actual', 'ERROR')}")

    # Save results
    import json
    from datetime import datetime
    output = {
        "run_date":    datetime.now().isoformat(),
        "total":       total,
        "passed":      passed,
        "failed":      failed,
        "accuracy":    accuracy,
        "verdict":     verdict_str,
        "cases":       results
    }

    output_path = Path("data/processed/regression_results.json")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)

    print(Fore.CYAN + f"  Full results saved: {output_path}\n")
    return accuracy >= 85


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SentryPay Regression Tests")
    parser.add_argument("--verbose", action="store_true", help="Show full agent output per test")
    parser.add_argument("--fast",    action="store_true", help="Skip BigQuery logging")
    args = parser.parse_args()

    success = run_tests(verbose=args.verbose, skip_bq=args.fast)
    sys.exit(0 if success else 1)