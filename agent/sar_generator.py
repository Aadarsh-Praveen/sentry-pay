"""
SentryPay — SAR PDF Generator
===============================
Automatically generates a Suspicious Activity Report (SAR) draft
whenever the agent produces a BLOCK verdict.

What is a SAR:
    A Suspicious Activity Report is a document that financial
    institutions are legally required to file with FinCEN (the U.S.
    Financial Crimes Enforcement Network) when they detect potential
    money laundering, fraud, or other financial crimes. SentryPay
    auto-drafts this document to save compliance teams hours of work.

What this script generates:
    A professionally formatted PDF containing:
      - Case reference number and date
      - Subject information (payment recipient and account)
      - Suspicious activity description
      - Transaction details (amount, type, date)
      - Agent reasoning and red flags
      - Recommended next steps for the compliance officer

Important note:
    This is a DRAFT document for review by a qualified compliance
    officer. It is NOT a filed SAR. The compliance officer must
    review, complete any missing fields, and file officially through
    the BSA E-Filing System at bsaefiling.fincen.treas.gov.

Output:
    PDF saved to data/sar_reports/SAR_{decision_id[:8]}.pdf

Usage:
    from agent.sar_generator import generate_sar
    pdf_path = generate_sar(verdict_dict, payment_details)
"""

import os
from pathlib import Path
from datetime import datetime
from colorama import Fore, init

init(autoreset=True)

SAR_DIR = Path("data/sar_reports")
SAR_DIR.mkdir(parents=True, exist_ok=True)


