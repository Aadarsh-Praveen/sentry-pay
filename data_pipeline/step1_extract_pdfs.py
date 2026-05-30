"""
SentryPay — Step 1: PDF Text Extraction
=========================================
Extracts and cleans raw text from FBI Internet Crime Complaint Center
(IC3) annual reports. These PDFs are the primary source of real-world
fraud typology descriptions used to build SentryPay's scam pattern library.

What this script does:
  1. Opens each PDF page by page using pdfplumber
  2. Filters out irrelevant pages (statistics tables, contact info,
     org charts) by checking for fraud-related keywords
  3. Cleans the extracted text by removing page numbers, repeated
     headers, and formatting artifacts introduced by the PDF renderer
  4. Saves the cleaned relevant text as plain .txt files for Step 2

Input files (place in data/raw/):
    2023_IC3Report.pdf  — FBI IC3 Annual Report 2023
    2024_IC3Report.pdf  — FBI IC3 Annual Report 2024

Output files (saved to data/processed/):
    ic3_2023_clean.txt  — Cleaned relevant text from 2023 report
    ic3_2024_clean.txt  — Cleaned relevant text from 2024 report

Usage:
    python data_pipeline/step1_extract_pdfs.py
"""

import os
import re
import sys
from pathlib import Path
from dotenv import load_dotenv
from colorama import Fore, Style, init
import pdfplumber

init(autoreset=True)
load_dotenv()

RAW_DIR       = Path(os.getenv("RAW_DATA_DIR", "data/raw"))
PROCESSED_DIR = Path(os.getenv("PROCESSED_DATA_DIR", "data/processed"))
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# Map input PDF filenames to output text filenames
PDF_FILES = {
    "2023_IC3Report.pdf": "ic3_2023_clean.txt",
    "2024_IC3Report.pdf": "ic3_2024_clean.txt",
}

# Sections we care about — skip everything else
RELEVANT_SECTIONS = [
    "crime type",
    "fraud",
    "scam",
    "business email compromise",
    "BEC",
    "ransomware",
    "investment",
    "romance",
    "extortion",
    "phishing",
    "spoofing",
    "tech support",
    "confidence fraud",
    "wire transfer",
    "advance fee",
    "government impersonation",
    "lottery",
    "real estate",
    "identity theft"
]


# ── Cleaning helpers ─────────────────────────────────────────────────────────

def clean_page_text(text: str) -> str:
    """
    Remove PDF rendering artifacts from a single page's extracted text.

    Strips page numbers, repeated report headers, footer text, and
    collapses excessive whitespace so the output is clean prose
    suitable for Gemini to read and parse in Step 2.

    Args:
        text (str): raw text extracted from one PDF page

    Returns:
        str: cleaned text with artifacts removed
    """
    if not text:
        return ""

    # Remove page numbers (various formats)
    text = re.sub(r'\bPage\s+\d+\s+of\s+\d+\b', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\b\d+\s*\|\s*', '', text)

    # Remove report headers/footers that repeat on every page
    text = re.sub(r'IC3\s+Annual\s+Report\s+\d{4}', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Internet\s+Crime\s+Complaint\s+Center', '', text, flags=re.IGNORECASE)
    text = re.sub(r'Federal\s+Bureau\s+of\s+Investigation', '', text, flags=re.IGNORECASE)

    # Collapse whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)

    # Remove lines that are just numbers or very short (table artifacts)
    lines = text.split('\n')
    lines = [
        line for line in lines
        if len(line.strip()) > 20 or line.strip() == ''
    ]

    return '\n'.join(lines).strip()


def is_relevant_section(text: str) -> bool:
    """
    Determine whether a page contains fraud-relevant content worth keeping.

    Checks the page text against a list of fraud-related keywords.
    Pages that match at least one keyword are kept; all others are
    discarded to reduce noise before passing text to Gemini.

    Args:
        text (str): cleaned text from one page

    Returns:
        bool: True if the page contains fraud-relevant content
    """
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in RELEVANT_SECTIONS)


# ── Main extraction ──────────────────────────────────────────────────────────

def extract_pdf(pdf_path: Path, output_path: Path) -> dict:
    """
    Extract, filter, clean, and save text from a single PDF file.

    Processes the file page by page, applies relevance filtering and
    cleaning, then writes all relevant pages to a single output text
    file. Each page is prefixed with a --- PAGE N --- marker to help
    Gemini understand document structure in Step 2.

    Args:
        pdf_path (Path): path to the source PDF file
        output_path (Path): path where cleaned text will be saved

    Returns:
        dict: summary containing success flag, total pages,
              relevant pages found, and output file path
    """
    print(f"\n  Processing: {Fore.CYAN}{pdf_path.name}{Style.RESET_ALL}")

    if not pdf_path.exists():
        print(Fore.RED + f"    ERROR: File not found — {pdf_path}")
        print(Fore.YELLOW + f"    Download from: https://www.ic3.gov/Media/PDF/AnnualReport/")
        return {"success": False, "pages": 0, "relevant_pages": 0}

    relevant_pages = []
    total_pages    = 0

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        print(f"    Total pages: {total_pages}")

        for i, page in enumerate(pdf.pages):
            raw_text = page.extract_text()
            if not raw_text:
                continue

            clean = clean_page_text(raw_text)

            if is_relevant_section(clean):
                relevant_pages.append(f"--- PAGE {i+1} ---\n{clean}")

            if (i + 1) % 20 == 0:
                print(f"    Scanned {i+1}/{total_pages} pages...", end='\r')

    print(f"    Relevant pages found: {Fore.GREEN}{len(relevant_pages)}{Style.RESET_ALL} / {total_pages}")

    full_text = '\n\n'.join(relevant_pages)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(full_text)

    print(f"    Saved to: {Fore.GREEN}{output_path}{Style.RESET_ALL}")
    print(f"    Size: {len(full_text):,} characters")

    return {
        "success":        True,
        "pages":          total_pages,
        "relevant_pages": len(relevant_pages),
        "output":         str(output_path),
        "char_count":     len(full_text)
    }


def run():
    print(Fore.CYAN + "\n── SentryPay: Step 1 — PDF Extraction \n")

    results = {}
    found_any = False

    for pdf_filename, txt_filename in PDF_FILES.items():
        pdf_path    = RAW_DIR / pdf_filename
        output_path = PROCESSED_DIR / txt_filename

        result = extract_pdf(pdf_path, output_path)
        results[pdf_filename] = result

        if result["success"]:
            found_any = True

    # Summary
    print(Fore.CYAN + "\n── Summary \n")
    for name, result in results.items():
        status = Fore.GREEN + "✓" if result["success"] else Fore.RED + "✗"
        print(f"  {status} {name}: {result.get('relevant_pages', 0)} relevant pages extracted")

    if not found_any:
        print(Fore.RED + """
  No PDF files found. Please download them:
  
  FBI IC3 2023: https://www.ic3.gov/Media/PDF/AnnualReport/2023_IC3Report.pdf
  FBI IC3 2024: https://www.ic3.gov/Media/PDF/AnnualReport/2024_IC3Report.pdf
  
  Save them to: data/raw/
        """)
        sys.exit(1)

    print(Fore.CYAN + "\n Step 1 Complete. Run step2_parse_typologies.py next. \n")


if __name__ == "__main__":
    run()