import os
import re
import hashlib
import json
import shutil
from pathlib import Path
import pdfplumber
from datetime import datetime

BASE_DIR = Path(r"C:\Users\Siddhi\Desktop\sorted_PDFs")
UNIDENTIFIED_DIR = BASE_DIR / "Unidentified"
OUTPUT_FILE = BASE_DIR / "master_charge_extraction_results.json"
LIMIT = None

CURRENCY_PATTERN = (
    r"USD|INR|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|"
    r"SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND"
)

CHARGE_LINE_PATTERN = re.compile(
    r"\b"
    r"(?P<size_type>\d{2}[A-Z]{2})\s+"
    r"[A-Z]\s+"
    r"(?P<description>.*?)"
    r"\s+[A-Z]{2,4}\s+"
    r"\d+(?:\.\d+)?[A-Z]+\s+"
    r"(?P<rate>[\d,]+(?:\.\d+)?)"
    r"(?P<rate_currency>" + CURRENCY_PATTERN + r")"
    r"\s+"
    r"(?P<amount>[\d,]+(?:\.\d+)?)"
    r"(?P<amount_currency>" + CURRENCY_PATTERN + r")?"
    r"\b",
    re.IGNORECASE,
)

MAERSK_CHARGE_LINE_PATTERN = re.compile(
    r"(?P<description>.+?)\s+"
    r"(?P<quantity>\d+(?:\.\d+)?)\s+"
    r"(?P<unit>[A-Z]+)\s+"
    r"(?P<rate>[\d,]+(?:\.\d+)?)\s+"
    r"(?P<currency>" + CURRENCY_PATTERN + r")\s+"
    r"(?P<amount>[\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)

def clean_text(value):
    if value is None:
        return ""

    value = str(value)
    value = value.replace("\xa0", " ")
    value = value.replace("\u200b", "")
    value = value.replace("\ufeff", "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()

def clean_number(value):
    if value is None:
        return None

    value = str(value).replace(",", "").strip()

    try:
        return float(value)
    except ValueError:
        return None

def table_to_text(table):
    rows = []

    for row in table:
        if not row:
            continue

        cells = []

        for cell in row:
            if cell is None:
                cell = ""

            cell = clean_text(cell)
            cells.append(cell)

        rows.append(" | ".join(cells))

    return "\n".join(rows)

def extract_pdf_content(pdf_path):
    text_parts = []
    table_parts = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()

                if page_text:
                    text_parts.append(page_text)

                tables = page.extract_tables()

                for table in tables:
                    table_text = table_to_text(table)

                    if table_text:
                        table_parts.append(table_text)

        return "\n".join(text_parts), table_parts, None

    except Exception as error:
        return "", [], str(error)

def get_unique_pdf_files(folder, limit=None):
    pdf_files = []
    hashes = set()
    duplicate_count = 0

    for pdf_path in sorted(folder.glob("*.pdf")):
        try:
            file_hash = hashlib.sha256(
                pdf_path.read_bytes()
            ).hexdigest()
        except Exception:
            continue

        if file_hash in hashes:
            duplicate_count += 1
            continue

        hashes.add(file_hash)
        pdf_files.append(pdf_path)

        if limit is not None and len(pdf_files) >= limit:
            break

    return pdf_files, duplicate_count

def extract_cma_cgm_invoice_no(text):
    match = re.search(
        r"\bINE[A-Z0-9]+\b",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(0).upper()

    return None

def extract_maersk_invoice_no(text):
    patterns = [
        r"\bMH\d{2}[A-Z]{2}\d+\b",
        r"\b[A-Z]{2}\d{8,}\b",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match:
            return match.group(0).upper()

    return None

def extract_hapag_lloyd_invoice_no(text):
    match = re.search(
        r"\bINVOICE\s+NO\.?\s*:\s*([A-Z0-9]+)",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).upper()

    return None

def extract_cma_cgm_charges(text, tables):
    charges = []
    seen = set()

    source_parts = []

    for table_text in tables:
        if table_text:
            source_parts.append(str(table_text))

    if text:
        source_parts.append(text)

    for source in source_parts:
        for row in source.splitlines():
            row = clean_text(row)

            if not row:
                continue

            for match in CHARGE_LINE_PATTERN.finditer(row):
                charge_name = clean_text(
                    match.group("description")
                )

                rate_currency = match.group(
                    "rate_currency"
                ).upper()

                amount = clean_number(
                    match.group("amount")
                )

                amount_currency = match.group(
                    "amount_currency"
                )

                if amount_currency:
                    currency = amount_currency.upper()
                else:
                    currency = rate_currency

                if not charge_name or amount is None:
                    continue

                charge_key = (
                    charge_name.upper(),
                    currency,
                    round(amount, 2),
                )

                if charge_key in seen:
                    continue

                seen.add(charge_key)

                charges.append(
                    {
                        "CHARGE_NAME": charge_name,
                        "CURRENCY_TYPE": currency,
                        "AMOUNT": amount,
                    }
                )

    return charges

def extract_maersk_charges(text, tables):
    charges = []
    seen = set()

    tax_pattern = re.compile(
        r"\bIN\s+"
        r"(?:CGST|SGST)\s+"
        r"\d+(?:\.\d+)?%\s+"
        r"[\d,]+(?:\.\d+)?"
        r"(?:\s+SAC/HSN\s+\d+)?",
        re.IGNORECASE,
    )

    standard_pattern = re.compile(
        r"^(?P<description>[A-Z][A-Za-z0-9 .,'&()\/\-–]+?)"
        r"\s+"
        r"\d+\s+"
        r"[A-Z]{2,5}\s+"
        r"[\d,]+(?:\.\d+)?\s+"
        r"[A-Z]{3}\s+"
        r"(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"(?P<currency>USD|INR|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)"
        r"\s*$",
        re.IGNORECASE,
    )

    def add_charge(charge_name, currency, amount):
        charge_name = clean_text(charge_name)

        if not charge_name or amount is None:
            return

        charge_name = re.sub(
            r"\b(?:CGST|SGST|IGST)\b.*$",
            "",
            charge_name,
            flags=re.IGNORECASE,
        )

        charge_name = clean_text(charge_name)

        if not charge_name:
            return

        if charge_name.upper() in {
            "TOTAL",
            "SUBTOTAL",
            "TAX",
            "CGST",
            "SGST",
            "IGST",
        }:
            return

        charge_key = (
            charge_name.upper(),
            currency.upper(),
            round(amount, 2),
        )

        if charge_key in seen:
            return

        seen.add(charge_key)

        charges.append(
            {
                "CHARGE_NAME": charge_name,
                "CURRENCY_TYPE": currency.upper(),
                "AMOUNT": amount,
            }
        )

    if text:
        for row in text.splitlines():
            row = clean_text(row)

            if not row:
                continue

            row = tax_pattern.sub(" ", row)
            row = clean_text(row)

            if not row:
                continue

            match = standard_pattern.match(row)

            if match:
                add_charge(
                    match.group("description"),
                    match.group("currency"),
                    clean_number(match.group("amount")),
                )
                continue

            for match in MAERSK_CHARGE_LINE_PATTERN.finditer(row):
                add_charge(
                    match.group("description"),
                    match.group("currency"),
                    clean_number(match.group("amount")),
                )

    if not charges:
        for table_text in tables:
            if not table_text:
                continue

            for row in str(table_text).splitlines():
                row = clean_text(row)

                if not row:
                    continue

                row = tax_pattern.sub(" ", row)
                row = clean_text(row)

                if not row:
                    continue

                for match in MAERSK_CHARGE_LINE_PATTERN.finditer(row):
                    add_charge(
                        match.group("description"),
                        match.group("currency"),
                        clean_number(match.group("amount")),
                    )

    return charges

def extract_hapag_lloyd_charges(text, tables):
    charges = []
    seen = set()

    charge_pattern = re.compile(
        r"(?P<charge_name>[A-Z][A-Z0-9 .,'&()\/-]*?)"
        r"(?:\s+\d{6})?"
        r"\s+"
        r"(?P<amount>[\d,]+\.\d+)\s+"
        r"(?P<currency>" + CURRENCY_PATTERN + r")\b",
        re.IGNORECASE,
    )

    source_parts = []

    for table_text in tables:
        if table_text:
            source_parts.append(str(table_text))

    if text:
        source_parts.append(text)

    for source in source_parts:
        for row in source.splitlines():
            row = clean_text(row)

            if not row:
                continue

            for match in charge_pattern.finditer(row):
                charge_name = clean_text(
                    match.group("charge_name")
                )

                amount = clean_number(
                    match.group("amount")
                )

                currency = match.group(
                    "currency"
                ).upper()

                charge = re.sub(
                    r"\b\d{6}\s*$",
                    "",
                    charge_name,
                    flags=re.IGNORECASE,
                )

                charge = re.sub(
                    r"\b(?:FLAT|CTR|BIL)\s*$",
                    "",
                    charge,
                    flags=re.IGNORECASE,
                )

                charge = re.sub(
                    r"\s+\d{3,}(?:\.\d+)?\s*$",
                    "",
                    charge,
                )

                charge = re.sub(
                    r"\s+HL[A-Z0-9]{8,}\b(?:\s+HL[A-Z0-9]{8,}\b)*\s*$",
                    "",
                    charge,
                    flags=re.IGNORECASE,
                )

                charge = re.sub(
                    r"\s+EXPORT\s+SERVICE\s+F\s*$",
                    " EXPORT SERVICE F",
                    charge,
                    flags=re.IGNORECASE,
                )

                charge = clean_text(charge)

                if charge.upper() in {
                    "NET",
                    "GROSS",
                }:
                    continue

                if not charge or amount is None:
                    continue

                charge_key = (
                    charge.upper(),
                    currency,
                    round(amount, 2),
                )

                if charge_key in seen:
                    continue

                seen.add(charge_key)

                charges.append(
                    {
                        "CHARGE_NAME": charge,
                        "CURRENCY_TYPE": currency,
                        "AMOUNT": amount,
                    }
                )

    return charges

def extract_hmm_invoice_no(text):
    match = re.search(
        r"\b(?:INVOICE\s*(?:NO\.?|NUMBER)\s*[:#]?|INV\s*NO\.?\s*[:#]?)\s*([A-Z0-9-]+)",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).upper()

    return None


def extract_hmm_charges(text, tables):
    charges = []
    seen = set()

    currency_set = {
        "USD", "INR", "EUR", "GBP", "AED", "SGD", "CNY", "RMB",
        "JPY", "AUD", "CAD", "CHF", "HKD", "MYR", "SAR", "QAR",
        "OMR", "KWD", "BHD", "NZD", "THB", "IDR", "KRW", "VND"
    }

    source_parts = []

    for table_text in tables:
        if table_text:
            source_parts.append(str(table_text))

    if text:
        source_parts.append(text)

    for source in source_parts:
        for row in source.splitlines():
            row = clean_text(row)

            if not row:
                continue

            parts = [
                clean_text(part)
                for part in re.split(r"\s*\|\s*", row)
            ]

            parts = [part for part in parts if part]

            if len(parts) >= 8:
                currency_indexes = [
                    index
                    for index, part in enumerate(parts)
                    if part.upper() in currency_set
                ]

                for currency_index in currency_indexes:
                    if currency_index + 2 >= len(parts):
                        continue

                    charge_name = parts[0]
                    currency = parts[currency_index].upper()
                    amount = clean_number(
                        parts[currency_index + 2]
                    )

                    if (
                        not charge_name
                        or amount is None
                        or currency not in currency_set
                    ):
                        continue

                    charge_name = re.sub(
                        r"\s+\d{6}\s+\d+\s+[A-Z]{2,4}$",
                        "",
                        charge_name,
                        flags=re.IGNORECASE,
                    )

                    charge_name = re.sub(
                        r"\s+\d{6}$",
                        "",
                        charge_name,
                        flags=re.IGNORECASE,
                    )

                    charge_name = clean_text(charge_name)

                    if charge_name.upper() in {
                        "DESCRIPTION OF CHARGES",
                        "DESCRIPTION",
                        "TOTAL",
                        "SUBTOTAL",
                        "NET",
                        "GROSS",
                    }:
                        continue

                    charge_key = (
                        charge_name.upper(),
                        currency,
                        round(amount, 2),
                    )

                    if charge_key in seen:
                        continue

                    seen.add(charge_key)

                    charges.append(
                        {
                            "CHARGE_NAME": charge_name,
                            "CURRENCY_TYPE": currency,
                            "AMOUNT": amount,
                        }
                    )

            else:
                match = re.search(
                    r"^(?P<charge_name>[A-Z][A-Z0-9 .,'&()\/-]*?)"
                    r"\s+"
                    r"(?:\d+\s+)?"
                    r"(?:[A-Z]{2,4}\s+)?"
                    r"(?P<currency>USD|INR|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)"
                    r"\s+"
                    r"[\d,]+(?:\.\d+)?\s+"
                    r"(?P<amount>[\d,]+(?:\.\d+)?)"
                    r"(?:\s+(?:USD|INR|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND))?\s*$",
                    row,
                    re.IGNORECASE,
                )

                if not match:
                    continue

                charge_name = clean_text(
                    match.group("charge_name")
                )

                currency = match.group(
                    "currency"
                ).upper()

                amount = clean_number(
                    match.group("amount")
                )

                charge_name = re.sub(
                    r"\s+\d{6}\s+\d+\s+[A-Z]{2,4}$",
                    "",
                    charge_name,
                    flags=re.IGNORECASE,
                )

                charge_name = re.sub(
                    r"\s+\d{6}$",
                    "",
                    charge_name,
                    flags=re.IGNORECASE,
                )

                charge_name = clean_text(charge_name)

                if (
                    not charge_name
                    or amount is None
                    or currency not in currency_set
                ):
                    continue

                if charge_name.upper() in {
                    "DESCRIPTION OF CHARGES",
                    "DESCRIPTION",
                    "TOTAL",
                    "SUBTOTAL",
                    "NET",
                    "GROSS",
                }:
                    continue

                charge_key = (
                    charge_name.upper(),
                    currency,
                    round(amount, 2),
                )

                if charge_key in seen:
                    continue

                seen.add(charge_key)

                charges.append(
                    {
                        "CHARGE_NAME": charge_name,
                        "CURRENCY_TYPE": currency,
                        "AMOUNT": amount,
                    }
                )

    return charges 

def extract_hub_and_links_invoice_no(text):
    match = re.search(
        r"\bInvoice\s+No\.?\s*:\s*([A-Z0-9\/-]+)",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).upper()

    return None


def extract_hub_and_links_charges(tables, text_parts):
    charges = []
    seen = set()

    rows = []

    def add_source(source):
        if isinstance(source, str):
            rows.extend(source.splitlines())

        elif isinstance(source, list):
            for item in source:
                if isinstance(item, str):
                    rows.extend(item.splitlines())

                elif isinstance(item, list):
                    cells = []

                    for cell in item:
                        if cell is None:
                            cells.append("")
                        else:
                            cells.append(str(cell).strip())

                    row = " ".join(
                        cell for cell in cells if cell
                    )

                    if row:
                        rows.extend(row.splitlines())

    add_source(tables)
    add_source(text_parts)

    for row in rows:
        row = clean_text(row)

        if not row:
            continue

        currency_match = re.search(
            r"\b(USD|INR|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)\b",
            row,
            re.IGNORECASE,
        )

        if not currency_match:
            continue

        currency = currency_match.group(1).upper()

        before_currency = row[:currency_match.start()].strip()

        charge_match = re.search(
            r"(?P<charge_name>.+?)\s+\d{6}\s*$",
            before_currency,
            re.IGNORECASE,
        )

        if not charge_match:
            continue

        charge_name = clean_text(
            charge_match.group("charge_name")
        )

        if not charge_name:
            continue

        if charge_name.upper() in {
            "PARTICULARS",
            "TOTAL",
            "ROUND OFF",
            "AMOUNT IN WORDS",
            "HSN/SAC",
        }:
            continue

        after_currency = row[currency_match.end():].strip()

        amounts = re.findall(
            r"(?<![A-Za-z])(?:\d{1,3}(?:,\d{2})*,\d{3}|\d+)(?:\.\d+)?",
            after_currency,
        )

        if not amounts:
            continue

        total_amount = clean_number(
            amounts[-1]
        )

        if total_amount is None:
            continue

        charge_key = (
            charge_name.upper(),
            currency,
            round(total_amount, 2),
        )

        if charge_key in seen:
            continue

        seen.add(charge_key)

        charges.append(
            {
                "CHARGE_NAME": charge_name,
                "CURRENCY_TYPE": currency,
                "AMOUNT": total_amount,
            }
        )

    return charges

def extract_jm_baxi_invoice_no(text):
    match = re.search(
        r"\bInvoice\s+No\s*:\s*([A-Z0-9\/-]+)",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).upper()

    return None


def extract_jm_baxi_charges(text, tables):
    charges = []
    seen = set()

    currency_pattern = (
        r"USD|INR|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|"
        r"SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND"
    )

    rows = []

    if isinstance(text, str):
        rows.extend(text.splitlines())

    elif isinstance(text, list):
        for item in text:
            if isinstance(item, str):
                rows.extend(item.splitlines())

    for table in tables:
        if isinstance(table, str):
            rows.extend(table.splitlines())

        elif isinstance(table, list):
            for table_row in table:
                if isinstance(table_row, list):
                    cells = []

                    for cell in table_row:
                        if cell is not None:
                            cell = clean_text(str(cell))
                            if cell:
                                cells.append(cell)

                    if cells:
                        rows.append(" ".join(cells))

                elif isinstance(table_row, str):
                    rows.extend(table_row.splitlines())

    for row in rows:
        row = clean_text(row)

        if not row:
            continue

        if re.search(
            r"^\s*(Description\s+of\s+charges|Total)\b",
            row,
            re.IGNORECASE,
        ):
            continue

        match = re.search(
            r"^(?P<charge_name>.+?)\s+"
            r"(?P<hsn>\d{6})\s+"
            r"(?P<currency>" + currency_pattern + r")\b"
            r"(?P<rest>.*)$",
            row,
            re.IGNORECASE,
        )

        if not match:
            continue

        charge_name = clean_text(
            match.group("charge_name")
        )

        currency = match.group(
            "currency"
        ).upper()

        rest = match.group("rest")

        amounts = re.findall(
            r"(?<![A-Za-z])(?:\d{1,3}(?:,\d{2})*,\d{3}|\d+)(?:\.\d+)?",
            rest,
        )

        if not amounts:
            continue

        total_amount = clean_number(
            amounts[-1]
        )

        if not charge_name or total_amount is None:
            continue

        if charge_name.upper() in {
            "DESCRIPTION OF CHARGES",
            "TOTAL",
            "TOTAL :",
        }:
            continue

        charge_key = (
            charge_name.upper(),
            currency,
            round(total_amount, 2),
        )

        if charge_key in seen:
            continue

        seen.add(charge_key)

        charges.append(
            {
                "CHARGE_NAME": charge_name,
                "CURRENCY_TYPE": currency,
                "AMOUNT": total_amount,
            }
        )

    return charges

def extract_lmt_charges(text, tables):
    charges = []
    seen = set()

    currency_pattern = (
        r"USD|INR|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|"
        r"SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND"
    )

    charge_pattern = re.compile(
        r"^\s*(?:\d+\s+)?"
        r"(?P<charge_name>.+?)\s+"
        r"\d{6}\s+"
        r"[\d,]+\.\d+\s+"
        r"(?P<currency>" + currency_pattern + r")\s+"
        r"\d+(?:\.\d+)?\s+"
        r"[\d,]+\.\d+\s+"
        r"[\d.]+\s+"
        r"[\d,]+\.\d+\s+"
        r"[\d,]+\.\d+\s*$",
        re.IGNORECASE,
    )

    rows = []

    if isinstance(text, str):
        rows.extend(text.splitlines())

    for table in tables:
        if not isinstance(table, list):
            continue

        for table_row in table:
            if not isinstance(table_row, list):
                continue

            cells = []

            for cell in table_row:
                if cell is None:
                    continue

                cell = clean_text(cell)

                if cell:
                    cells.append(cell)

            if not cells:
                continue

            row = " ".join(cells)

            row = re.sub(
                r"\s+(?=\d+\s+[A-Z])",
                "\n",
                row,
            )

            rows.extend(row.splitlines())

    for row in rows:
        row = clean_text(row)

        if not row:
            continue

        if re.match(
            r"^(?:Grand\s+Total|Total|CGST\s+Output|SGST\s+Output|"
            r"Central\s+Tax|State\s+Tax|TOTAL\s+AMOUNT|Remarks?)\b",
            row,
            re.IGNORECASE,
        ):
            continue

        match = charge_pattern.match(row)

        if not match:
            continue

        charge_name = clean_text(
            match.group("charge_name")
        )

        currency = match.group(
            "currency"
        ).upper()

        amount_matches = re.findall(
            r"(?<![A-Za-z])(?:\d{1,3}(?:,\d{2})*,\d{3}|\d+)(?:\.\d+)?",
            row,
        )

        if not amount_matches:
            continue

        total_amount = clean_number(
            amount_matches[-1]
        )

        if not charge_name or total_amount is None:
            continue

        charge_name = re.sub(
            r"^\d+\s+",
            "",
            charge_name,
        )

        charge_name = clean_text(charge_name)

        if charge_name.upper() in {
            "PARTICULARS",
            "GRAND TOTAL",
            "TOTAL",
            "CGST OUTPUT",
            "SGST OUTPUT",
        }:
            continue

        charge_key = (
            charge_name.upper(),
            currency,
            round(total_amount, 2),
        )

        if charge_key in seen:
            continue

        seen.add(charge_key)

        charges.append(
            {
                "CHARGE_NAME": charge_name,
                "CURRENCY_TYPE": currency,
                "AMOUNT": total_amount,
            }
        )

    return charges


def extract_lmt_invoice_no(text):
    match = re.search(
        r"\bInvoice\s+No\.\s*:\s*([A-Z0-9\/-]+)",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).upper()

    return None

def extract_nhava_sheva_invoice_no(text):
    match = re.search(
        r"\bTax\s+Invoice\s+No\.?\s*:\s*([A-Z0-9\/-]+)",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).upper()

    return None


def extract_nhava_sheva_charges(text, tables):
    charges = []

    currency_map = {
        "₹": "INR",
        "$": "USD",
        "€": "EUR",
        "£": "GBP",
        "AED": "AED",
        "INR": "INR",
        "USD": "USD",
        "EUR": "EUR",
        "GBP": "GBP",
    }

    amount_header_pattern = re.compile(
        r"Amount\s+in\s+([₹$€£]|INR|USD|EUR|GBP)\b",
        re.IGNORECASE,
    )

    charge_line_pattern = re.compile(
        r"^\s*"
        r"(?P<code>[A-Z0-9]+)\s+"
        r"(?P<charge_name>.+?)\s+"
        r"(?P<qty>\d+(?:\.\d+)?)\s+"
        r"(?:(?P<tariff_currency>[$₹])\s*)?"
        r"(?P<tariff>[\d,]+\.\d+)\s+"
        r"(?P<ex_rate>[\d,]+\.\d+)\s+"
        r"(?P<amount>[\d,]+\.\d+)"
        r"\s*$",
        re.IGNORECASE,
    )

    currency = "INR"

    if isinstance(text, str):
        currency_match = amount_header_pattern.search(text)

        if currency_match:
            currency_value = currency_match.group(1).upper()
            currency = currency_map.get(
                currency_value,
                currency_value,
            )

    lines = text.splitlines()

    for line in lines:
        line = clean_text(line)

        if not line:
            continue

        if re.match(
            r"^(?:Sub\s+Total|CGST|SGST|IGST|Round\s+Off|Grand\s+Total|"
            r"State\s+Code|SAC\s+Code|Remarks|For\s+Nhava\s+Sheva)\b",
            line,
            re.IGNORECASE,
        ):
            continue

        match = charge_line_pattern.match(line)

        if not match:
            continue

        charge_name = clean_text(
            match.group("charge_name")
        )

        amount = clean_number(
            match.group("amount")
        )

        if not charge_name or amount is None:
            continue

        charges.append(
            {
                "CHARGE_NAME": charge_name,
                "CURRENCY_TYPE": currency,
                "AMOUNT": amount,
            }
        )

    table_charges = []

    for table in tables:
        if not isinstance(table, list):
            continue

        if not table:
            continue

        header = [
            clean_text(cell).upper()
            for cell in table[0]
            if cell is not None
        ]

        has_description = any(
            "DESCRIPTION" in cell
            for cell in header
        )

        has_amount = any(
            "AMOUNT" in cell
            for cell in header
        )

        if not has_description or not has_amount:
            continue

        description_index = None
        amount_index = None

        for index, cell in enumerate(header):
            if "DESCRIPTION" in cell:
                description_index = index

            if "AMOUNT" in cell:
                amount_index = index

        if description_index is None or amount_index is None:
            continue

        for row in table[1:]:
            if not isinstance(row, list):
                continue

            if len(row) <= max(
                description_index,
                amount_index,
            ):
                continue

            charge_name = clean_text(
                row[description_index]
            )

            amount_text = clean_text(
                row[amount_index]
            )

            if not charge_name or not amount_text:
                continue

            if re.match(
                r"^(?:Sub\s+Total|CGST|SGST|IGST|Round\s+Off|Grand\s+Total|Total)\b",
                charge_name,
                re.IGNORECASE,
            ):
                continue

            amount_match = re.search(
                r"(?<![A-Za-z])(?:\d{1,3}(?:,\d{2})*,\d{3}|\d+)(?:\.\d+)?",
                amount_text,
            )

            if not amount_match:
                continue

            amount = clean_number(
                amount_match.group(0)
            )

            if amount is None:
                continue

            table_charges.append(
                {
                    "CHARGE_NAME": charge_name,
                    "CURRENCY_TYPE": currency,
                    "AMOUNT": amount,
                }
            )

    if table_charges:
        return table_charges

    return charges

def extract_mundra_invoice_no(text):
    match = re.search(
        r"\bInvoice\s+No\.?\s*:\s*([A-Z0-9\/-]+)",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).upper()

    return None


def extract_mundra_charges(text, tables):
    charges = []

    currency_map = {
        "₹": "INR",
        "$": "USD",
        "€": "EUR",
        "£": "GBP",
        "AED": "AED",
        "INR": "INR",
        "USD": "USD",
        "EUR": "EUR",
        "GBP": "GBP",
    }

    amount_header_pattern = re.compile(
        r"Amount\s+in\s+([₹$€£]|INR|USD|EUR|GBP)\b",
        re.IGNORECASE,
    )

    charge_line_pattern = re.compile(
        r"^\s*"
        r"(?P<code>[A-Z0-9]+)\s+"
        r"(?P<charge_name>.+?)\s+"
        r"(?P<qty>\d+(?:\.\d+)?)\s+"
        r"(?:(?P<tariff_currency>[$₹])\s*)?"
        r"(?P<tariff>[\d,]+\.\d+)\s+"
        r"(?P<ex_rate>[\d,]+\.\d+)\s+"
        r"(?P<amount>[\d,]+\.\d+)"
        r"\s*$",
        re.IGNORECASE,
    )

    currency = "INR"

    if isinstance(text, str):
        currency_match = amount_header_pattern.search(text)

        if currency_match:
            currency_value = currency_match.group(1).upper()
            currency = currency_map.get(
                currency_value,
                currency_value,
            )

    lines = text.splitlines()

    for line in lines:
        line = clean_text(line)

        if not line:
            continue

        if re.match(
            r"^(?:Sub\s+Total|Central\s+GST|State\s+GST|CGST|SGST|"
            r"IGST|Round\s+Off|Grand\s+Total|State\s+Code|SAC|"
            r"Remarks|For\s+Mundra)\b",
            line,
            re.IGNORECASE,
        ):
            continue

        match = charge_line_pattern.match(line)

        if not match:
            continue

        charge_name = clean_text(
            match.group("charge_name")
        )

        amount = clean_number(
            match.group("amount")
        )

        if not charge_name or amount is None:
            continue

        charges.append(
            {
                "CHARGE_NAME": charge_name,
                "CURRENCY_TYPE": currency,
                "AMOUNT": amount,
            }
        )

    table_charges = []

    for table in tables:
        if not isinstance(table, list):
            continue

        if not table:
            continue

        header = [
            clean_text(cell).upper()
            for cell in table[0]
            if cell is not None
        ]

        has_description = any(
            "DESCRIPTION" in cell
            for cell in header
        )

        has_amount = any(
            "AMOUNT" in cell
            for cell in header
        )

        if not has_description or not has_amount:
            continue

        description_index = None
        amount_index = None

        for index, cell in enumerate(header):
            if "DESCRIPTION" in cell:
                description_index = index

            if "AMOUNT" in cell:
                amount_index = index

        if description_index is None or amount_index is None:
            continue

        for row in table[1:]:
            if not isinstance(row, list):
                continue

            if len(row) <= max(
                description_index,
                amount_index,
            ):
                continue

            charge_name = clean_text(
                row[description_index]
            )

            amount_text = clean_text(
                row[amount_index]
            )

            if not charge_name or not amount_text:
                continue

            if re.match(
                r"^(?:Sub\s+Total|Central\s+GST|State\s+GST|CGST|SGST|"
                r"IGST|Round\s+Off|Grand\s+Total|Total)\b",
                charge_name,
                re.IGNORECASE,
            ):
                continue

            amount_match = re.search(
                r"(?<![A-Za-z])(?:\d{1,3}(?:,\d{2})*,\d{3}|\d+)(?:\.\d+)?",
                amount_text,
            )

            if not amount_match:
                continue

            amount = clean_number(
                amount_match.group(0)
            )

            if amount is None:
                continue

            table_charges.append(
                {
                    "CHARGE_NAME": charge_name,
                    "CURRENCY_TYPE": currency,
                    "AMOUNT": amount,
                }
            )

    if table_charges:
        return table_charges

    return charges

def extract_msc_invoice_no(text):
    match = re.search(
        r"Client\s+no\s*:\s*Invoice\s+no\.?\s*:\s*Invoice\s+date\s*:\s*Due\s+date\s*:\s*"
        r"\s*\d+\s+([A-Z0-9][A-Z0-9\/-]*)",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).upper()

    match = re.search(
        r"\bInvoice\s+no\.?\s*:\s*\n\s*"
        r"\d+\s+([A-Z0-9][A-Z0-9\/-]*)",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).upper()

    return None


def extract_msc_charges(text, tables):
    charges = []

    def find_msc_charge_table():
        for table in tables:
            if not isinstance(table, list):
                continue

            for row_index, row in enumerate(table):
                if not isinstance(row, list):
                    continue

                row_text = " ".join(
                    clean_text(cell).replace("\n", " ")
                    for cell in row
                    if cell is not None
                ).upper()

                if (
                    "CHARGE" in row_text
                    and "HSN CODE" in row_text
                    and "TOTAL INR" in row_text
                    and "SGST" in row_text
                    and "CGST" in row_text
                ):
                    return table, row_index

        return None, None

    def split_cell_lines(value):
        if value is None:
            return []

        value = str(value)
        value = value.replace("\r", "\n")

        lines = []

        for line in value.split("\n"):
            line = re.sub(r"[ \t]+", " ", line).strip()

            if line:
                lines.append(line)

        return lines

    def merge_charge_name_lines(lines):
        merged = []

        continuation_prefixes = (
            "AND ",
            "OR ",
            "OF ",
            "FOR ",
            "WITH ",
            "INCLUDING ",
            "EXCLUDING ",
        )

        for line in lines:
            line = clean_text(line)

            if not line:
                continue

            if merged and line.upper().startswith(
                continuation_prefixes
            ):
                merged[-1] = (
                    merged[-1] + " " + line
                )
            else:
                merged.append(line)

        return merged

    table, header_row_index = find_msc_charge_table()

    if table is not None:
        header_row = table[header_row_index]

        if isinstance(header_row, list):
            charge_index = None
            currency_index = None
            total_inr_index = None

            for index, cell in enumerate(header_row):
                cell_text = clean_text(cell).upper()

                if (
                    charge_index is None
                    and "CHARGE" in cell_text
                ):
                    charge_index = index

                if (
                    currency_index is None
                    and (
                        "CURR." in cell_text
                        or "CURR" in cell_text
                    )
                    and "TOTAL" not in cell_text
                ):
                    currency_index = index

                if (
                    total_inr_index is None
                    and "TOTAL INR" in cell_text
                ):
                    total_inr_index = index

            if (
                charge_index is not None
                and currency_index is not None
                and total_inr_index is not None
            ):
                data_rows = table[
                    header_row_index + 1:
                ]

                for row in data_rows:
                    if not isinstance(row, list):
                        continue

                    if len(row) <= max(
                        charge_index,
                        currency_index,
                        total_inr_index,
                    ):
                        continue

                    charge_lines = split_cell_lines(
                        row[charge_index]
                    )

                    currency_lines = split_cell_lines(
                        row[currency_index]
                    )

                    total_inr_lines = split_cell_lines(
                        row[total_inr_index]
                    )

                    if not charge_lines:
                        continue

                    if not currency_lines:
                        continue

                    if not total_inr_lines:
                        continue

                    charge_lines = merge_charge_name_lines(
                        charge_lines
                    )

                    if len(charge_lines) != len(
                        currency_lines
                    ):
                        continue

                    if len(charge_lines) != len(
                        total_inr_lines
                    ):
                        continue

                    for charge_name, currency_text, amount_text in zip(
                        charge_lines,
                        currency_lines,
                        total_inr_lines,
                    ):
                        charge_name = clean_text(
                            charge_name
                        )

                        currency_match = re.search(
                            r"\b(INR|USD|EUR|GBP)\b",
                            currency_text,
                            re.IGNORECASE,
                        )

                        if not currency_match:
                            continue

                        currency = currency_match.group(
                            1
                        ).upper()

                        amount_match = re.search(
                            r"(?<![A-Za-z])"
                            r"(?:\d{1,3}(?:,\d{2})*,\d{3}|\d+)"
                            r"(?:\.\d+)?",
                            amount_text,
                        )

                        if not amount_match:
                            continue

                        amount = clean_number(
                            amount_match.group(0)
                        )

                        if amount is None:
                            continue

                        if not charge_name:
                            continue

                        if re.match(
                            r"^(?:TAXABLE VALUE|TOTAL GST|TOTAL INVOICE|TOTAL|GRAND TOTAL)\b",
                            charge_name,
                            re.IGNORECASE,
                        ):
                            continue

                        charges.append(
                            {
                                "CHARGE_NAME": charge_name,
                                "CURRENCY_TYPE": currency,
                                "AMOUNT": amount,
                            }
                        )

        if charges:
            return charges

    charge_pattern = re.compile(
        r"^(?P<charge_name>.+?)\s+"
        r"\d{6}\s+"
        r"\d+(?:\.\d+)?\s+x\s+"
        r"[\d,]+(?:\.\d+)?\s+"
        r"(?P<currency>INR|USD|EUR|GBP)\s+"
        r"(?P<total_curr>[\d,]+(?:\.\d+)?)\s+"
        r"(?P<roe>[\d,]+(?:\.\d+)?)\s+"
        r"(?P<total_inr>[\d,]+(?:\.\d+)?)"
        r"(?:\s+.*)?$",
        re.IGNORECASE,
    )

    lines = []

    for line in text.splitlines():
        line = clean_text(line)

        if line:
            lines.append(line)

    for line in lines:
        match = charge_pattern.match(line)

        if not match:
            continue

        charge_name = clean_text(
            match.group("charge_name")
        )

        currency = match.group(
            "currency"
        ).upper()

        amount = clean_number(
            match.group("total_inr")
        )

        if not charge_name or amount is None:
            continue

        if re.match(
            r"^(?:TAXABLE VALUE|TOTAL GST|TOTAL INVOICE|TOTAL|GRAND TOTAL)\b",
            charge_name,
            re.IGNORECASE,
        ):
            continue

        charges.append(
            {
                "CHARGE_NAME": charge_name,
                "CURRENCY_TYPE": currency,
                "AMOUNT": amount,
            }
        )

    unique_charges = []
    seen = set()

    for charge in charges:
        key = (
            charge["CHARGE_NAME"].upper(),
            charge["CURRENCY_TYPE"],
            round(charge["AMOUNT"], 2),
        )

        if key in seen:
            continue

        seen.add(key)
        unique_charges.append(charge)

    return unique_charges

def extract_nhava_sheva_freeport_invoice_no(text):
    match = re.search(
        r"\bInvoice\s+No\.?\s*[:#]?\s*([A-Z0-9\/-]+)",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).upper()

    return None


def extract_nhava_sheva_freeport_charges(text, tables):
    charges = []
    seen = set()

    for table_text in tables:
        if not table_text:
            continue

        rows = [
            clean_text(row)
            for row in str(table_text).splitlines()
            if clean_text(row)
        ]

        if not rows:
            continue

        header_index = None
        description_index = None
        currency_index = None
        usd_index = None
        inr_index = None

        for index, row in enumerate(rows):
            cells = [
                clean_text(cell)
                for cell in row.split("|")
            ]

            normalized = [
                cell.upper()
                for cell in cells
            ]

            for i, cell in enumerate(normalized):
                if "DESCRIPTION OF GOODS" in cell or "DESCRIPTION OF GOODS/SERVICE" in cell:
                    description_index = i

                if cell == "CURRENCY":
                    currency_index = i

                if "AMOUNT (USD)" in cell:
                    usd_index = i

                if "AMOUNT (INR)" in cell:
                    inr_index = i

            if (
                description_index is not None
                and currency_index is not None
                and (
                    usd_index is not None
                    or inr_index is not None
                )
            ):
                header_index = index
                break

        if header_index is None:
            continue

        for row in rows[header_index + 1:]:
            cells = [
                clean_text(cell)
                for cell in row.split("|")
            ]

            if len(cells) <= max(
                description_index,
                currency_index,
                usd_index if usd_index is not None else 0,
                inr_index if inr_index is not None else 0,
            ):
                continue

            charge_name = cells[description_index].strip()
            currency = cells[currency_index].upper().strip()

            if not charge_name:
                continue

            if re.search(
                r"\b(?:TOTAL|SUBTOTAL|TAXABLE|CGST|SGST|IGST|GRAND TOTAL)\b",
                charge_name,
                re.IGNORECASE,
            ):
                continue

            amount = None

            if currency == "USD" and usd_index is not None:
                amount = clean_number(cells[usd_index])

            elif currency == "INR" and inr_index is not None:
                amount = clean_number(cells[inr_index])

            elif usd_index is not None:
                usd_amount = clean_number(cells[usd_index])

                if usd_amount is not None and usd_amount != 0:
                    currency = "USD"
                    amount = usd_amount

            if amount is None and inr_index is not None:
                inr_amount = clean_number(cells[inr_index])

                if inr_amount is not None and inr_amount != 0:
                    currency = "INR"
                    amount = inr_amount

            if amount is None or amount == 0:
                continue

            charge_key = (
                charge_name.upper(),
                currency,
                round(amount, 2),
            )

            if charge_key in seen:
                continue

            seen.add(charge_key)

            charges.append(
                {
                    "CHARGE_NAME": charge_name,
                    "CURRENCY_TYPE": currency,
                    "AMOUNT": amount,
                }
            )

    return charges

def extract_oasis_shipping_invoice_no(text):
    match = re.search(
        r"\bInvoice\s+No\.?\s*[:#]?\s*([A-Z0-9\/-]+)",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).upper()
    return None


def extract_oasis_shipping_invoice_no(text):
    match = re.search(
        r"\bINVOICE\s+NO\s*:\s*([A-Z0-9\/-]+)",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).upper()

    return None


def extract_oasis_shipping_invoice_no(text):
    match = re.search(
        r"\bTO\s+INVOICE\s+NO\s*[:#]?\s*([A-Z0-9\/-]+)",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).upper()

    match = re.search(
        r"\bINVOICE\s+NO\s*[:#]?\s*([A-Z0-9\/-]+)",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).upper()

    return None


def extract_oasis_shipping_charges(text, tables):
    charges = []

    lines = [
        clean_text(line)
        for line in str(text).splitlines()
        if clean_text(line)
    ]

    current_charge = None

    for line in lines:
        if not line:
            continue

        if re.match(r"^\d{6}\s+", line):
            if current_charge is not None:
                charges.append(current_charge)

            match = re.match(
                r"^\d{6}\s+(.+?)\s+("
                + CURRENCY_PATTERN
                + r")\s+"
                r"([0-9,]+\.[0-9]+|[0-9]+(?:\.[0-9]+)?)\s+"
                r"(.+)$",
                line,
                re.IGNORECASE,
            )

            if not match:
                current_charge = None
                continue

            charge_name = clean_text(match.group(1))
            currency = match.group(2).upper()
            remaining = clean_text(match.group(4))

            if re.search(
                r"\b(?:CGST|SGST|IGST)\b",
                charge_name,
                re.IGNORECASE,
            ):
                current_charge = None
                continue

            if re.search(
                r"\b(?:Tax\s+Breakup|Tax\s+Code|GST\s+Amt|Taxable\s+Amt)\b",
                charge_name,
                re.IGNORECASE,
            ):
                current_charge = None
                continue

            numeric_values = re.findall(
                r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?",
                remaining,
            )

            if len(numeric_values) < 4:
                current_charge = None
                continue

            amount = clean_number(numeric_values[-4])

            current_charge = {
                "CHARGE_NAME": charge_name,
                "CURRENCY_TYPE": currency,
                "AMOUNT": amount,
            }

            continue

        if current_charge is not None:
            if re.match(
                r"^(?:Total|Tax Breakup|CGST|SGST|IGST|In Words|Notes|PAN|"
                r"Payments accepted|Beneficiary|A/C|Please send|THIS IS|"
                r"As Agents|Signed by|Register Feedback)",
                line,
                re.IGNORECASE,
            ):
                charges.append(current_charge)
                current_charge = None
                continue

            if re.match(
                r"^\d{6}\s+",
                line,
                re.IGNORECASE,
            ):
                continue

            if re.match(
                r"^(?:SAC Code|Charge Desc|Curr\.|Ex\.Rate|Basis|Qty|Rate|"
                r"Forgn\. Amt|Taxable|GST)",
                line,
                re.IGNORECASE,
            ):
                continue

            if re.search(
                r"\b(?:Collection BASIS|Surcharge|Charges|Mumbai)\b",
                line,
                re.IGNORECASE,
            ):
                current_charge["CHARGE_NAME"] = clean_text(
                    current_charge["CHARGE_NAME"] + " " + line
                )

    if current_charge is not None:
        charges.append(current_charge)

    cleaned_charges = []
    seen = set()

    for charge in charges:
        charge_name = clean_text(charge["CHARGE_NAME"])
        currency = clean_text(charge["CURRENCY_TYPE"]).upper()
        amount = charge["AMOUNT"]

        if not charge_name:
            continue

        if amount is None:
            continue

        if amount == 0:
            continue

        if re.search(
            r"\b(?:TOTAL|SUBTOTAL|TAXABLE|CGST|SGST|IGST|GRAND TOTAL|"
            r"TAX BREAKUP|TAX CODE|GST AMT)\b",
            charge_name,
            re.IGNORECASE,
        ):
            continue

        charge_key = (
            charge_name.upper(),
            currency,
            round(float(amount), 2),
        )

        if charge_key in seen:
            continue

        seen.add(charge_key)

        cleaned_charges.append(
            {
                "CHARGE_NAME": charge_name,
                "CURRENCY_TYPE": currency,
                "AMOUNT": round(float(amount), 2),
            }
        )

    return cleaned_charges

def extract_ocean_generation_shipping_invoice_no(text):
    lines = str(text).splitlines()

    has_tax_invoice = any(
        re.search(r"\bTAX\s+INVOICE\b", line, re.IGNORECASE)
        for line in lines
    )

    if not has_tax_invoice:
        return None

    for i, line in enumerate(lines):
        if re.search(r"\bInvoice\s+No\b", line, re.IGNORECASE):
            same_line = re.search(
                r"\bInvoice\s+No\s*:?\s*([A-Z0-9\/-]+)",
                line,
                re.IGNORECASE,
            )

            if same_line:
                value = same_line.group(1).upper()

                if value not in {"REFERENCE", "NO"}:
                    return value

            for next_line in lines[i + 1:i + 5]:
                value_match = re.search(
                    r":\s*([A-Z0-9\/-]+)",
                    next_line,
                    re.IGNORECASE,
                )

                if value_match:
                    value = value_match.group(1).upper()

                    if value not in {"REFERENCE", "NO"}:
                        return value

                value_match = re.search(
                    r"\b([A-Z]{2,}[A-Z0-9\/-]*\d[A-Z0-9\/-]*)\b",
                    next_line,
                    re.IGNORECASE,
                )

                if value_match:
                    value = value_match.group(1).upper()

                    if value not in {"REFERENCE", "NO"}:
                        return value

    return None


def extract_ocean_generation_shipping_charges(text, tables):
    charges = []
    seen = set()

    currency_pattern = r"(?:USD|INR|EUR|GBP|AED|SGD|CNY|JPY)"

    charge_pattern = re.compile(
        r"^\s*\d+\s+"
        r"(?P<charge_name>.+?)\s+"
        r"\d{6}\s+"
        r"\d+(?:\.\d+)?\s+"
        r"(?P<currency>" + currency_pattern + r")\s+"
        r"(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"\d+(?:\.\d+)?\s+"
        r"[\d,]+(?:\.\d+)?"
        r"\s*$",
        re.IGNORECASE,
    )

    for line in str(text).splitlines():
        line = line.strip()

        if not line:
            continue

        match = charge_pattern.match(line)

        if not match:
            continue

        charge_name = match.group("charge_name").strip()
        currency = match.group("currency").upper().strip()
        amount = float(match.group("amount").replace(",", ""))

        if not charge_name:
            continue

        if re.search(
            r"\b(?:TOTAL|SUBTOTAL|TAXABLE|CGST|SGST|IGST|GRAND\s+TOTAL)\b",
            charge_name,
            re.IGNORECASE,
        ):
            continue

        charge_key = (
            charge_name.upper(),
            currency,
            round(amount, 2),
        )

        if charge_key in seen:
            continue

        seen.add(charge_key)

        charges.append(
            {
                "CHARGE_NAME": charge_name,
                "CURRENCY_TYPE": currency,
                "AMOUNT": amount,
            }
        )

    return charges

def extract_one_invoice_no(text):
    match = re.search(
        r"\bInvoice\s+No\b.*?\b(IN[0-9]{11,})\b",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return match.group(1).upper()
    return None


def extract_one_charges(text, tables):
    charges = []
    seen = set()

    currency_pattern = r"(?:USD|INR|EUR|GBP|AED|SGD|CNY|JPY)"

    charge_pattern = re.compile(
        r"^\s*\d+\s+"
        r"(?P<charge_name>.+?)\s+"
        r"\d{6}\s+"
        r"\S+\s+"
        r"[\d,]+\.\d+\s+"
        r"\d+(?:\.\d+)?\s+"
        r"(?P<currency>" + currency_pattern + r")\s+"
        r"(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"[\d.]+\s+"
        r"[\d,]+(?:\.\d+)?\s+"
        r"[\d,]+(?:\.\d+)?"
        r"(?:\s+[\d.]+\s+[\d,]+(?:\.\d+)?){0,2}"
        r"\s*$",
        re.IGNORECASE,
    )

    for line in str(text).splitlines():
        line = line.strip()

        if not line:
            continue

        match = charge_pattern.match(line)

        if not match:
            continue

        charge_name = match.group("charge_name").strip()
        currency = match.group("currency").upper().strip()
        amount = float(match.group("amount").replace(",", ""))

        if not charge_name:
            continue

        if re.search(
            r"\b(?:TOTAL|SUBTOTAL|TAXABLE|CGST|SGST|IGST|GRAND\s+TOTAL)\b",
            charge_name,
            re.IGNORECASE,
        ):
            continue

        charge_key = (
            charge_name.upper(),
            currency,
            round(amount, 2),
        )

        if charge_key in seen:
            continue

        seen.add(charge_key)

        charges.append(
            {
                "CHARGE_NAME": charge_name,
                "CURRENCY_TYPE": currency,
                "AMOUNT": amount,
            }
        )

    return charges

def extract_oocl_invoice_no(text):
    match = re.search(
        r"\bINVOICE\s+NO\.?\s*:\s*([0-9]+\s*[A-Z0-9]+)\b",
        text,
        re.IGNORECASE,
    )

    if match:
        return re.sub(r"\s+", " ", match.group(1)).upper()

    return None


def extract_oocl_charges(text, tables):
    charges = []
    seen = set()

    currency_pattern = r"(?:USD|INR|EUR|GBP|AED|SGD|CNY|JPY)"

    charge_pattern = re.compile(
        r"^\s*"
        r"(?P<charge_name>.+?)\s+"
        r"(?P<basis>\d+(?:\.\d+)?)\s+"
        r"(?P<rate>[\d,]+(?:\.\d+)?)\s+"
        r"(?P<currency>" + currency_pattern + r")\s+"
        r"(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"[\d.]+\s+"
        r"(?:YES|NO)"
        r"\s+"
        r"[\d,]+(?:\.\d+)?"
        r"\s*$",
        re.IGNORECASE,
    )

    for line in str(text).splitlines():
        line = line.strip()

        if not line:
            continue

        match = charge_pattern.match(line)

        if not match:
            continue

        charge_name = match.group("charge_name").strip()
        currency = match.group("currency").upper().strip()
        amount = float(match.group("amount").replace(",", ""))

        if not charge_name:
            continue

        if re.search(
            r"\b(?:SUB[- ]?TOTAL|TOTAL|CGST|SGST|IGST|UTGST|AMOUNT\s+DUE|GRAND\s+TOTAL)\b",
            charge_name,
            re.IGNORECASE,
        ):
            continue

        charge_key = (
            charge_name.upper(),
            currency,
            round(amount, 2),
        )

        if charge_key in seen:
            continue

        seen.add(charge_key)

        charges.append(
            {
                "CHARGE_NAME": charge_name,
                "CURRENCY_TYPE": currency,
                "AMOUNT": amount,
            }
        )

    return charges

def extract_pil_invoice_no(text):
    match = re.search(
        r"\bInvoice\s+No\s*:\s*([A-Z0-9\/-]+)",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).upper()

    return None


def extract_pil_charges(text, tables):
    charges = []
    seen = set()

    currency_pattern = r"(?:USD|INR|EUR|GBP|AED|SGD|CNY|JPY)"

    charge_pattern = re.compile(
        r"^\s*"
        r"\d+"
        r"(?P<charge_name>.+?)\s+"
        r"\d{6}\s+"
        r"\d+(?:\.\d+)?\s+"
        r"\S+\s+"
        r"\S+\s+"
        r"(?P<currency>" + currency_pattern + r")\s+"
        r"(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r"[\d,]+(?:\.\d+)?\s+"
        r"[\d,]+(?:\.\d+)?\s+"
        r"[\d,]+(?:\.\d+)?"
        r"\s*$",
        re.IGNORECASE,
    )

    for line in str(text).splitlines():
        line = line.strip()

        if not line:
            continue

        match = charge_pattern.match(line)

        if not match:
            continue

        charge_name = match.group("charge_name").strip()
        currency = match.group("currency").upper().strip()
        amount = float(match.group("amount").replace(",", ""))

        if not charge_name:
            continue

        if re.search(
            r"\b(?:TOTAL|SUBTOTAL|TAXABLE|CGST|SGST|IGST|UTGST|GRAND\s+TOTAL)\b",
            charge_name,
            re.IGNORECASE,
        ):
            continue

        charge_key = (
            charge_name.upper(),
            currency,
            round(amount, 2),
        )

        if charge_key in seen:
            continue

        seen.add(charge_key)

        charges.append(
            {
                "CHARGE_NAME": charge_name,
                "CURRENCY_TYPE": currency,
                "AMOUNT": amount,
            }
        )

    return charges

def extract_promise_shipping_line_invoice_no(text):
    match = re.search(
        r"\bInv\s*#\s*([A-Z0-9\/-]+)",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).upper()

    return None


def extract_promise_shipping_line_charges(text, tables):
    charges = []
    seen = set()

    currency_pattern = r"(?:USD|INR|EUR|GBP|AED|SGD|CNY|JPY)"

    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in str(text).splitlines()
        if line.strip()
    ]

    ignored_lines = {
        "RS (INR) (%) (%) (%)",
        "CHARGES SAC QTY UNITS CURR RATE CGST SGST IGST INR",
        "CHARGES SAC QTY UNITS CURR RATE CGST SGST IGST",
    }

    charge_start_pattern = re.compile(
        r"^(?P<charge_name>.+?)\s+"
        r"\d{6}\s+"
        r"\d+(?:\.\d+)?\s+"
        r"[A-Z0-9]+\s*"
        r"(?P<currency>" + currency_pattern + r")\s+"
        r"(?P<values>.+)$",
        re.IGNORECASE,
    )

    i = 0

    while i < len(lines):
        line = lines[i]

        if line.upper() in ignored_lines:
            i += 1
            continue

        if re.search(
            r"^(?:ROUND\s+OFF|TOTAL|RUPEES|CONTAINER\s+DETAILS|REMARKS|BANK\s+DETAILS|FAVOURING|IFSC\s+CODE|BANK\s+ADDRESS|AUTHORISED\s+SIGNATORY)",
            line,
            re.IGNORECASE,
        ):
            i += 1
            continue

        combined_line = line
        consumed = 1

        if (
            line.upper() == "TERMINAL HANDLING CHARGES"
            and i + 1 < len(lines)
        ):
            next_line = lines[i + 1]

            if re.match(
                r"^\d{6}\s+\d+(?:\.\d+)?\s+[A-Z0-9]+\s*"
                + currency_pattern
                + r"\b",
                next_line,
                re.IGNORECASE,
            ):
                combined_line = line + " " + next_line
                consumed = 2

                if (
                    i + 2 < len(lines)
                    and lines[i + 2].upper() == "DESTINATION"
                ):
                    combined_line += " DESTINATION"
                    consumed = 3

        match = charge_start_pattern.match(combined_line)

        if not match:
            i += consumed
            continue

        charge_name = match.group("charge_name").strip()
        currency = match.group("currency").upper().strip()
        values_text = match.group("values").strip()

        if (
            i + consumed < len(lines)
            and lines[i + consumed].upper() == "DESTINATION"
        ):
            charge_name = charge_name + " DESTINATION"
            consumed += 1

        if not charge_name:
            i += consumed
            continue

        if re.search(
            r"^(?:Rs\s*\(INR\)|CHARGES|SAC|QTY|UNITS|CURR|RATE|CGST|SGST|IGST|INR)$",
            charge_name,
            re.IGNORECASE,
        ):
            i += consumed
            continue

        if re.search(
            r"\b(?:TOTAL|SUBTOTAL|TAXABLE|CGST|SGST|IGST|GRAND\s+TOTAL)\b",
            charge_name,
            re.IGNORECASE,
        ):
            i += consumed
            continue

        numeric_values = re.findall(
            r"-?\d[\d,]*(?:\.\d+)?",
            values_text,
        )

        if not numeric_values:
            i += consumed
            continue

        amount = float(
            numeric_values[-1].replace(",", "")
        )

        charge_key = (
            charge_name.upper(),
            "INR",
            round(amount, 2),
        )

        if charge_key not in seen:
            seen.add(charge_key)

            charges.append(
                {
                    "CHARGE_NAME": charge_name,
                    "CURRENCY_TYPE": "INR",
                    "AMOUNT": amount,
                }
            )

        i += consumed

    return charges

def extract_psa_invoice_no(text):
    match = re.search(
        r"\bINVOICE\s+NUMBER\s+[-\s]*([A-Z0-9\/-]+)",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).upper()

    return None


def extract_psa_charges(text, tables):
    charges = []
    seen = set()

    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in str(text).splitlines()
        if line.strip()
    ]

    service_lines = []

    service_pattern = re.compile(
        r"^(?P<description>.+?)\s+"
        r"(?P<sac>\d{6})\s+"
        r"(?P<qty>\d+(?:\.\d+)?)\s+"
        r"(?P<uom>[A-Z]+)\s+"
        r"(?P<rate>[\d,]+\.\d+)\s+"
        r"(?P<amount>[\d,]+\.\d+)$",
        re.IGNORECASE,
    )

    current_description = None

    for line in lines:
        if re.search(
            r"^(?:SERVICE|SAC|QTY|UOM|RATE|AMOUNT\(INR\)|INVOICE|INVOICE\s+DETAILS|TOTAL\s+AMOUNT|ADD\s*:|ROUND-OFF|TOTAL|FOR\s+BHARAT|REGISTERED\s+OFFICE|PRINTED\s+BY)",
            line,
            re.IGNORECASE,
        ):
            continue

        match = service_pattern.match(line)

        if match:
            description = match.group("description").strip()

            if current_description:
                description = current_description + " " + description

            amount = float(
                match.group("amount").replace(",", "")
            )

            service_lines.append(
                {
                    "CHARGE_NAME": description,
                    "CURRENCY_TYPE": "INR",
                    "AMOUNT": amount,
                }
            )

            current_description = None
            continue

        if re.search(
            r"^STEVEDORING/\s*TERMINAL\s+HANDLING\s+CHARGES",
            line,
            re.IGNORECASE,
        ):
            current_description = line
            continue

        if current_description:
            current_description = (
                current_description + " " + line
            )

    for charge in service_lines:
        charge_name = charge["CHARGE_NAME"].strip()
        amount = charge["AMOUNT"]

        if not charge_name:
            continue

        charge_key = (
            charge_name.upper(),
            "INR",
            round(amount, 2),
        )

        if charge_key in seen:
            continue

        seen.add(charge_key)

        charges.append(
            {
                "CHARGE_NAME": charge_name,
                "CURRENCY_TYPE": "INR",
                "AMOUNT": amount,
            }
        )

    return charges

def extract_rcl_invoice_no(text):
    match = re.search(
        r"\bInvoice\s+No\.\s*:\s*([A-Z0-9\/-]+)",
        text,
        re.IGNORECASE,
    )

    if match:
        invoice_no = match.group(1).upper().strip()

        if invoice_no not in {"-", "--", "N/A", "NA"}:
            return invoice_no

    return None


def extract_rcl_charges(text, tables):
    charges = []
    seen = set()

    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in str(text).splitlines()
        if line.strip()
    ]

    currency_pattern = r"(?:USD|INR|EUR|GBP|AED|SGD|CNY|JPY)"

    charge_pattern = re.compile(
        r"^(?P<row>\d+)\s+"
        r"(?P<charge_name>.+?)\s+"
        r"(?P<size>\d+\s+[A-Z]+|0\s+\*+)\s+"
        r"(?P<sac>\d{6})\s+"
        r"(?P<qty>\d+(?:\.\d+)?)\s+"
        r"(?P<currency>" + currency_pattern + r")\s+"
        r"(?P<rate>[\d,]+(?:\.\d+)?)\s+"
        r"(?P<amount>[\d,]+(?:\.\d+)?)\s+"
        r".*$",
        re.IGNORECASE,
    )

    continuation_pattern = re.compile(
        r"^(?:"
        r"FIFO\s+FCL\d+"
        r"|FEE.*"
        r"|CHARGE.*"
        r"|RECOVERY.*"
        r"|HANDLING.*"
        r"|HAULAGE.*"
        r"|SURCH.*"
        r"|SURRENDER.*"
        r"|FACILITATION.*"
        r"|USER\s+CHARGES.*"
        r")$",
        re.IGNORECASE,
    )

    for i, line in enumerate(lines):
        match = charge_pattern.match(line)

        if not match:
            continue

        charge_name = match.group("charge_name").strip()
        currency = match.group("currency").upper()
        amount = float(match.group("amount").replace(",", ""))

        if i + 1 < len(lines):
            next_line = lines[i + 1]

            if (
                not re.match(
                    r"^\d+\s+\d{5}-",
                    next_line,
                    re.IGNORECASE,
                )
                and continuation_pattern.match(next_line)
            ):
                charge_name = charge_name + " " + next_line

        charge_name = re.sub(
            r"\s+",
            " ",
            charge_name,
        ).strip()

        if not charge_name:
            continue

        if re.search(
            r"\b(?:TOTAL|SUBTOTAL|CGST|SGST|IGST|GRAND\s+TOTAL)\b",
            charge_name,
            re.IGNORECASE,
        ):
            continue

        charge_key = (
            charge_name.upper(),
            currency,
            round(amount, 2),
        )

        if charge_key in seen:
            continue

        seen.add(charge_key)

        charges.append(
            {
                "CHARGE_NAME": charge_name,
                "CURRENCY_TYPE": currency,
                "AMOUNT": amount,
            }
        )

    return charges

def extract_s_j_logistics_invoice_no(text):
    match = re.search(
        r"\bInvoice\s+No\s*:\s*([A-Z0-9\/-]+)",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).upper()
    return None


def extract_s_j_logistics_charges(text, tables):
    charges = []
    seen = set()

    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in str(text).splitlines()
        if line.strip()
    ]

    invoice_currency = None

    currency_match = re.search(
        r"\bInvoice\s+Currency\s*:\s*([A-Z]{3})",
        text,
        re.IGNORECASE,
    )

    if currency_match:
        invoice_currency = currency_match.group(1).upper()

    if not invoice_currency:
        currency_match = re.search(
            r"\bInvoice\s+Currency\s*[-:]?\s*([A-Z]{3})",
            text,
            re.IGNORECASE,
        )
        if currency_match:
            invoice_currency = currency_match.group(1).upper()

    charge_pattern = re.compile(
        r"^\s*(\d+)\s+"
        r"(?P<charge_name>.+?)\s+"
        r"(?P<sac>\d{6})\s+"
        r"(?:(?P<source_currency>USD|INR|EUR|GBP|AED|SGD|CNY|JPY)\s+)?"
        r"(?P<rate>[\d,]+(?:\.\d+)?)\s+"
        r"(?P<qty>\d+(?:\.\d+)?)\s+"
        r"(?P<rest>.+)$",
        re.IGNORECASE,
    )

    for line in lines:
        match = charge_pattern.match(line)

        if not match:
            continue

        charge_name = match.group("charge_name").strip()
        source_currency = match.group("source_currency")

        if source_currency:
            source_currency = source_currency.upper()
        else:
            source_currency = invoice_currency

        rest = match.group("rest").strip()

        numeric_values = re.findall(
            r"\d[\d,]*(?:\.\d+)?",
            rest,
        )

        if not numeric_values:
            continue

        total_amount = float(
            numeric_values[-1].replace(",", "")
        )

        if not charge_name:
            continue

        if re.search(
            r"\b(?:TOTAL|SUBTOTAL|CGST|SGST|IGST|GRAND\s+TOTAL)\b",
            charge_name,
            re.IGNORECASE,
        ):
            continue

        if not source_currency:
            continue

        charge_key = (
            charge_name.upper(),
            source_currency,
            round(total_amount, 2),
        )

        if charge_key in seen:
            continue

        seen.add(charge_key)

        charges.append(
            {
                "CHARGE_NAME": charge_name,
                "CURRENCY_TYPE": source_currency,
                "AMOUNT": total_amount,
            }
        )

    return charges

def extract_sci_invoice_no(text):
    match = re.search(
        r"\bInvoice\s+No\s*:\s*([A-Z0-9\/-]+)",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).upper()
    return None


def extract_sci_charges(text, tables):
    charges = []
    seen = set()

    for table in tables:
        if not table:
            continue

        if isinstance(table, list):
            rows = table
        else:
            rows = str(table).splitlines()

        for row in rows:
            if isinstance(row, (list, tuple)):
                cells = [str(cell or "").strip() for cell in row]
            else:
                cells = [
                    part.strip()
                    for part in str(row).split("|")
                ]

            if len(cells) < 11:
                continue

            description = cells[0]
            currency = cells[1].upper()
            total_amount = cells[10]

            if not description:
                continue

            if description.upper() in {
                "DESCRIPTION",
                "TOTAL TAXABLE AMOUNT INR",
                "TOTAL TAX AMOUNT INR",
                "TOTAL INVOICE AMOUNT INR",
            }:
                continue

            if not re.fullmatch(
                r"(?:USD|INR|EUR|GBP|AED|SGD|CNY|JPY)",
                currency,
                re.IGNORECASE,
            ):
                continue

            if not re.search(r"\d{6}", description):
                continue

            charge_name = re.sub(
                r"\s*HSN/SAC\s*:\s*\d{6}",
                "",
                description,
                flags=re.IGNORECASE,
            )

            charge_name = re.sub(
                r"\s+",
                " ",
                charge_name,
            ).strip()

            if not charge_name:
                continue

            amount_match = re.search(
                r"[\d,]+(?:\.\d+)?",
                total_amount,
            )

            if not amount_match:
                continue

            amount = float(
                amount_match.group(0).replace(",", "")
            )

            charge_key = (
                charge_name.upper(),
                currency,
                round(amount, 2),
            )

            if charge_key in seen:
                continue

            seen.add(charge_key)

            charges.append(
                {
                    "CHARGE_NAME": charge_name,
                    "CURRENCY_TYPE": currency,
                    "AMOUNT": amount,
                }
            )

    return charges    

def move_to_unidentified(pdf_path):
    UNIDENTIFIED_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = UNIDENTIFIED_DIR / pdf_path.name

    if destination.exists():
        stem = pdf_path.stem
        suffix = pdf_path.suffix
        counter = 1

        while destination.exists():
            destination = (
                UNIDENTIFIED_DIR
                / f"{stem}_{counter}{suffix}"
            )
            counter += 1

    shutil.move(
        str(pdf_path),
        str(destination),
    )

    return destination

CHARGE_TEMPLATES = {
    "Maersk_Only": extract_maersk_charges,
    "CMA CGM": extract_cma_cgm_charges,
    "Hapag-Lloyd": extract_hapag_lloyd_charges,
    "HMM": extract_hmm_charges,
    "Hub and Links Logistics": extract_hub_and_links_charges,
    "J M Baxi": extract_jm_baxi_charges,
    "LMT": extract_lmt_charges,
    "Nhava Sheva": extract_nhava_sheva_charges,
    "Mundra": extract_mundra_charges,
    "MSC": extract_msc_charges,
    "Nhava Sheva Freeport Terminal": extract_nhava_sheva_freeport_charges,
    "Oasis Shipping": extract_oasis_shipping_charges,
    "Ocean Generation Shipping":extract_ocean_generation_shipping_charges,
    "ONE": extract_one_charges,
    "OOCL": extract_oocl_charges,
    "PIL": extract_pil_charges,
    "Promise Shipping Line": extract_promise_shipping_line_charges,
    "PSA": extract_psa_charges,
    "RCL": extract_rcl_charges,
    "S J Logistics":extract_s_j_logistics_charges,
    "SCI":extract_sci_charges , 
    
}

INVOICE_TEMPLATES = {
    "Maersk_Only": extract_maersk_invoice_no,
    "CMA CGM": extract_cma_cgm_invoice_no,
    "Hapag-Lloyd": extract_hapag_lloyd_invoice_no,
    "HMM": extract_hmm_invoice_no,
    "Hub and Links Logistics": extract_hub_and_links_invoice_no,
    "J M Baxi": extract_jm_baxi_invoice_no,
    "LMT": extract_lmt_invoice_no,
    "Nhava Sheva": extract_nhava_sheva_invoice_no,
    "Mundra": extract_mundra_invoice_no,
    "MSC": extract_msc_invoice_no,
    "Nhava Sheva Freeport Terminal": extract_nhava_sheva_freeport_invoice_no,
    "Oasis Shipping": extract_oasis_shipping_invoice_no,
    "Ocean Generation Shipping":extract_ocean_generation_shipping_invoice_no,
    "ONE": extract_one_invoice_no,
    "OOCL": extract_oocl_invoice_no,
    "PIL": extract_pil_invoice_no,
    "Promise Shipping Line": extract_promise_shipping_line_invoice_no,
    "PSA": extract_psa_invoice_no,
    "RCL":extract_rcl_invoice_no,
    "S J Logistics":extract_s_j_logistics_invoice_no,
    "SCI":extract_sci_invoice_no , 
}

def main():
    print("=" * 80)
    print("MASTER CHARGE EXTRACTION")
    print(f"LIMIT PER CARRIER: {LIMIT}")
    print("=" * 80)

    UNIDENTIFIED_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    all_results = []
    total_unique_pdfs = 0
    total_duplicates = 0
    total_charges = 0
    total_unidentified = 0
    total_failed = 0

    carrier_summaries = []

    for carrier, extractor in CHARGE_TEMPLATES.items():
        carrier_dir = BASE_DIR / carrier

        print()
        print("=" * 80)
        print(f"CARRIER: {carrier}")
        print("=" * 80)

        if not carrier_dir.exists():
            print(f"Folder not found: {carrier_dir}")

            carrier_summaries.append(
                {
                    "CARRIER": carrier,
                    "FOLDER_FOUND": False,
                    "UNIQUE_PDFS": 0,
                    "DUPLICATES_SKIPPED": 0,
                    "UNIDENTIFIED_FILES": 0,
                    "TOTAL_CHARGES": 0,
                    "FAILED_FILES": 0,
                }
            )

            continue

        pdf_files, duplicate_count = get_unique_pdf_files(
            carrier_dir,
            LIMIT,
        )

        print(f"Unique PDFs selected: {len(pdf_files)}")
        print(
            f"Exact duplicate PDFs skipped: "
            f"{duplicate_count}"
        )

        total_unique_pdfs += len(pdf_files)
        total_duplicates += duplicate_count

        carrier_charges = 0
        carrier_unidentified = 0
        carrier_failed = 0

        invoice_extractor = INVOICE_TEMPLATES[carrier]

        for index, pdf_path in enumerate(
            pdf_files,
            start=1,
        ):
            print("-" * 80)
            print(
                f"[{index}/{len(pdf_files)}] "
                f"{pdf_path.name}"
            )

            text, tables, error = extract_pdf_content(
                pdf_path
            )

            if error:
                carrier_failed += 1
                total_failed += 1

                print(f"ERROR: {error}")
                continue

            invoice_no = invoice_extractor(text)

            if not invoice_no:
                try:
                    destination = move_to_unidentified(
                        pdf_path
                    )

                    carrier_unidentified += 1
                    total_unidentified += 1

                    print("INVOICE_NO: None")
                    print(
                        "ACTION: Moved to Unidentified"
                    )
                    print(
                        f"DESTINATION: {destination}"
                    )

                except Exception as move_error:
                    carrier_failed += 1
                    total_failed += 1

                    print("INVOICE_NO: None")
                    print(
                        f"MOVE ERROR: {move_error}"
                    )

                continue

            charges = extractor(
                text,
                tables,
            )

            print(
                f"INVOICE_NO: {invoice_no}"
            )
            print(
                f"CHARGES FOUND: {len(charges)}"
            )

            for charge in charges:
                print(
                    f"  {charge['CHARGE_NAME']} | "
                    f"{charge['CURRENCY_TYPE']} | "
                    f"{charge['AMOUNT']:.2f}"
                )

            carrier_charges += len(charges)
            total_charges += len(charges)

            all_results.append(
                {
                    "INVOICE_NO": invoice_no,
                    "CARRIER": carrier,
                    "PDF_FILE": pdf_path.name,
                    "CHARGES": charges,
                }
            )

        carrier_summaries.append(
            {
                "CARRIER": carrier,
                "FOLDER_FOUND": True,
                "UNIQUE_PDFS": len(pdf_files),
                "DUPLICATES_SKIPPED": duplicate_count,
                "UNIDENTIFIED_FILES": carrier_unidentified,
                "TOTAL_CHARGES": carrier_charges,
                "FAILED_FILES": carrier_failed,
            }
        )

    output = {
        "LIMIT_PER_CARRIER": LIMIT,
        "TOTAL_UNIQUE_PDFS": total_unique_pdfs,
        "TOTAL_DUPLICATES_SKIPPED": total_duplicates,
        "TOTAL_UNIDENTIFIED_FILES": total_unidentified,
        "TOTAL_CHARGES": total_charges,
        "TOTAL_FAILED_FILES": total_failed,
        "CARRIER_SUMMARIES": carrier_summaries,
        "RESULTS": all_results,
    }

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            output,
            file,
            indent=4,
            ensure_ascii=False,
        )

    print()
    print("=" * 80)
    print("MASTER SUMMARY")
    print("=" * 80)
    print(
        f"Total unique PDFs processed: "
        f"{total_unique_pdfs}"
    )
    print(
        f"Total duplicates skipped: "
        f"{total_duplicates}"
    )
    print(
        f"Total PDFs moved to Unidentified: "
        f"{total_unidentified}"
    )
    print(
        f"Total charge rows extracted: "
        f"{total_charges}"
    )
    print(
        f"Total failed PDFs: "
        f"{total_failed}"
    )
    print(f"Output: {OUTPUT_FILE}")
    print("=" * 80)

if __name__ == "__main__":
    main()