def generate_sar(
    decision_id:    str,
    verdict:        dict,
    email_text:     str,
    amount:         float,
    recipient_name: str,
    account_number: str,
    payment_type:   str,
    user_id:        str
) -> str:
    """
    Generate a SAR draft PDF for a blocked payment.

    Builds a professionally formatted PDF containing all the
    information a compliance officer needs to review and file
    an official SAR with FinCEN.

    Args:
        decision_id (str): unique SentryPay decision identifier
        verdict (dict): full verdict dict from the Gemini agent
        email_text (str): the suspicious email that triggered the block
        amount (float): blocked payment amount
        recipient_name (str): intended payment recipient
        account_number (str): destination account number
        payment_type (str): ACH / Wire / RTP / Zelle / Check
        user_id (str): identifier of the reporting user

    Returns:
        str: file path to the generated PDF
    """
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer,
            Table, TableStyle, HRFlowable
        )
        from reportlab.lib.enums import TA_LEFT, TA_CENTER

    except ImportError:
        print(Fore.YELLOW + "reportlab not installed. Run: pip install reportlab")
        return _generate_text_sar(decision_id, verdict, email_text,
                                   amount, recipient_name, account_number,
                                   payment_type, user_id)

    short_id  = decision_id[:8].upper()
    filename  = SAR_DIR / f"SAR_{short_id}.pdf"
    filed_date = datetime.now().strftime("%B %d, %Y")

    doc   = SimpleDocTemplate(
        str(filename),
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch
    )

    styles   = getSampleStyleSheet()
    elements = []

    # ── Styles ────────────────────────────────────────────────────────────────
    title_style = ParagraphStyle(
        "Title",
        parent=styles["Heading1"],
        fontSize=16,
        textColor=colors.HexColor("#1a1a2e"),
        spaceAfter=4,
        alignment=TA_CENTER
    )
    subtitle_style = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#555555"),
        spaceAfter=2,
        alignment=TA_CENTER
    )
    section_style = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontSize=11,
        textColor=colors.HexColor("#cc0000"),
        spaceBefore=12,
        spaceAfter=4
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=9,
        leading=14,
        spaceAfter=4
    )
    label_style = ParagraphStyle(
        "Label",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#666666"),
        spaceAfter=1
    )
    warning_style = ParagraphStyle(
        "Warning",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#cc0000"),
        leading=12
    )

    # ── Header ────────────────────────────────────────────────────────────────
    elements.append(Paragraph("SUSPICIOUS ACTIVITY REPORT", title_style))
    elements.append(Paragraph("DRAFT — For Compliance Officer Review Only", subtitle_style))
    elements.append(Paragraph(
        "Auto-generated by SentryPay AI Fraud Detection System",
        subtitle_style
    ))
    elements.append(Spacer(1, 6))
    elements.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#cc0000")))
    elements.append(Spacer(1, 6))

    # ── Warning box ───────────────────────────────────────────────────────────
    warning_data = [[
        Paragraph(
            "⚠ DRAFT DOCUMENT — This SAR draft must be reviewed by a qualified compliance "
            "officer before filing. Official SAR filing must be completed through the "
            "BSA E-Filing System at bsaefiling.fincen.treas.gov. This document alone "
            "does not constitute a filed SAR.",
            warning_style
        )
    ]]
    warning_table = Table(warning_data, colWidths=[6.8 * inch])
    warning_table.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, -1), colors.HexColor("#fff3f3")),
        ("BOX",         (0, 0), (-1, -1), 1, colors.HexColor("#cc0000")),
        ("TOPPADDING",  (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
    ]))
    elements.append(warning_table)
    elements.append(Spacer(1, 10))

    # ── Case reference ────────────────────────────────────────────────────────
    ref_data = [
        ["SAR Reference:",    f"SENTRYPAY-{short_id}",
         "Date Generated:",   filed_date],
        ["SentryPay Case ID:", decision_id,
         "Reporting System:", "SentryPay v1.0"],
        ["Confidence Score:", f"{verdict.get('confidence', 0):.0%}",
         "Verdict:",          "BLOCK — Payment Halted"],
    ]
    ref_table = Table(ref_data, colWidths=[1.4*inch, 2.3*inch, 1.4*inch, 2.2*inch])
    ref_table.setStyle(TableStyle([
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("FONTNAME",      (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",      (2, 0), (2, -1), "Helvetica-Bold"),
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#f8f8f8")),
        ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("INNERGRID",     (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
    ]))
    elements.append(ref_table)

    # ── Section 1: Suspicious Activity ───────────────────────────────────────
    elements.append(Paragraph("1. SUSPICIOUS ACTIVITY DESCRIPTION", section_style))

    typology = verdict.get('typology_matched') or 'Unknown Fraud Pattern'
    elements.append(Paragraph(f"<b>Fraud Pattern Identified:</b> {typology}", body_style))
    elements.append(Spacer(1, 4))

    reasoning = verdict.get('reasoning', 'No reasoning provided.')
    elements.append(Paragraph("<b>Agent Analysis:</b>", body_style))
    elements.append(Paragraph(reasoning, body_style))
    elements.append(Spacer(1, 4))

    red_flags = verdict.get('red_flags', [])
    if red_flags:
        elements.append(Paragraph("<b>Red Flags Identified:</b>", body_style))
        for flag in red_flags:
            elements.append(Paragraph(f"• {flag}", body_style))

    # ── Section 2: Transaction Details ───────────────────────────────────────
    elements.append(Paragraph("2. TRANSACTION DETAILS", section_style))

    txn_data = [
        ["Field",               "Value"],
        ["Amount",              f"${amount:,.2f} USD"],
        ["Payment Type",        payment_type],
        ["Intended Recipient",  recipient_name],
        ["Destination Account", account_number],
        ["Transaction Date",    datetime.now().strftime("%Y-%m-%d")],
        ["Status",              "BLOCKED — Payment Not Executed"],
        ["Reporting User",      user_id],
    ]
    txn_table = Table(txn_data, colWidths=[2.0*inch, 5.3*inch])
    txn_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("FONTNAME",      (0, 1), (0, -1), "Helvetica-Bold"),
        ("BACKGROUND",    (0, 1), (-1, -1), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.HexColor("#f8f8f8"), colors.white]),
        ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("INNERGRID",     (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
    ]))
    elements.append(txn_table)

    # ── Section 3: Original Communication ────────────────────────────────────
    elements.append(Paragraph("3. ORIGINAL COMMUNICATION", section_style))
    elements.append(Paragraph(
        "The following email or message triggered the payment request:", body_style
    ))

    email_preview = email_text[:800] + ("..." if len(email_text) > 800 else "")
    email_style = ParagraphStyle(
        "Email",
        parent=styles["Code"],
        fontSize=8,
        leading=12,
        leftIndent=10
    )
    email_data = [[Paragraph(email_preview.replace('\n', '<br/>'), email_style)]]
    email_table = Table(email_data, colWidths=[7.3*inch])
    email_table.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#f5f5f5")),
        ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#aaaaaa")),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
    ]))
    elements.append(email_table)

    # ── Section 4: Recommended Actions ───────────────────────────────────────
    elements.append(Paragraph("4. RECOMMENDED NEXT STEPS", section_style))

    actions = [
        "1. Do NOT execute the blocked payment.",
        "2. Contact the purported sender through a VERIFIED channel "
           "(known phone number, not email) to confirm the request.",
        "3. Preserve all communication records related to this request.",
        "4. Review and complete this SAR draft.",
        "5. File the completed SAR through the BSA E-Filing System "
           "within 30 days of detection (or 60 days if no suspect identified).",
        "6. Notify the sending institution if a wire transfer was already initiated.",
        f"7. Recommended action per agent: {verdict.get('recommended_action', 'Manual review required.')}",
    ]
    for action in actions:
        elements.append(Paragraph(action, body_style))

    # ── Footer ────────────────────────────────────────────────────────────────
    elements.append(Spacer(1, 12))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
    elements.append(Spacer(1, 4))
    elements.append(Paragraph(
        f"Generated by SentryPay AI Fraud Detection System | "
        f"Case ID: {decision_id} | {filed_date} | "
        f"This document is confidential and intended for compliance use only.",
        label_style
    ))

    doc.build(elements)
    print(Fore.GREEN + f"SAR PDF generated: {filename}")
    return str(filename)


def _generate_text_sar(
    decision_id, verdict, email_text,
    amount, recipient_name, account_number,
    payment_type, user_id
) -> str:
    """
    Fallback text-based SAR when reportlab is not installed.

    Generates a plain text SAR report instead of a PDF.
    Install reportlab for professional PDF output:
        pip install reportlab

    Returns:
        str: path to the generated .txt file
    """
    short_id  = decision_id[:8].upper()
    filename  = SAR_DIR / f"SAR_{short_id}.txt"
    filed_date = datetime.now().strftime("%B %d, %Y")

    content = f"""
SUSPICIOUS ACTIVITY REPORT — DRAFT
====================================
SENTRYPAY AI FRAUD DETECTION SYSTEM
Case Reference: SENTRYPAY-{short_id}
Date Generated: {filed_date}

⚠ DRAFT DOCUMENT — Must be reviewed by a compliance officer before filing.

1. SUSPICIOUS ACTIVITY
-----------------------
Fraud Pattern: {verdict.get('typology_matched', 'Unknown')}
Confidence:    {verdict.get('confidence', 0):.0%}
Reasoning:     {verdict.get('reasoning', '')}

Red Flags:
{chr(10).join(f'  • {f}' for f in verdict.get('red_flags', []))}

2. TRANSACTION DETAILS
-----------------------
Amount:          ${amount:,.2f} USD
Payment Type:    {payment_type}
Recipient:       {recipient_name}
Account:         {account_number}
Date:            {datetime.now().strftime('%Y-%m-%d')}
Status:          BLOCKED — Payment Not Executed

3. ORIGINAL EMAIL
------------------
{email_text[:600]}

4. NEXT STEPS
--------------
1. Do NOT execute the blocked payment.
2. Contact the sender through a VERIFIED channel.
3. File this SAR through BSA E-Filing within 30 days.
4. {verdict.get('recommended_action', 'Manual review required.')}

SentryPay Case ID: {decision_id}
"""

    with open(filename, 'w') as f:
        f.write(content)

    print(Fore.YELLOW + f"Text SAR generated (install reportlab for PDF): {filename}")
    return str(filename)