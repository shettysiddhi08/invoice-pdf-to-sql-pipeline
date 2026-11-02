import os
import re
import hashlib
from datetime import datetime
from pathlib import Path

import pdfplumber


BASE_DIR = Path(r"C:\Users\Siddhi\Desktop\sorted_PDFs")

STAGING_TABLE = "dbo.OceanFreightInvoices_Staging"

TARGET_FIELDS = [
    "INVOICE_NO",
    "INVOICE_DATE",
    "DUE_DATE",
    "IRN_NO",
    "COMPANY",
    "PAN_NO",
    "BILL_OF_LADING",
    "VESSEL",
    "CONTAINER_NO",
    "POL",
    "POD",
    "CHARGES_NAME",
    "CURRENCY",
    "CGST",
    "SGST",
    "TAXABLE_AMOUNT",
    "TOTAL_PAYABLE_AMOUNT",
]


def get_empty_result():
    return {
        "INVOICE_NO": None,
        "INVOICE_DATE": None,
        "DUE_DATE": None,
        "IRN_NO": None,
        "COMPANY": None,
        "PAN_NO": None,
        "BILL_OF_LADING": None,
        "VESSEL": None,
        "CONTAINER_NO": None,
        "POL": None,
        "POD": None,
        "CHARGES_NAME": None,
        "CURRENCY": None,
        "CGST": None,
        "SGST": None,
        "TAXABLE_AMOUNT": None,
        "TOTAL_PAYABLE_AMOUNT": None,
    }


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

    value = str(value)
    value = value.replace(",", "")
    value = value.replace("₹", "")
    value = value.replace("$", "")
    value = value.strip()

    try:
        return float(value)
    except ValueError:
        return None


def parse_date(value, formats):
    if not value:
        return None

    value = clean_text(value)

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return None


def table_to_text(table):
    rows = []

    for row in table:
        if not row:
            continue

        cells = []

        for cell in row:
            cells.append(clean_text(cell))

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

                try:
                    tables = page.extract_tables()
                except Exception:
                    tables = []

                for table in tables:
                    table_text = table_to_text(table)

                    if table_text:
                        table_parts.append(table_text)

    except Exception as exc:
        return "", [], str(exc)

    text = "\n".join(text_parts)
    text = clean_text(text)

    return text, table_parts, None


def file_hash(pdf_path):
    sha256 = hashlib.sha256()

    with open(pdf_path, "rb") as file:
        while True:
            chunk = file.read(1024 * 1024)

            if not chunk:
                break

            sha256.update(chunk)

    return sha256.hexdigest()


def get_pdf_files(folder):
    if not folder.exists():
        return []

    return sorted(
        [
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() == ".pdf"
        ]
    )


def get_unique_pdf_files(folder, limit=None):
    pdf_files = get_pdf_files(folder)

    unique_files = []
    seen_hashes = set()
    duplicate_count = 0

    for pdf_path in pdf_files:
        try:
            current_hash = file_hash(pdf_path)
        except Exception:
            continue

        if current_hash in seen_hashes:
            duplicate_count += 1
            continue

        seen_hashes.add(current_hash)
        unique_files.append(pdf_path)

        if limit is not None and len(unique_files) >= limit:
            break

    return unique_files, duplicate_count


def extract_irn(text):
    normalized = text.replace("\xa0", " ")
    normalized = normalized.replace("\u200b", "")
    normalized = normalized.replace("\ufeff", "")

    match = re.search(
        r"IRN\s*No\s*\.\s*:\s*(?:Tax\s+Notification\.\s*)?([A-Fa-f0-9\\:]{64,70})",
        normalized,
        re.IGNORECASE,
    )

    if match:
        value = match.group(1)
        value = value.replace("\\:", "")
        value = value.replace(":", "")
        value = value.replace("\\", "")
        value = value.replace(" ", "")
        value = re.sub(r"\s+", "", value)

        if len(value) == 64 and re.fullmatch(r"[A-Fa-f0-9]{64}", value):
            return value.lower()

    gov_match = re.search(
        r"GOV\s+IRN\s*:\s*([A-Fa-f0-9]{64})",
        normalized,
        re.IGNORECASE,
    )

    if gov_match:
        return gov_match.group(1).lower()

    return None


def extract_containers(text):
    containers = re.findall(
        r"\b[A-Z]{4}\d{7}\b",
        text,
        re.IGNORECASE,
    )

    if not containers:
        return None

    return ",".join(
        dict.fromkeys(
            container.upper()
            for container in containers
        )
    )


def validate_result(result):
    issues = []

    for field in TARGET_FIELDS:
        if field not in result:
            issues.append(f"Missing field: {field}")

    if result.get("CGST") is not None and not isinstance(
        result["CGST"],
        (int, float),
    ):
        issues.append("Invalid CGST")

    if result.get("SGST") is not None and not isinstance(
        result["SGST"],
        (int, float),
    ):
        issues.append("Invalid SGST")

    if result.get("TAXABLE_AMOUNT") is not None and not isinstance(
        result["TAXABLE_AMOUNT"],
        (int, float),
    ):
        issues.append("Invalid TAXABLE_AMOUNT")

    if result.get("TOTAL_PAYABLE_AMOUNT") is not None and not isinstance(
        result["TOTAL_PAYABLE_AMOUNT"],
        (int, float),
    ):
        issues.append("Invalid TOTAL_PAYABLE_AMOUNT")

    return issues

def extract_maersk(text, tables):
    result = get_empty_result()

    invoice_match = re.search(
        r"\bMH\d{2}[A-Z]{2}\d+\b",
        text,
        re.IGNORECASE,
    )

    if invoice_match:
        result["INVOICE_NO"] = invoice_match.group(0).upper()

    invoice_date_match = re.search(
        r"\bInvoice\s+Date\s+"
        r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
        text,
        re.IGNORECASE,
    )

    if invoice_date_match:
        result["INVOICE_DATE"] = parse_date(
            invoice_date_match.group(1),
            [
                "%b %d, %Y",
                "%B %d, %Y",
            ],
        )

    due_date_match = re.search(
        r"\bDue\s+Date\s+"
        r"([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})",
        text,
        re.IGNORECASE,
    )

    if due_date_match:
        result["DUE_DATE"] = parse_date(
            due_date_match.group(1),
            [
                "%b %d, %Y",
                "%B %d, %Y",
            ],
        )

    normalized = text.replace("\xa0", " ")
    normalized = normalized.replace("\u200b", "")
    normalized = normalized.replace("\ufeff", "")

    irn_value = None

    irn_match = re.search(
        r"\bIRN\s*(?:No\.?|Number)?\s*[:#\-]?\s*",
        normalized,
        re.IGNORECASE,
    )

    if irn_match:
        tail = normalized[
            irn_match.end():
            irn_match.end() + 300
        ]

        parts = re.findall(
            r"\b[A-Fa-f0-9]+\b",
            tail,
        )

        combined = ""

        for part in parts:
            if len(combined) >= 64:
                break

            combined += part

            if len(combined) >= 64:
                candidate = combined[:64]

                if re.fullmatch(
                    r"[A-Fa-f0-9]{64}",
                    candidate,
                ):
                    irn_value = candidate.lower()
                    break

    if irn_value is None:
        direct_irn = re.search(
            r"(?<![A-Fa-f0-9])"
            r"([A-Fa-f0-9]{64})"
            r"(?![A-Fa-f0-9])",
            normalized,
        )

        if direct_irn:
            irn_value = direct_irn.group(1).lower()

    result["IRN_NO"] = irn_value

    pan_match = re.search(
        r"\b[A-Z]{5}\d{4}[A-Z]\b",
        text,
        re.IGNORECASE,
    )

    if pan_match:
        result["PAN_NO"] = pan_match.group(0).upper()

    result["COMPANY"] = "Maersk Line India Pvt. Ltd."

    bl_match = re.search(
        r"\bBill\s+of\s+Lading\s+"
        r"([A-Z0-9\/-]+)",
        text,
        re.IGNORECASE,
    )

    if bl_match:
        result["BILL_OF_LADING"] = (
            bl_match.group(1).strip().upper()
        )

    vessel_match = re.search(
        r"\bVessel\/Voyage\s+Direction\s+Reference\s+"
        r"(.+?)\/[A-Za-z0-9-]+\b",
        text,
        re.IGNORECASE,
    )

    if vessel_match:
        vessel = clean_text(
            vessel_match.group(1)
        )

        if vessel:
            result["VESSEL"] = vessel

    containers = re.findall(
        r"\b[A-Z]{4}\d{7}\b",
        text,
        re.IGNORECASE,
    )

    valid_containers = []

    for container in containers:
        container = container.upper()

        if container == "HSBC0400002":
            continue

        if container.startswith("HSBC"):
            continue

        valid_containers.append(container)

    if valid_containers:
        result["CONTAINER_NO"] = ",".join(
            dict.fromkeys(valid_containers)
        )

    currency_matches = re.findall(
        r"\b(?:USD|INR|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|"
        r"SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)\b",
        text,
        re.IGNORECASE,
    )

    if currency_matches:
        result["CURRENCY"] = ", ".join(
            dict.fromkeys(
                value.upper()
                for value in currency_matches
            )
        )

    pol = None
    pod = None

    for table_text in tables:
        if not table_text:
            continue

        table_text = str(table_text)

        pol_match = re.search(
            r"\bPort\s+of\s+Loading\b"
            r"\s*(?:\|\s*)?"
            r"([A-Za-z0-9][A-Za-z0-9 .()&\/-]*,\s*[A-Z]{2})\b",
            table_text,
            re.IGNORECASE,
        )

        if pol_match and pol is None:
            pol = clean_text(
                pol_match.group(1)
            )

        pod_match = re.search(
            r"\bPort\s+of\s+Discharge\b"
            r"\s*(?:\|\s*)?"
            r"([A-Za-z0-9][A-Za-z0-9 .()&\/-]*,\s*[A-Z]{2})\b",
            table_text,
            re.IGNORECASE,
        )

        if pod_match and pod is None:
            pod = clean_text(
                pod_match.group(1)
            )

    if pol is None or pod is None:
        route_match = re.search(
            r"\bPlace\s+of\s+Receipt\s+"
            r"Port\s+of\s+Loading\s+"
            r"Port\s+of\s+Discharge\s+"
            r"Place\s+of\s+Delivery\s+"
            r"(.+?)"
            r"\s+Bill\s+of\s+Lading\b",
            text,
            re.IGNORECASE,
        )

        if route_match:
            route_values = re.findall(
                r"[A-Za-z0-9][A-Za-z0-9 .()&\/-]*,\s*[A-Z]{2}\b",
                route_match.group(1),
            )

            if len(route_values) >= 2 and pol is None:
                pol = clean_text(
                    route_values[1]
                )

            if len(route_values) >= 3 and pod is None:
                pod = clean_text(
                    route_values[2]
                )

    result["POL"] = pol
    result["POD"] = pod

    charge_names = []

    charge_pattern = re.compile(
        r"(?<![A-Za-z])"
        r"(?P<description>"
        r"[A-Za-z]"
        r"[A-Za-z0-9 .,&()\/\-–]*?"
        r")"
        r"\s+"
        r"(?P<quantity>\d+(?:\.\d+)?)"
        r"\s+"
        r"(?P<unit>[A-Z]+)"
        r"\s+"
        r"(?P<rate>[\d,]+(?:\.\d+)?)"
        r"\s+"
        r"(?P<currency>"
        r"USD|INR|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|"
        r"SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND"
        r")"
        r"\s+"
        r"(?P<amount>[\d,]+(?:\.\d+)?)",
        re.IGNORECASE,
    )

    source_parts = []

    for table_text in tables:
        if not table_text:
            continue

        table_text = str(table_text)

        header_match = re.search(
            r"Description\s+of\s+Charges.*?"
            r"Extended\s+Value",
            table_text,
            re.IGNORECASE,
        )

        if header_match:
            table_text = table_text[
                header_match.end():
            ]

        source_parts.append(table_text)

    if text:
        text_source = text

        header_match = re.search(
            r"Description\s+of\s+Charges.*?"
            r"Extended\s+Value",
            text_source,
            re.IGNORECASE,
        )

        if header_match:
            text_source = text_source[
                header_match.end():
            ]

        source_parts.append(text_source)

    for source in source_parts:
        for match in charge_pattern.finditer(source):
            charge = clean_text(
                match.group("description")
            )

            if not charge:
                continue

            if re.search(
                r"\b(?:Description|QTY|UOM|Rate|Currency|Extended|Value|"
                r"CGST|SGST|IGST|SAC|HSN|Total|Tax|Taxable)\b",
                charge,
                re.IGNORECASE,
            ):
                continue

            charge_names.append(charge)

    if charge_names:
        result["CHARGES_NAME"] = ", ".join(
            dict.fromkeys(charge_names)
        )

    taxable_match = re.search(
        r"\bTotal\s+Base\s+Amount\s+"
        r"(?:INR|USD|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|"
        r"SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)\s+"
        r"([\d,]+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )

    if taxable_match:
        result["TAXABLE_AMOUNT"] = clean_number(
            taxable_match.group(1)
        )

    total_match = re.search(
        r"\bTotal\s+Payable\s+Amount\s+"
        r"(?:INR|USD|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|"
        r"SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)\s+"
        r"([\d,]+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )

    if total_match:
        result["TOTAL_PAYABLE_AMOUNT"] = clean_number(
            total_match.group(1)
        )

    cgst_match = re.search(
        r"\bC-GST\s+Total\s+taxes"
        r".*?"
        r"(?:INR|USD|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|"
        r"SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)\s+"
        r"([\d,]+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )

    if cgst_match:
        result["CGST"] = clean_number(
            cgst_match.group(1)
        )

    sgst_match = re.search(
        r"\bS-GST\s+Total\s+taxes"
        r".*?"
        r"(?:INR|USD|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|"
        r"SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)\s+"
        r"([\d,]+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )

    if sgst_match:
        result["SGST"] = clean_number(
            sgst_match.group(1)
        )

    return result


def extract_cma_cgm(text, tables):
    result = get_empty_result()

    match = re.search(
        r"\bINE[A-Z0-9]+\b",
        text,
        re.IGNORECASE,
    )

    if match:
        result["INVOICE_NO"] = match.group(0).upper()

    date_match = re.search(
        r"(?:Invoice\s+Date|Date)\s*[:\-]?\s*"
        r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})",
        text,
        re.IGNORECASE,
    )

    if date_match:
        result["INVOICE_DATE"] = parse_date(
            date_match.group(1),
            [
                "%d/%m/%Y",
                "%d-%m-%Y",
                "%m/%d/%Y",
                "%m-%d-%Y",
            ],
        )

    due_match = re.search(
        r"(?:Due\s+Date|Payable\s+by)\s*[:\-]?\s*"
        r"(\d{1,2}[\/\-][A-Za-z]{3}[\/\-]\d{4}|\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})",
        text,
        re.IGNORECASE,
    )

    if due_match:
        due_value = due_match.group(1)

        result["DUE_DATE"] = parse_date(
            due_value,
            [
                "%d/%m/%Y",
                "%d-%m-%Y",
                "%m/%d/%Y",
                "%m-%d-%Y",
                "%d-%b-%Y",
                "%d/%b/%Y",
            ],
        )

    normalized = text.replace("\xa0", " ")
    normalized = normalized.replace("\u200b", "")
    normalized = normalized.replace("\ufeff", "")

    irn_value = None

    irn_match = re.search(
        r"\bIRN\s*(?:No\.?|Number)?\s*[:#\-]?\s*"
        r"([A-Fa-f0-9]{32}\s*[A-Fa-f0-9]{32})",
        normalized,
        re.IGNORECASE,
    )

    if irn_match:
        candidate = re.sub(
            r"\s+",
            "",
            irn_match.group(1),
        )

        if len(candidate) == 64 and re.fullmatch(
            r"[A-Fa-f0-9]{64}",
            candidate,
        ):
            irn_value = candidate.lower()

    if irn_value is None:
        lines = normalized.splitlines()

        for index, line in enumerate(lines):
            if re.search(r"\bIRN\b", line, re.IGNORECASE):
                combined = re.sub(
                    r"[^A-Fa-f0-9]",
                    "",
                    line.split("IRN", 1)[-1],
                )

                if len(combined) >= 64:
                    candidate = combined[:64]

                    if re.fullmatch(
                        r"[A-Fa-f0-9]{64}",
                        candidate,
                    ):
                        irn_value = candidate.lower()
                        break

                for next_index in range(
                    index + 1,
                    min(index + 5, len(lines)),
                ):
                    next_part = re.sub(
                        r"[^A-Fa-f0-9]",
                        "",
                        lines[next_index],
                    )

                    if not next_part:
                        continue

                    combined += next_part

                    if len(combined) >= 64:
                        candidate = combined[:64]

                        if re.fullmatch(
                            r"[A-Fa-f0-9]{64}",
                            candidate,
                        ):
                            irn_value = candidate.lower()

                        break

                if irn_value:
                    break

    if irn_value is None:
        gov_match = re.search(
            r"GOV\s+IRN\s*:\s*([A-Fa-f0-9]{64})",
            normalized,
            re.IGNORECASE,
        )

        if gov_match:
            irn_value = gov_match.group(1).lower()

    result["IRN_NO"] = irn_value

    pan_match = re.search(
        r"\b[A-Z]{5}\d{4}[A-Z]\b",
        text,
        re.IGNORECASE,
    )

    if pan_match:
        result["PAN_NO"] = pan_match.group(0).upper()

    company_match = re.search(
        r"Payable\s+to\s*:\s*(.+?)(?=\s+Invoice\s+To\s*:)",
        text,
        re.IGNORECASE,
    )

    if company_match:
        company = clean_text(company_match.group(1))
        company = re.sub(
            r"[.\s]+$",
            "",
            company,
        )
        result["COMPANY"] = company

    bl_match = re.search(
        r"(?:Bill\s+of\s+Lading|B\/L|BL)\s*"
        r"(?:No\.?|Number)?\s*[:\-]?\s*"
        r"([A-Z0-9\-\/]+)",
        text,
        re.IGNORECASE,
    )

    if bl_match:
        result["BILL_OF_LADING"] = bl_match.group(1).strip().upper()

    vessel_match = re.search(
        r"\bVessel\s*:\s*(.+?)\s+Call\s+Date\s*:",
        text,
        re.IGNORECASE,
    )

    if vessel_match:
        result["VESSEL"] = clean_text(
            vessel_match.group(1)
        )

    result["CONTAINER_NO"] = extract_containers(text)

    currency_matches = re.findall(
        r"\b(?:USD|INR|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)\b",
        text,
        re.IGNORECASE,
    )

    if currency_matches:
        result["CURRENCY"] = ", ".join(
            dict.fromkeys(
                value.upper()
                for value in currency_matches
            )
        )

    load_port_match = re.search(
        r"\bLoad\s+Port\s*:\s*(.+?)"
        r"(?=\s+Place\s+of\s+Delivery\s*:)",
        text,
        re.IGNORECASE,
    )

    if load_port_match:
        result["POL"] = clean_text(
            load_port_match.group(1)
        )

    discharge_port_match = re.search(
        r"\bDischarge\s+Port\s*:\s*(.+?)"
        r"(?=\s+Load\s+Port\s*:)",
        text,
        re.IGNORECASE,
    )

    if discharge_port_match:
        result["POD"] = clean_text(
            discharge_port_match.group(1)
        )

    charge_names = []

    charge_line_pattern = re.compile(
        r"\b\d{2}[A-Z]{2}\s+[A-Z]\s+"
        r"(?P<description>.*?)"
        r"\s+[A-Z]{2}\s+"
        r"\d+(?:\.\d+)?[A-Z]+\s+"
        r"[\d,]+(?:\.\d+)?\s*"
        r"(?:USD|INR|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)\b",
        re.IGNORECASE,
    )

    for table_text in tables:
        if not table_text:
            continue

        for row in str(table_text).splitlines():
            row = clean_text(row)

            if not row:
                continue

            for match in charge_line_pattern.finditer(row):
                charge = clean_text(
                    match.group("description")
                )

                if charge:
                    charge_names.append(charge)

    if not charge_names:
        for match in charge_line_pattern.finditer(text):
            charge = clean_text(
                match.group("description")
            )

            if charge:
                charge_names.append(charge)

    if charge_names:
        result["CHARGES_NAME"] = ", ".join(
            dict.fromkeys(charge_names)
        )

    taxable_match = re.search(
        r"\bTotal\s+Excluding\s+Tax\s+"
        r"([\d,]+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )

    if taxable_match:
        result["TAXABLE_AMOUNT"] = clean_number(
            taxable_match.group(1)
        )

    if result["TAXABLE_AMOUNT"] is None:
        taxable_match = re.search(
            r"\bTotal\s+Excluding\s+Tax\b.*?"
            r"([\d,]+(?:\.\d+)?)",
            text,
            re.IGNORECASE | re.DOTALL,
        )

        if taxable_match:
            result["TAXABLE_AMOUNT"] = clean_number(
                taxable_match.group(1)
            )

    total_match = re.search(
        r"\bTotal\s+Including\s+Tax\s+"
        r"([\d,]+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )

    if total_match:
        result["TOTAL_PAYABLE_AMOUNT"] = clean_number(
            total_match.group(1)
        )

    if result["TOTAL_PAYABLE_AMOUNT"] is None:
        total_match = re.search(
            r"\bTotal\s+Amount\s*:\s*"
            r"([\d,]+(?:\.\d+)?)\s*"
            r"(?:USD|INR|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)?",
            text,
            re.IGNORECASE,
        )

        if total_match:
            result["TOTAL_PAYABLE_AMOUNT"] = clean_number(
                total_match.group(1)
            )

    cgst_values = []
    sgst_values = []

    for match in re.finditer(
        r"\b(?:[A-Z]{2}\s+)?CGST\s*@\s*[\d.]+\s*%\s+"
        r".*?"
        r"([\d,]+(?:\.\d+)?)\s+"
        r"([\d,]+(?:\.\d+)?)"
        r"(?:\s*(?:INR|USD|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND))?",
        text,
        re.IGNORECASE,
    ):
        taxable_value = clean_number(match.group(1))
        tax_value = clean_number(match.group(2))

        if tax_value is not None:
            cgst_values.append(tax_value)

    for match in re.finditer(
        r"\b(?:[A-Z]{2}\s+)?SGST\s*@\s*[\d.]+\s*%\s+"
        r".*?"
        r"([\d,]+(?:\.\d+)?)\s+"
        r"([\d,]+(?:\.\d+)?)"
        r"(?:\s*(?:INR|USD|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND))?",
        text,
        re.IGNORECASE,
    ):
        taxable_value = clean_number(match.group(1))
        tax_value = clean_number(match.group(2))

        if tax_value is not None:
            sgst_values.append(tax_value)

    total_cgst_match = re.search(
        r"\bTotal\s+CGST\b.*?"
        r"([\d,]+(?:\.\d+)?)"
        r"(?:\s*(?:INR|USD|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND))?",
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if total_cgst_match:
        value = clean_number(
            total_cgst_match.group(1)
        )

        if value is not None:
            result["CGST"] = value

    elif cgst_values:
        result["CGST"] = round(
            sum(cgst_values),
            2,
        )

    total_sgst_match = re.search(
        r"\bTotal\s+SGST\b.*?"
        r"([\d,]+(?:\.\d+)?)"
        r"(?:\s*(?:INR|USD|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND))?",
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if total_sgst_match:
        value = clean_number(
            total_sgst_match.group(1)
        )

        if value is not None:
            result["SGST"] = value

    elif sgst_values:
        result["SGST"] = round(
            sum(sgst_values),
            2,
        )

    return result

def extract_hapag_lloyd(text, tables):
    result = get_empty_result()

    invoice_match = re.search(
        r"INVOICE\s*NO\.?\s*:\s*([A-Z0-9]+)",
        text,
        re.IGNORECASE,
    )

    if invoice_match:
        result["INVOICE_NO"] = invoice_match.group(1).upper()

    invoice_date_match = re.search(
        r"INVOICE\s*NO\.?\s*:\s*[A-Z0-9]+\s+REF\s*:\s*\d+\s+"
        r"(\d{2}\.\d{2}\.\d{4})",
        text,
        re.IGNORECASE,
    )

    if invoice_date_match:
        result["INVOICE_DATE"] = parse_date(
            invoice_date_match.group(1),
            [
                "%d.%m.%Y",
                "%d/%m/%Y",
                "%d-%m-%Y",
            ],
        )

    due_match = re.search(
        r"(?:DUE\s*DATE|DUE\s*DATE\s*:)\s*"
        r"(\d{1,2}[./-]\d{1,2}[./-]\d{4})",
        text,
        re.IGNORECASE,
    )

    if due_match:
        result["DUE_DATE"] = parse_date(
            due_match.group(1),
            [
                "%d.%m.%Y",
                "%d/%m/%Y",
                "%d-%m-%Y",
                "%m.%d.%Y",
                "%m/%d/%Y",
                "%m-%d-%Y",
            ],
        )

    result["IRN_NO"] = extract_irn(text)
    result["COMPANY"] = "Hapag-Lloyd AG"

    pan_match = re.search(
        r"\b[A-Z]{5}\d{4}[A-Z]\b",
        text,
        re.IGNORECASE,
    )

    if pan_match:
        result["PAN_NO"] = pan_match.group(0).upper()

    bl_match = re.search(
        r"(?:SWB-NO\.?|B\/L-NO\.?)\s*[:\-]?\s*([A-Z0-9\-]+)",
        text,
        re.IGNORECASE,
    )

    if bl_match:
        result["BILL_OF_LADING"] = bl_match.group(1).upper()

    vessel_match = re.search(
        r"FCL\/FCL\s+(.+?)\s+\d{2,4}[A-Z]{1,3}\s*\/\s*\d+"
        r"\s+SAILING",
        text,
        re.IGNORECASE,
    )

    if vessel_match:
        result["VESSEL"] = clean_text(vessel_match.group(1))

    route_match = re.search(
        r"\bFROM\s+(.+?)\s+TO\s+(.+?)"
        r"(?=\s+[A-Z][A-Z0-9 .,'&()\/-]*\s+\d{6}\s+)",
        text,
        re.IGNORECASE,
    )

    if route_match:
        result["POL"] = clean_text(route_match.group(1))
        result["POD"] = clean_text(route_match.group(2))

    containers = re.findall(
        r"\b[A-Z]{4}\s*\d{7}\b",
        text,
        re.IGNORECASE,
    )

    if containers:
        result["CONTAINER_NO"] = ",".join(
            dict.fromkeys(
                re.sub(r"\s+", "", value).upper()
                for value in containers
            )
        )

    charge_names = []

    route_charge_match = re.search(
        r"\bFROM\s+.+?\s+TO\s+.+?"
        r"(?=\s+[A-Z][A-Z0-9 .,'&()\/-]*\s+\d{6}\s+)"
        r"(.+?)"
        r"\s+NET\s+[\d,]+\.\d+\s+[A-Z]{3}",
        text,
        re.IGNORECASE,
    )

    if route_charge_match:
        charge_section = clean_text(route_charge_match.group(1))

        charge_pattern = re.compile(
            r"([A-Z][A-Z0-9 .,'&()\/-]*?)"
            r"(?:\s+\d{6})?"
            r"\s+"
            r"(?:[\d,]+\.\d+)\s+"
            r"(?:USD|EUR|GBP|INR|AED|SGD|CNY|JPY|AUD|CAD|CHF|HKD|MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)\b",
            re.IGNORECASE,
        )

        for match in charge_pattern.finditer(charge_section):
            charge = clean_text(match.group(1))

            charge = re.sub(
                r"\b\d{6}\s*$",
                "",
                charge,
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

            if charge:
                charge_names.append(charge)

    if charge_names:
        result["CHARGES_NAME"] = ", ".join(
            dict.fromkeys(charge_names)
        )

    net_match = re.search(
        r"\bNET\s+([\d,]+\.\d+)\s+([A-Z]{3})\b",
        text,
        re.IGNORECASE,
    )

    if net_match:
        result["TAXABLE_AMOUNT"] = clean_number(
            net_match.group(1)
        )
        result["CURRENCY"] = net_match.group(2).upper()

    gross_match = re.search(
        r"\bGROSS\s+([\d,]+\.\d+)\s+([A-Z]{3})\b",
        text,
        re.IGNORECASE,
    )

    if gross_match:
        result["TOTAL_PAYABLE_AMOUNT"] = clean_number(
            gross_match.group(1)
        )

        if result["CURRENCY"] is None:
            result["CURRENCY"] = gross_match.group(2).upper()

    cgst_values = []
    sgst_values = []

    tax_pattern = re.compile(
        r"\b\d+[AB]\s+[\d,]+\.\d+\s+[\d.]+\s*%\s+"
        r"([\d,]+\.\d+)\s+[A-Z]{3}",
        re.IGNORECASE,
    )

    for match in tax_pattern.finditer(text):
        full_match = match.group(0)
        amount = clean_number(match.group(1))

        code_match = re.match(
            r"\s*(\d+[AB])",
            full_match,
            re.IGNORECASE,
        )

        if not code_match:
            continue

        code = code_match.group(1).upper()

        if code.endswith("A"):
            cgst_values.append(amount)

        elif code.endswith("B"):
            sgst_values.append(amount)

    if cgst_values:
        result["CGST"] = round(sum(cgst_values), 2)

    if sgst_values:
        result["SGST"] = round(sum(sgst_values), 2)

    return result

def extract_hmm(text, tables):
    result = get_empty_result()

    invoice_match = re.search(
        r"\b(?:BF|MF|BOF|MR)\d+\b",
        text,
        re.IGNORECASE,
    )

    if invoice_match:
        result["INVOICE_NO"] = invoice_match.group(0).upper()

    date_match = re.search(
        r"Invoice\s+Date\s*[:\-]?\s*"
        r"(\d{4}-\d{2}-\d{2})",
        text,
        re.IGNORECASE,
    )

    if date_match:
        result["INVOICE_DATE"] = date_match.group(1)

    due_match = re.search(
        r"Due\s+Date\s*[:\-]?\s*(\d{4}-\d{2}-\d{2})",
        text,
        re.IGNORECASE,
    )

    if due_match:
        result["DUE_DATE"] = due_match.group(1)

    result["IRN_NO"] = extract_irn(text)
    result["COMPANY"] = "HMM SHIPPING INDIA PVT. LTD."
    result["PAN_NO"] = "AABCH5572J"

    bl_match = re.search(
        r"(?:B\/L\s+No|B\/L\s+or\s+Booking\s+No)\s*:\s*"
        r"([A-Z0-9\-]+)",
        text,
        re.IGNORECASE,
    )

    if bl_match:
        result["BILL_OF_LADING"] = bl_match.group(1).upper()

    vessel_match = re.search(
        r"(?:Mother\s+Vessel|Vessel\s+Voyage\s+Drection)\s*:\s*"
        r"(.+?)"
        r"(?=\s+(?:Feeder\s+Vessel|Sailing\/Arrival\s+Date|"
        r"B\/L\s+No|B\/L\s+or\s+Booking\s+No|Customer\s+Reference\s+No|"
        r"Place\s+of\s+Receipt)\b)",
        text,
        re.IGNORECASE,
    )

    if vessel_match:
        result["VESSEL"] = clean_text(vessel_match.group(1))

    containers = re.findall(
        r"\b[A-Z]{4}\d{7}\b",
        text,
        re.IGNORECASE,
    )

    containers = [
        value.upper()
        for value in containers
        if value.upper() != "ICIC0000106"
    ]

    if containers:
        result["CONTAINER_NO"] = ",".join(
            dict.fromkeys(containers)
        )

    pol_match = re.search(
        r"Port\s+of\s+Loading\s*:\s*(.+?)"
        r"(?=\s+Port\s+of\s+Discharge\s*:)",
        text,
        re.IGNORECASE,
    )

    if pol_match:
        result["POL"] = clean_text(pol_match.group(1))

    pod_match = re.search(
        r"Port\s+of\s+Discharge\s*:\s*(.+?)"
        r"(?=\s+Place\s+of\s+Delivery\s*:)",
        text,
        re.IGNORECASE,
    )

    if pod_match:
        result["POD"] = clean_text(pod_match.group(1))

    charges = []

    charge_pattern = re.compile(
        r"\b(?:AM1|SEF|DOL|MUF|THL|EFL|OAF|O\/F)\s+"
        r"(.+?)"
        r"\s+(?:USD|INR|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)\b",
        re.IGNORECASE,
    )

    for match in charge_pattern.finditer(text):
        charge = clean_text(match.group(1))

        charge = re.sub(
            r"\s+(?:BL|BX|DC20|FR4H|DC4H|2A|4A|OT20|OT40)\s*$",
            "",
            charge,
            flags=re.IGNORECASE,
        )

        if charge:
            charges.append(charge)

    mr_charge_pattern = re.compile(
        r"Description\s+Of\s+Charges\s+SAC\s+Unit\s+Type\s+Size\s+Curr\.\s+"
        r"Unit\s+Price\s+Amount\s+"
        r"(.+?)"
        r"\s+\d{6}\s+\d+\s+[A-Z]{2,4}\s+\d+\s*",
        re.IGNORECASE,
    )

    mr_charge_match = mr_charge_pattern.search(text)

    if mr_charge_match:
        charge = clean_text(mr_charge_match.group(1))

        if charge:
            charges.append(charge)

    if charges:
        result["CHARGES_NAME"] = ", ".join(
            dict.fromkeys(charges)
        )

    currencies = re.findall(
        r"\b(?:USD|INR|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)\b",
        text,
        re.IGNORECASE,
    )

    if currencies:
        result["CURRENCY"] = ", ".join(
            dict.fromkeys(
                value.upper()
                for value in currencies
            )
        )

    cgst_match = re.search(
        r"\bCGST\s+([\d,]+\.\d+)\s+SGST\s+[\d,]+\.\d+",
        text,
        re.IGNORECASE,
    )

    if cgst_match:
        result["CGST"] = clean_number(
            cgst_match.group(1)
        )

    sgst_match = re.search(
        r"\bCGST\s+[\d,]+\.\d+\s+SGST\s+([\d,]+\.\d+)",
        text,
        re.IGNORECASE,
    )

    if sgst_match:
        result["SGST"] = clean_number(
            sgst_match.group(1)
        )

    taxable_match = re.search(
        r"\bTaxable\s+([\d,]+\.\d+)\s+Tax\b",
        text,
        re.IGNORECASE,
    )

    if taxable_match:
        result["TAXABLE_AMOUNT"] = clean_number(
            taxable_match.group(1)
        )

    total_match = re.search(
        r"\bTotal\s+([\d,]+\.\d+)\s+"
        r"(?:Total\s+USD|Total\s+INR|Total\s+In\s+words)",
        text,
        re.IGNORECASE,
    )

    if total_match:
        result["TOTAL_PAYABLE_AMOUNT"] = clean_number(
            total_match.group(1)
        )

    if (
        result["CGST"] is None
        or result["SGST"] is None
        or result["TAXABLE_AMOUNT"] is None
    ):
        summary_tax_match = re.search(
            r"\bCGST\s+([\d,]+\.\d+)\s+"
            r"SGST\s+([\d,]+\.\d+)\s+"
            r"IGST\s+[\d,]+\.\d+\s+"
            r"Taxable\s+([\d,]+\.\d+)",
            text,
            re.IGNORECASE,
        )

        if summary_tax_match:
            if result["CGST"] is None:
                result["CGST"] = clean_number(
                    summary_tax_match.group(1)
                )

            if result["SGST"] is None:
                result["SGST"] = clean_number(
                    summary_tax_match.group(2)
                )

            if result["TAXABLE_AMOUNT"] is None:
                result["TAXABLE_AMOUNT"] = clean_number(
                    summary_tax_match.group(3)
                )

    if (
        result["CGST"] is None
        or result["SGST"] is None
        or result["TAXABLE_AMOUNT"] is None
    ):
        charge_amount_pattern = re.compile(
            r"\b(?:AM1|SEF|DOL|MUF|THL|EFL|OAF|O\/F)\s+"
            r".+?\s+"
            r"(?:USD|INR|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)\s+"
            r"[A-Z0-9]+\s+"
            r"[\d,]+\.\d+\s+"
            r"\d+\s+"
            r"\d{6}\s+"
            r"([\d,]+\.\d+)\s+"
            r"[\d.]+\s+"
            r"([\d,]+\.\d+)\s+"
            r"[\d.]+\s+"
            r"([\d,]+\.\d+)",
            re.IGNORECASE,
        )

        fallback_taxable = 0.0
        fallback_cgst = 0.0
        fallback_sgst = 0.0

        for match in charge_amount_pattern.finditer(text):
            fallback_taxable += clean_number(match.group(1))
            fallback_cgst += clean_number(match.group(2))
            fallback_sgst += clean_number(match.group(3))

        if result["TAXABLE_AMOUNT"] is None and fallback_taxable:
            result["TAXABLE_AMOUNT"] = round(
                fallback_taxable,
                2,
            )

        if result["CGST"] is None and fallback_cgst:
            result["CGST"] = round(
                fallback_cgst,
                2,
            )

        if result["SGST"] is None and fallback_sgst:
            result["SGST"] = round(
                fallback_sgst,
                2,
            )

    if (
        result["TOTAL_PAYABLE_AMOUNT"] is None
        and result["CGST"] is not None
        and result["SGST"] is not None
        and result["TAXABLE_AMOUNT"] is not None
    ):
        result["TOTAL_PAYABLE_AMOUNT"] = round(
            result["TAXABLE_AMOUNT"]
            + result["CGST"]
            + result["SGST"],
            2,
        )

    return result

def extract_hub_and_links(text, tables): 
    result = get_empty_result()

    invoice_match = re.search(
        r"(?:Invoice\s+No\.?|Invoice\s+Number)\s*:\s*([A-Z0-9\-\/]+)",
        text,
        re.IGNORECASE,
    )

    if invoice_match:
        result["INVOICE_NO"] = invoice_match.group(1).strip()

    date_match = re.search(
        r"Invoice\s+Date\s*:\s*"
        r"(\d{1,2}[\/\-][A-Za-z]{3}[\/\-]\d{4}|\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})",
        text,
        re.IGNORECASE,
    )

    if date_match:
        result["INVOICE_DATE"] = parse_date(
            date_match.group(1),
            [
                "%d/%b/%Y",
                "%d/%B/%Y",
                "%d/%m/%Y",
                "%d-%m-%Y",
                "%d-%b-%Y",
                "%d-%B-%Y",
            ],
        )

    due_match = re.search(
        r"(?:Invoice\s+)?Due\s+Date\s*:\s*"
        r"(\d{1,2}[\/\-][A-Za-z]{3}[\/\-]\d{4}|\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})",
        text,
        re.IGNORECASE,
    )

    if due_match:
        result["DUE_DATE"] = parse_date(
            due_match.group(1),
            [
                "%d/%b/%Y",
                "%d/%B/%Y",
                "%d/%m/%Y",
                "%d-%m-%Y",
                "%d-%b-%Y",
                "%d-%B-%Y",
            ],
        )

    result["IRN_NO"] = extract_irn(text)
    result["COMPANY"] = "HUB AND LINKS LOGISTICS INDIA PVT LTD"
    result["PAN_NO"] = "AACCH0890G"

    bl_match = re.search(
        r"Prepaid\s+BL\s+number\s*:\s*([A-Z0-9\-\/]+)",
        text,
        re.IGNORECASE,
    )

    if bl_match:
        result["BILL_OF_LADING"] = bl_match.group(1).upper().strip()

    vessel_match = re.search(
        r"Vessel\s*\/\s*Voyage\s*:\s*([^\/\r\n]+)",
        text,
        re.IGNORECASE,
    )

    if vessel_match:
        result["VESSEL"] = clean_text(
            vessel_match.group(1)
        )

    container_match = re.search(
        r"Container\s+No\.\s+And\s+Type\s*:\s*.*?\(([A-Z]{4}\d{7})\)",
        text,
        re.IGNORECASE,
    )

    if container_match:
        result["CONTAINER_NO"] = container_match.group(1).upper()

    pol_match = re.search(
        r"Port\s+of\s+Loading\s*\(\s*T\s*\)\s*:\s*(.*?)(?="
        r"\s+Booking\s+Party\s+Name\s*:|"
        r"\s+Port\s+of\s+Discharge\s*:|"
        r"\r?\n|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if pol_match:
        result["POL"] = clean_text(
            pol_match.group(1)
        )

    pod_match = re.search(
        r"Port\s+of\s+Discharge\s*:\s*(.*?)(?="
        r"\s+Final\s+Destination\s*:|"
        r"\r?\n|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if pod_match:
        result["POD"] = clean_text(
            pod_match.group(1)
        )

    charge_patterns = [
    r"Ocean\s+Freight",
    r"Container\s+Seal\s+Charges",
    r"Container\s+Release\s+Facilitation\s+Charges",
    r"Documentation\s+Charges",
    r"Administration\s+Charges",
    r"Mandatory\s+User\s+Charges",
    r"Toll\s+Charges",
    r"Terminal\s+Handling\s+Charges(?:-[A-Za-z]+)?",
    r"Ssr\s+Charges",
    r"Detention\s+Charges",
    r"BL\s+Surrender\s+Charges",
    r"Surrender\s+Fee",
    r"Bill\s+of\s+Lading\s+Surrender\s+Charges",
]

    charges = []

    for line in text.splitlines():
        line = clean_text(line)

        if not line:
            continue

        for pattern in charge_patterns:
            matches = re.findall(
                r"\b(" + pattern + r")\b",
                line,
                re.IGNORECASE,
            )

            for match in matches:
                charge = clean_text(match)

                if not any(
                    charge.lower() == existing.lower()
                    for existing in charges
                ):
                    charges.append(charge)

    for table in tables:
        if isinstance(table, str):
            table_text = clean_text(table)
        else:
            table_text = clean_text(
                " ".join(
                    str(cell)
                    for row in table
                    for cell in row
                    if cell is not None
                )
            )

        if not table_text:
            continue

        for pattern in charge_patterns:
            matches = re.findall(
                r"\b(" + pattern + r")\b",
                table_text,
                re.IGNORECASE,
            )

            for match in matches:
                charge = clean_text(match)

                if not any(
                    charge.lower() == existing.lower()
                    for existing in charges
                ):
                    charges.append(charge)

    if charges:
        result["CHARGES_NAME"] = ", ".join(charges)

    currency_match = re.search(
        r"Currency\s*\/\s*Ex\s*Rate\s*:\s*"
        r"(USD|INR|EUR|GBP|AED|SGD)\s*\/",
        text,
        re.IGNORECASE,
    )

    if currency_match:
        result["CURRENCY"] = currency_match.group(1).upper()

    tax_row_matches = re.findall(
        r"(?:Ocean\s+Freight|Container\s+Seal\s+Charges|"
        r"Container\s+Release\s+Facilitation\s+Charges|"
        r"Documentation\s+Charges|Administration\s+Charges|"
        r"Mandatory\s+User\s+Charges|Toll\s+Charges|"
        r"Terminal\s+Handling\s+Charges(?:-[A-Za-z]+)?|"
        r"Ssr\s+Charges|Detention\s+Charges)"
        r".*?"
        r"(?:USD|INR|EUR|GBP|AED|SGD)\s+"
        r"([\d,]+\.\d+)\s+"
        r"[\d,]+\.\d+\s+"
        r"([\d,]+\.\d+)\s+"
        r"[\d,]+\.\d+\s+"
        r"([\d,]+\.\d+)",
        text,
        re.IGNORECASE,
    )

    if tax_row_matches:
        taxable, cgst, total = tax_row_matches[0]

        result["TAXABLE_AMOUNT"] = clean_number(taxable)
        result["CGST"] = clean_number(cgst)
        result["SGST"] = clean_number(cgst)
        result["TOTAL_PAYABLE_AMOUNT"] = clean_number(total)

    summary_match = re.search(
        r"(?:Total|Grand\s+Total)\s*"
        r"(?:Taxable\s+Amount)?\s*"
        r"([\d,]+\.\d+)\s+"
        r"([\d,]+\.\d+)\s+"
        r"([\d,]+\.\d+)\s+"
        r"([\d,]+\.\d+)",
        text,
        re.IGNORECASE,
    )

    if summary_match:
        result["TAXABLE_AMOUNT"] = clean_number(
            summary_match.group(1)
        )
        result["CGST"] = clean_number(
            summary_match.group(2)
        )
        result["SGST"] = clean_number(
            summary_match.group(3)
        )
        result["TOTAL_PAYABLE_AMOUNT"] = clean_number(
            summary_match.group(4)
        )

    if result["TAXABLE_AMOUNT"] is None:
        taxable_match = re.search(
            r"(?:Taxable\s+Amount|Taxable)"
            r"[^\d]*([\d,]+\.\d+)",
            text,
            re.IGNORECASE,
        )

        if taxable_match:
            result["TAXABLE_AMOUNT"] = clean_number(
                taxable_match.group(1)
            )

    return result

def extract_jm_baxi(text, tables):
    result = get_empty_result()

    invoice_match = re.search(
        r"Invoice\s+No\s*:\s*([A-Z0-9\-]+)",
        text,
        re.IGNORECASE,
    )
    if invoice_match:
        result["INVOICE_NO"] = invoice_match.group(1).upper()

    date_match = re.search(
        r"Invoice\s+Date\s*:\s*(\d{1,2}-[A-Za-z]{3}-\d{4})",
        text,
        re.IGNORECASE,
    )
    if date_match:
        result["INVOICE_DATE"] = parse_date(
            date_match.group(1).upper(),
            ["%d-%b-%Y"],
        )

    irn_match = re.search(
        r"IRN\s*:\s*([A-Fa-f0-9]{64})",
        text,
        re.IGNORECASE,
    )
    if irn_match:
        result["IRN_NO"] = irn_match.group(1).lower()

    result["COMPANY"] = "J.M. BAXI & COMPANY"

    pan_match = re.search(
        r"PAN\s+No\s*:\s*([A-Z]{5}\d{4}[A-Z])",
        text,
        re.IGNORECASE,
    )
    if pan_match:
        result["PAN_NO"] = pan_match.group(1).upper()

    bl_match = re.search(
        r"BL\s+No\s*:\s*([A-Z0-9\-]+)",
        text,
        re.IGNORECASE,
    )
    if bl_match:
        result["BILL_OF_LADING"] = bl_match.group(1).upper()

    route_match = re.search(
        r"PORT\s+OF\s+LOADING\s+PORT\s+OF\s+DISCHARGE\s*"
        r"\s*1\s+1\s+"
        r"([A-Z][A-Z0-9 .&/-]*?-[A-Z0-9]+)\s+"
        r"([A-Z][A-Z ]*?)\s+"
        r"([A-Z][A-Z ]*?)(?=\s*(?:\n|Invoice|Narration|SEAWAY|Description|$))",
        text,
        re.IGNORECASE,
    )

    if route_match:
        result["VESSEL"] = clean_text(route_match.group(1))
        result["POL"] = clean_text(route_match.group(2))
        result["POD"] = clean_text(route_match.group(3))

    if result["VESSEL"] is None:
        vessel_match = re.search(
            r"\b1\s+1\s+"
            r"([A-Z][A-Z0-9 .&/-]*?-[A-Z0-9]+)"
            r"\s+[A-Z][A-Z ]+\s+[A-Z][A-Z ]+",
            text,
            re.IGNORECASE,
        )

        if vessel_match:
            result["VESSEL"] = clean_text(
                vessel_match.group(1)
            )

    if result["POL"] is None or result["POD"] is None:
        pol_pod_match = re.search(
            r"PORT\s+OF\s+LOADING\s+([A-Z][A-Z .&/-]+?)\s+"
            r"PORT\s+OF\s+DISCHARGE\s+([A-Z][A-Z .&/-]+?)"
            r"(?=\s+(?:Invoice|Narration|SEAWAY|Description)|\n|$)",
            text,
            re.IGNORECASE,
        )

        if pol_pod_match:
            if result["POL"] is None:
                result["POL"] = clean_text(
                    pol_pod_match.group(1)
                )

            if result["POD"] is None:
                result["POD"] = clean_text(
                    pol_pod_match.group(2)
                )

    container_matches = re.findall(
        r"\b[A-Z]{4}\d{7,8}\b",
        text,
        re.IGNORECASE,
    )

    if container_matches:
        unique_containers = []

        for container in container_matches:
            container = container.upper()

            if container not in unique_containers:
                unique_containers.append(container)

        result["CONTAINER_NO"] = ", ".join(
            unique_containers
        )

    charge_match = re.search(
        r"SEAWAY\s+B/L\s+CHARGES",
        text,
        re.IGNORECASE,
    )

    if charge_match:
        result["CHARGES_NAME"] = "SEAWAY B/L CHARGES"

    result["CURRENCY"] = "INR"

    taxable_match = re.search(
        r"SEAWAY\s+B/L\s+CHARGES.*?"
        r"INR\s+\d+\s+\d+\s+([\d,]+\.\d+)",
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if taxable_match:
        result["TAXABLE_AMOUNT"] = clean_number(
            taxable_match.group(1)
        )

    tax_values = re.findall(
        r"\d+(?:\.\d+)?\s+([\d,]+\.\d+)\s+"
        r"\d+(?:\.\d+)?\s+([\d,]+\.\d+)\s+"
        r"[\d,]+\.\d+",
        text,
        re.IGNORECASE,
    )

    if tax_values:
        result["CGST"] = clean_number(
            tax_values[0][0]
        )
        result["SGST"] = clean_number(
            tax_values[0][1]
        )

    total_match = re.search(
        r"Total\s*:\s*SIX\s+THOUSAND.*?"
        r"([\d,]+\.\d+)\s+([\d,]+\.\d+)\s+"
        r"([\d,]+\.\d+)\s+([\d,]+\.\d+)\s+"
        r"([\d,]+\.\d+)",
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if total_match:
        result["TOTAL_PAYABLE_AMOUNT"] = clean_number(
            total_match.group(5)
        )

    return result

def extract_nhava_sheva(text, tables):
    result = get_empty_result()

    invoice_match = re.search(
        r"Tax\s+Invoice\s+No\.\s*:\s*([A-Z]{2}-\d+)",
        text,
        re.IGNORECASE
    )

    if invoice_match:
        result["INVOICE_NO"] = invoice_match.group(1).strip()

    date_match = re.search(
        r"Tax\s+Invoice\s+Date\s*:\s*(\d{2}-[A-Za-z]{3}-\d{4})",
        text,
        re.IGNORECASE
    )

    if date_match:
        try:
            result["INVOICE_DATE"] = datetime.strptime(
                date_match.group(1).title(),
                "%d-%b-%Y"
            ).strftime("%Y-%m-%d")
        except ValueError:
            pass

    result["COMPANY"] = "Nhava Sheva International Container Terminal Pvt. Ltd."

    pan_match = re.search(
        r"PAN\s+No\s*:\s*([A-Z]{5}\d{4}[A-Z])",
        text,
        re.IGNORECASE
    )

    if pan_match:
        result["PAN_NO"] = pan_match.group(1).upper()

    irn_match = re.search(
        r"GOV\s+IRN\s*:\s*([A-Fa-f0-9]{64})",
        text,
        re.IGNORECASE
    )

    if irn_match:
        result["IRN_NO"] = irn_match.group(1).lower()

    vessel_match = re.search(
        r"Vessel\s*:\s*([^/\r\n]+)",
        text,
        re.IGNORECASE
    )

    if vessel_match:
        vessel = clean_text(vessel_match.group(1))
        vessel = re.sub(
            r"\s*/\s*[A-Z0-9-]+$",
            "",
            vessel,
            flags=re.IGNORECASE
        )
        result["VESSEL"] = vessel

    containers = re.findall(
        r"\b[A-Z]{4}\s*\d{7}\b",
        text,
        re.IGNORECASE
    )

    if containers:
        result["CONTAINER_NO"] = ",".join(
            dict.fromkeys(
                re.sub(
                    r"\s+",
                    "",
                    container
                ).upper()
                for container in containers
            )
        )

    charge_names = []
    currencies = []

    header_match = re.search(
        r"Code\s+Description\s+Qty\s+Tariff\s+Ex\.?Rate\s+Amount\s+in\s+[₹$]",
        text,
        re.IGNORECASE
    )

    if header_match:
        charge_start = header_match.end()

        subtotal_match = re.search(
            r"\bSub\s+Total\s*:",
            text[charge_start:],
            re.IGNORECASE
        )

        if subtotal_match:
            charge_block = text[
                charge_start:
                charge_start + subtotal_match.start()
            ]
        else:
            charge_block = text[charge_start:]

        tariff_matches = list(
            re.finditer(
                r"\b[A-Z]{3,8}\d{1,4}\b",
                charge_block,
                re.IGNORECASE
            )
        )

        for index, tariff_match in enumerate(tariff_matches):
            start = tariff_match.end()

            if index + 1 < len(tariff_matches):
                end = tariff_matches[index + 1].start()
            else:
                end = len(charge_block)

            row = charge_block[start:end]
            row = clean_text(row)

            if not row:
                continue

            quantity_match = re.search(
                r"\s+(\d+(?:\.\d+)?)\s+[₹$]",
                row
            )

            if quantity_match:
                description = row[:quantity_match.start()]
            else:
                description = row

            description = clean_text(description)

            description = re.sub(
                r"\s+[₹$]\s+[\d,]+\.\d+.*$",
                "",
                description
            )

            description = clean_text(description)

            if description:
                charge_names.append(description)

            if "₹" in row:
                currencies.append("INR")
            elif "$" in row:
                currencies.append("USD")

    if charge_names:
        result["CHARGES_NAME"] = ", ".join(
            dict.fromkeys(charge_names)
        )

    if currencies:
        result["CURRENCY"] = ", ".join(
            dict.fromkeys(currencies)
        )
    taxable_match = re.search(
        r"Sub\s+Total\s*:\s*([\d,]+\.\d+)",
        text,
        re.IGNORECASE
    )

    if taxable_match:
        result["TAXABLE_AMOUNT"] = clean_number(
            taxable_match.group(1)
        )

    cgst_match = re.search(
        r"CGST@\s*\(\s*\d+(?:\.\d+)?%\s*\)\s*:\s*"
        r"([\d,]+\.\d+)",
        text,
        re.IGNORECASE
    )

    if cgst_match:
        result["CGST"] = clean_number(
            cgst_match.group(1)
        )

    sgst_match = re.search(
        r"SGST@\s*\(\s*\d+(?:\.\d+)?%\s*\)\s*:\s*"
        r"([\d,]+\.\d+)",
        text,
        re.IGNORECASE
    )

    if sgst_match:
        result["SGST"] = clean_number(
            sgst_match.group(1)
        )

    total_match = re.search(
        r"Grand\s+Total\s*:\s*([\d,]+\.\d+)",
        text,
        re.IGNORECASE
    )

    if total_match:
        result["TOTAL_PAYABLE_AMOUNT"] = clean_number(
            total_match.group(1)
        )

    return result

def extract_mundra(text, tables):
    result = get_empty_result()

    invoice_date_match = re.search(
    r"Invoice\s+Date\s*:\s*(\d{2}-[A-Za-z]{3}-\d{4})",
    text,
    re.IGNORECASE
)

    if invoice_date_match:
      result["INVOICE_DATE"] = datetime.strptime(
        invoice_date_match.group(1).upper(),
        "%d-%b-%Y"
    ).strftime("%Y-%m-%d")

    result["COMPANY"] = "Mundra International Container Terminal Pvt. Ltd."

    pan_match = re.search(
        r"PAN\s*:\s*([A-Z]{5}\d{4}[A-Z])",
        text,
        re.IGNORECASE
    )

    if pan_match:
        result["PAN_NO"] = pan_match.group(1).upper()

    irn_match = re.search(
        r"GOV\s+IRN\s*:\s*([A-Fa-f0-9]{64})",
        text,
        re.IGNORECASE
    )

    if irn_match:
        result["IRN_NO"] = irn_match.group(1).lower()

    vessel_match = re.search(
        r"Vessel\s*:\s*([^/\r\n]+)\s*/\s*[A-Z0-9-]+",
        text,
        re.IGNORECASE
    )

    if vessel_match:
        result["VESSEL"] = clean_text(
            vessel_match.group(1)
        )

    charge_block = ""

    charge_header_match = re.search(
        r"Code\s+Description\s+Qty\s+Tariff\s+Ex\.Rate\s+Amount\s+in\s+[₹$]",
        text,
        re.IGNORECASE
    )

    if charge_header_match:
        charge_start = charge_header_match.end()

        subtotal_match = re.search(
            r"\bSub\s+Total\s*:",
            text[charge_start:],
            re.IGNORECASE
        )

        if subtotal_match:
            charge_block = text[
                charge_start:
                charge_start + subtotal_match.start()
            ]
        else:
            charge_block = text[charge_start:]

    if charge_block:
        charge_matches = re.finditer(
            r"\b[A-Z0-9]+\s+"
            r"(.+?)\s+"
            r"\d+(?:\.\d+)?\s+"
            r"([$₹])\s*"
            r"[\d,]+\.\d+\s+"
            r"[\d,]+\.\d+\s+"
            r"[\d,]+\.\d+",
            charge_block,
            re.IGNORECASE
        )

        charge_names = []
        currencies = []

        for match in charge_matches:
            description = clean_text(
                match.group(1)
            )

            if description:
                charge_names.append(description)

            currency_symbol = match.group(2)

            if currency_symbol == "$":
                currencies.append("USD")
            elif currency_symbol == "₹":
                currencies.append("INR")

        if charge_names:
            result["CHARGES_NAME"] = ", ".join(
                dict.fromkeys(charge_names)
            )

        if currencies:
            result["CURRENCY"] = ", ".join(
                dict.fromkeys(currencies)
            )

    taxable_match = re.search(
        r"Sub\s+Total\s*:\s*([\d,]+\.\d+)",
        text,
        re.IGNORECASE
    )

    if taxable_match:
        result["TAXABLE_AMOUNT"] = clean_number(
            taxable_match.group(1)
        )

    cgst_match = re.search(
        r"Central\s+GST\s*@\s*9%\s*:\s*([\d,]+\.\d+)",
        text,
        re.IGNORECASE
    )

    if cgst_match:
        result["CGST"] = clean_number(
            cgst_match.group(1)
        )

    sgst_match = re.search(
        r"State\s+GST\s*@\s*9%\s*:\s*([\d,]+\.\d+)",
        text,
        re.IGNORECASE
    )

    if sgst_match:
        result["SGST"] = clean_number(
            sgst_match.group(1)
        )

    total_match = re.search(
        r"Grand\s+Total\s*:\s*([\d,]+\.\d+)",
        text,
        re.IGNORECASE
    )

    if total_match:
        result["TOTAL_PAYABLE_AMOUNT"] = clean_number(
            total_match.group(1)
        )

    return result 

def extract_msc(text, tables=None):
    result = get_empty_result()

    result["COMPANY"] = "MSC Mediterranean Shipping Company S.A"

    invoice_match = re.search(
        r"Client\s+no\s*:\s*Invoice\s+no\s*:\s*Invoice\s+date\s*:\s*Due\s+date\s*:\s*"
        r"\s*\d+\s+([A-Z0-9][A-Z0-9./_-]*)\s+"
        r"(\d{2}-[A-Za-z]{3}-\d{4})\s+"
        r"(\d{2}-[A-Za-z]{3}-\d{4})",
        text,
        re.IGNORECASE
    )

    if invoice_match:
        result["INVOICE_NO"] = invoice_match.group(1).strip()

        result["INVOICE_DATE"] = datetime.strptime(
            invoice_match.group(2).upper(),
            "%d-%b-%Y"
        ).strftime("%Y-%m-%d")

        result["DUE_DATE"] = datetime.strptime(
            invoice_match.group(3).upper(),
            "%d-%b-%Y"
        ).strftime("%Y-%m-%d")

    irn_match = re.search(
        r"\bIRN\s*:\s*([a-f0-9]{64})\b",
        text,
        re.IGNORECASE
    )

    if irn_match:
        result["IRN_NO"] = irn_match.group(1).lower()

    pan_match = re.search(
        r"\bPAN\s*:\s*([A-Z]{5}\d{4}[A-Z])\b",
        text,
        re.IGNORECASE
    )

    if pan_match:
        result["PAN_NO"] = pan_match.group(1).upper()

    route_header_match = re.search(
        r"Vessel\s*:\s*Voy\s*:\s*POL\s*:\s*POD\s*:\s*B/L\s*No\s*:\s*HBL\s*No\s*:\s*",
        text,
        re.IGNORECASE
    )

    if route_header_match:
        route_start = route_header_match.end()

        route_text = text[route_start:]

        charge_header_match = re.search(
            r"Charge\s+HSN\s+Code",
            route_text,
            re.IGNORECASE
        )

        if charge_header_match:
            route_text = route_text[:charge_header_match.start()]

        route_text = clean_text(route_text)

        voyage_match = re.search(
            r"\b[A-Z]{2}\d{3}[A-Z]\b",
            route_text,
            re.IGNORECASE
        )

        if voyage_match:
            vessel = clean_text(
                route_text[:voyage_match.start()]
            )

            remaining = clean_text(
                route_text[voyage_match.end():]
            )

            bl_match = re.search(
                r"\b[A-Z]{4}[A-Z0-9]{6,12}\b",
                remaining,
                re.IGNORECASE
            )

            if bl_match:
                middle = clean_text(
                    remaining[:bl_match.start()]
                )

                result["BILL_OF_LADING"] = bl_match.group(0).upper()

                middle_match = re.match(
                    r"(.+?)\s+(Nhava\s+Sheva)\s+(.+)$",
                    middle,
                    re.IGNORECASE
                )

                if middle_match:
                    result["VESSEL"] = vessel
                    result["POL"] = clean_text(
                        middle_match.group(2)
                    )
                    result["POD"] = clean_text(
                        middle_match.group(3)
                    )
                else:
                    middle_parts = middle.split()

                    if len(middle_parts) >= 3:
                        result["VESSEL"] = vessel
                        result["POL"] = " ".join(
                            middle_parts[:2]
                        )
                        result["POD"] = " ".join(
                            middle_parts[2:]
                        )

    container_header_match = re.search(
        r"Container\s+Container\s+Type",
        text,
        re.IGNORECASE
    )

    if container_header_match:
        container_block = text[
            container_header_match.end():
        ]

        container_end_match = re.search(
            r"(?:Total|Taxable|Payment|Terms|Page\s+\d+)",
            container_block,
            re.IGNORECASE
        )

        if container_end_match:
            container_block = container_block[
                :container_end_match.start()
            ]

        containers = re.findall(
            r"\b[A-Z]{4}\d{7}\b",
            container_block,
            re.IGNORECASE
        )

        if containers:
            result["CONTAINER_NO"] = ",".join(
                dict.fromkeys(
                    container.upper()
                    for container in containers
                )
            )

    charge_header_match = re.search(
        r"Charge\s+HSN\s+Code\s+Qty\s+x\s+Rate\s+Curr\.\s+Total\s+Curr\.\s+ROE\s+TOTAL\s+INR",
        text,
        re.IGNORECASE
    )

    charge_names = []
    currencies = []
    cgst_values = []
    sgst_values = []

    if charge_header_match:
        charge_block = text[
            charge_header_match.end():
        ]

        charge_end_match = re.search(
            r"Taxable\s+Value\s*\(INR\)",
            charge_block,
            re.IGNORECASE
        )

        if charge_end_match:
            charge_block = charge_block[
                :charge_end_match.start()
            ]

        charge_block = re.sub(
            r"%\s*Amount\s+%\s*Amount\s+%\s*Amount",
            " ",
            charge_block,
            flags=re.IGNORECASE
        )

        row_pattern = re.compile(
            r"([A-Z][A-Z0-9 &/\-]*?)\s+"
            r"\d{6}\s+"
            r"\d+(?:\.\d+)?\s+x\s+"
            r"[\d,]+(?:\.\d+)?\s+"
            r"(USD|INR|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)\s+"
            r"[\d,]+(?:\.\d+)?\s+"
            r"[\d,]+(?:\.\d+)?\s+"
            r"[\d,]+(?:\.\d+)?\s+"
            r"(\d+(?:\.\d+)?)\s+"
            r"([\d,]+\.\d+)\s+"
            r"(\d+(?:\.\d+)?)\s+"
            r"([\d,]+\.\d+)\s+"
            r"0\.0\s+"
            r"[\d,]+\.\d+",
            re.IGNORECASE
        )

        matches = list(row_pattern.finditer(charge_block))

        for index, match in enumerate(matches):
            description = clean_text(
                match.group(1)
            )

            if index + 1 < len(matches):
                between = charge_block[
                    match.end():
                    matches[index + 1].start()
                ]

                continuation = clean_text(
                    between
                )

                if continuation:
                    continuation = re.sub(
                        r"\s+",
                        " ",
                        continuation
                    )

                    if continuation.upper() != "TOTAL":
                        description = clean_text(
                            description + " " + continuation
                        )

            charge_names.append(description)

            currencies.append(
                match.group(2).upper()
            )

            cgst_values.append(
                clean_number(match.group(4))
            )

            sgst_values.append(
                clean_number(match.group(6))
            )

    if charge_names:
        cleaned_charge_names = []

        for charge in charge_names:
            charge = re.sub(
                r"^%\s*Amount\s+%\s*Amount\s+%\s*Amount\s*",
                "",
                charge,
                flags=re.IGNORECASE
            )

            charge = clean_text(charge)

            if charge:
                cleaned_charge_names.append(charge)

        if cleaned_charge_names:
            result["CHARGES_NAME"] = ", ".join(
                dict.fromkeys(cleaned_charge_names)
            )

    if currencies:
        result["CURRENCY"] = ", ".join(
            dict.fromkeys(currencies)
        )

    cgst_values = [
        value for value in cgst_values
        if value is not None
    ]

    sgst_values = [
        value for value in sgst_values
        if value is not None
    ]

    if cgst_values:
        result["CGST"] = round(
            sum(cgst_values),
            2
        )

    if sgst_values:
        result["SGST"] = round(
            sum(sgst_values),
            2
        )

    taxable_match = re.search(
        r"Taxable\s+Value\s*\(INR\)\s*:\s*([\d,]+\.\d+)",
        text,
        re.IGNORECASE
    )

    if taxable_match:
        result["TAXABLE_AMOUNT"] = clean_number(
            taxable_match.group(1)
        )

    total_match = re.search(
        r"Total\s+Invoice\s+Amount\s+INR\s*:\s*([\d,]+\.\d+)",
        text,
        re.IGNORECASE
    )

    if total_match:
        result["TOTAL_PAYABLE_AMOUNT"] = clean_number(
            total_match.group(1)
        )

    return result

def extract_nhava_sheva_freeport(text, tables=None):
    result = get_empty_result()

    text = clean_text(text)

    result["COMPANY"] = "Nhava Sheva Freeport Terminal Private Limited"

    pan_match = re.search(
        r"\bPAN\s*:?\s*([A-Z]{5}\d{4}[A-Z])\b",
        text,
        re.IGNORECASE
    )

    if pan_match:
        result["PAN_NO"] = pan_match.group(1).upper()

    invoice_match = re.search(
        r"Invoice\s+No\.?\s*:?\s*([A-Z0-9-]+)",
        text,
        re.IGNORECASE
    )

    if invoice_match:
        result["INVOICE_NO"] = invoice_match.group(1).strip()

    invoice_date_match = re.search(
        r"Invoice\s+Date\s*:?\s*(\d{2}/\d{2}/\d{4})",
        text,
        re.IGNORECASE
    )

    if invoice_date_match:
        try:
            result["INVOICE_DATE"] = datetime.strptime(
                invoice_date_match.group(1),
                "%d/%m/%Y"
            ).strftime("%Y-%m-%d")
        except:
            pass

    irn_match = re.search(
        r"IRN\s*:\s*([a-f0-9]+)",
        text,
        re.IGNORECASE
    )

    if irn_match:
        first_part = irn_match.group(1)

        if len(first_part) == 64:
            result["IRN_NO"] = first_part.lower()
        else:
            remaining_text = text[
                irn_match.end():
                irn_match.end() + 500
            ]

            hex_parts = re.findall(
                r"\b[a-f0-9]{2,64}\b",
                remaining_text,
                re.IGNORECASE
            )

            for part in hex_parts:
                combined = first_part + part

                if len(combined) == 64 and re.fullmatch(
                    r"[a-f0-9]{64}",
                    combined,
                    re.IGNORECASE
                ):
                    result["IRN_NO"] = combined.lower()
                    break

    vessel_match = re.search(
        r"Vessel\s+Name\s*:\s*(.+?)\s+A\.T\.A\.",
        text,
        re.IGNORECASE
    )

    if vessel_match:
        result["VESSEL"] = clean_text(
            vessel_match.group(1)
        )

    charge_names = []
    currencies = []

    charge_start_match = re.search(
        r"Sr\.\s*No\s+Description\s+of\s+Goods/Service",
        text,
        re.IGNORECASE
    )

    if charge_start_match:
        charge_block = text[charge_start_match.end():]

        charge_end_match = re.search(
            r"\bGST\s+Total\s+18%\s*:",
            charge_block,
            re.IGNORECASE
        )

        if charge_end_match:
            charge_block = charge_block[:charge_end_match.start()]

        charge_matches = re.finditer(
            r"\b\d+\s+"
            r"(.+?)\s+"
            r"\d+(?:\.\d+)?\s+"
            r"[\d,]+(?:\.\d+)?\s+"
            r"[\d,]+(?:\.\d+)?\s+"
            r"(USD|INR)\s+"
            r"\d+\s+"
            r"[\d,]+(?:\.\d+)?\s+"
            r"[\d,]+(?:\.\d+)?",
            charge_block,
            re.IGNORECASE
        )

        for match in charge_matches:
            description = clean_text(match.group(1))
            currency = match.group(2).upper()

            if description:
                charge_names.append(description)

            if currency not in currencies:
                currencies.append(currency)

    if charge_names:
        result["CHARGES_NAME"] = ", ".join(
            dict.fromkeys(charge_names)
        )

    if currencies:
        result["CURRENCY"] = ", ".join(
            dict.fromkeys(currencies)
        )

    cgst_match = re.search(
        r"CGST\s+9%\s*:\s*([\d,]+(?:\.\d+)?)",
        text,
        re.IGNORECASE
    )

    if cgst_match:
        result["CGST"] = clean_number(
            cgst_match.group(1)
        )

    sgst_match = re.search(
        r"SGST\s+9%\s*:\s*([\d,]+(?:\.\d+)?)",
        text,
        re.IGNORECASE
    )

    if sgst_match:
        result["SGST"] = clean_number(
            sgst_match.group(1)
        )

    taxable_match = re.search(
        r"\bTotal\s*:\s*([\d,]+(?:\.\d+)?)",
        text,
        re.IGNORECASE
    )

    if taxable_match:
        result["TAXABLE_AMOUNT"] = clean_number(
            taxable_match.group(1)
        )

    total_match = re.search(
        r"Total\s+Invoice\s+Amount\s*\(\s*INR\s*\)\s*:\s*"
        r"([\d,]+(?:\.\d+)?)",
        text,
        re.IGNORECASE
    )

    if total_match:
        result["TOTAL_PAYABLE_AMOUNT"] = clean_number(
            total_match.group(1)
        )

    return result

def extract_oasis_shipping(text, tables):
    result = get_empty_result()

    invoice_match = re.search(
        r"TO\s+INVOICE\s+NO\s*:\s*([A-Z0-9./_-]+)",
        text,
        re.IGNORECASE
    )
    if invoice_match:
        result["INVOICE_NO"] = invoice_match.group(1).strip()

    date_match = re.search(
        r"Invoice\s+Date\s*:\s*(\d{2}-[A-Za-z]{3}-\d{2})",
        text,
        re.IGNORECASE
    )
    if date_match:
        try:
            result["INVOICE_DATE"] = datetime.strptime(
                date_match.group(1).upper(),
                "%d-%b-%y"
            ).strftime("%Y-%m-%d")
        except ValueError:
            pass

    irn_match = re.search(
        r"\bIRN\s*:\s*([a-f0-9\s]{64,})",
        text,
        re.IGNORECASE
    )
    if irn_match:
        irn = re.sub(r"\s+", "", irn_match.group(1))
        clean_irn = re.match(r"[a-f0-9]{64}", irn, re.IGNORECASE)
        if clean_irn:
            result["IRN_NO"] = clean_irn.group(0).lower()

    gst_match = re.search(
        r"GST\s+No\s*:\s*\d{2}([A-Z]{5}\d{4}[A-Z])\d?Z\d?",
        text,
        re.IGNORECASE
    )
    if gst_match:
        result["PAN_NO"] = gst_match.group(1).upper()

    if re.search(
        r"OASIS\s+SHIPPING\s+PVT\.\s+LTD\.",
        text,
        re.IGNORECASE
    ):
        result["COMPANY"] = "OASIS SHIPPING PVT. LTD."

    bl_match = re.search(
        r"BL\s+Number\s*:\s*([A-Z0-9./_-]+)",
        text,
        re.IGNORECASE
    )
    if bl_match:
        result["BILL_OF_LADING"] = bl_match.group(1).strip()

    vessel_match = re.search(
        r"VESSEL\s*/\s*VOYAGE\s*:\s*(.*?)\s*/\s*[A-Z0-9]+",
        text,
        re.IGNORECASE
    )
    if vessel_match:
        result["VESSEL"] = clean_text(vessel_match.group(1))

    pol_match = re.search(
        r"PORT\s+OF\s+LOADING\s*:\s*(.*?)"
        r"PORT\s+OF\s+DISCHARGE\s*:",
        text,
        re.IGNORECASE
    )
    if pol_match:
        result["POL"] = clean_text(pol_match.group(1))

    pod_match = re.search(
        r"PORT\s+OF\s+DISCHARGE\s*:\s*(.*?)"
        r"PORT\s+OF\s+DESTINATION\s*:",
        text,
        re.IGNORECASE
    )
    if pod_match:
        result["POD"] = clean_text(pod_match.group(1))

    currency_pattern = (
        r"\b(USD|INR|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|"
        r"MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)\b"
    )

    charge_section_match = re.search(
        r"SAC\s+Code\s*Charge\s+Desc.*?"
        r"(?=\bTax\s+Breakup\b|\bTotal\b|\bIn\s+Words\b)",
        text,
        re.IGNORECASE
    )

    charge_section = (
        charge_section_match.group(0)
        if charge_section_match
        else ""
    )

    charge_pattern = re.compile(
        r"\b\d{6}\s+"
        r"(.*?)"
        r"\s+"
        + currency_pattern +
        r"\s+"
        r".*?"
        r"\b\d[\d,]*\.\d{2}\b"
        r"(?:\s+.*?)?"
        r"(?=\s+\b\d{6}\b|\s+\bTotal\b|\s+\bTax\s+Breakup\b|\s+\bIn\s+Words\b|$)",
        re.IGNORECASE
    )

    charge_names = []
    currencies = []

    if charge_section:
        rows = re.findall(
            r"\b\d{6}\s+(.*?)(?=\s+\b\d{6}\b|\s+\bTotal\b|\s+\bTax\s+Breakup\b|\s+\bIn\s+Words\b|$)",
            charge_section,
            re.IGNORECASE
        )

        for row in rows:
            row = clean_text(row)

            currency_match = re.search(
                currency_pattern,
                row,
                re.IGNORECASE
            )

            if not currency_match:
                continue

            currency = currency_match.group(1).upper()

            if currency not in currencies:
                currencies.append(currency)

            before_currency = row[:currency_match.start()].strip()
            after_currency = row[currency_match.end():].strip()

            numeric_matches = list(
                re.finditer(
                    r"\b\d[\d,]*\.\d{2}\b",
                    after_currency
                )
            )

            continuation = ""

            if numeric_matches:
                continuation = after_currency[
                    numeric_matches[-1].end():
                ].strip()

            continuation = clean_text(continuation)

            continuation = re.sub(
                r"THIS\s+INVOICE\s+IS\s+ISSUED.*$",
                "",
                continuation,
                flags=re.IGNORECASE
            )

            description = clean_text(before_currency)

            if continuation:
                description = clean_text(
                    description + " " + continuation
                )

            description = re.sub(
                r"\s*-\s*Mundra\b",
                "- Mundra",
                description,
                flags=re.IGNORECASE
            )

            description = re.sub(
                r"\s*-\s*Mumbai\b",
                "- Mumbai",
                description,
                flags=re.IGNORECASE
            )

            description = re.sub(
                r"\s*-\s*Prepaid\b",
                "- Prepaid",
                description,
                flags=re.IGNORECASE
            )

            if description and description not in charge_names:
                charge_names.append(description)

    if charge_names:
        result["CHARGES_NAME"] = ", ".join(charge_names)

    if currencies:
        result["CURRENCY"] = ", ".join(currencies)

    tax_breakup_match = re.search(
        r"Tax\s+Breakup(.*?)(?=\bTotal\b|\bIn\s+Words\b)",
        text,
        re.IGNORECASE
    )

    tax_section = (
        tax_breakup_match.group(1)
        if tax_breakup_match
        else ""
    )

    cgst_values = re.findall(
        r"CGST.*?(\d[\d,]*\.\d{2})",
        tax_section,
        re.IGNORECASE
    )

    sgst_values = re.findall(
        r"SGST.*?(\d[\d,]*\.\d{2})",
        tax_section,
        re.IGNORECASE
    )

    if cgst_values:
        result["CGST"] = round(
            sum(float(value.replace(",", "")) for value in cgst_values),
            2
        )

    if sgst_values:
        result["SGST"] = round(
            sum(float(value.replace(",", "")) for value in sgst_values),
            2
        )

    taxable_match = re.search(
        r"\bTotal\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})",
        text,
        re.IGNORECASE
    )

    if taxable_match:
        result["TAXABLE_AMOUNT"] = float(
            taxable_match.group(1).replace(",", "")
        )

    total_match = re.search(
        r"In\s+Words\s*:.*?\b(\d[\d,]*\.\d{2})\b",
        text,
        re.IGNORECASE
    )

    if total_match:
        result["TOTAL_PAYABLE_AMOUNT"] = float(
            total_match.group(1).replace(",", "")
        )

    return result

def extract_ocean_generation_shipping(text, tables):
    result = get_empty_result()

    invoice_match = re.search(
        r"Invoice\s+No\s*:\s*(?:\n\s*)?([A-Z0-9][A-Z0-9./_-]*)",
        text,
        re.IGNORECASE
    )

    if invoice_match:
        invoice_value = invoice_match.group(1).strip()

        if invoice_value.upper() not in {
            "REFERENCE",
            "LIMITED",
            "DATE",
            "INVOICE",
            "NO"
        }:
            result["INVOICE_NO"] = invoice_value

    date_match = re.search(
        r"(?:Invoice\s+Date|Date)\s*:\s*(\d{2}-\d{2}-\d{4})",
        text,
        re.IGNORECASE
    )

    if date_match:
        try:
            result["INVOICE_DATE"] = datetime.strptime(
                date_match.group(1),
                "%d-%m-%Y"
            ).strftime("%Y-%m-%d")
        except ValueError:
            pass

    irn_match = re.search(
        r"\bIRN\s*:\s*([a-f0-9]{64})\b",
        text,
        re.IGNORECASE
    )

    if irn_match:
        result["IRN_NO"] = irn_match.group(1).lower()

    company_match = re.search(
        r"Bill\s+To\s*:\s*"
        r"(OCEAN\s+GENERATION\s+SHIPPING\s+PVT\.\s+LTD\.)",
        text,
        re.IGNORECASE
    )

    if company_match:
        result["COMPANY"] = clean_text(
            company_match.group(1)
        )

    pan_match = re.search(
        r"PAN\s*#\s*([A-Z]{5}\d{4}[A-Z])",
        text,
        re.IGNORECASE
    )

    if pan_match:
        result["PAN_NO"] = pan_match.group(1).upper()

    bl_match = re.search(
        r"B/L\s+No\./Date\s*:.*?"
        r"([A-Z0-9./_-]+)\s*/\s*\d{2}-\d{2}-\d{4}",
        text,
        re.IGNORECASE | re.DOTALL
    )

    if bl_match:
        result["BILL_OF_LADING"] = bl_match.group(1).strip()

    vessel_match = re.search(
        r"Vessel\s+Name/Voy\s*:\s*(.*?)"
        r"\s*/\s*[A-Z0-9]+",
        text,
        re.IGNORECASE
    )

    if vessel_match:
        result["VESSEL"] = clean_text(
            vessel_match.group(1)
        )

    container_section_match = re.search(
        r"Container\s+No\s*:\s*(.*?)"
        r"(?=Non\s+Taxable\s+Taxable|"
        r"SN\s+Charge\s+Description|"
        r"TOTAL\s+[\d,]+\.\d+\s+[\d,]+\.\d+)",
        text,
        re.IGNORECASE | re.DOTALL
    )

    if container_section_match:
        container_section = container_section_match.group(1)

        containers = re.findall(
            r"\b[A-Z]{4}\d{7}\b",
            container_section,
            re.IGNORECASE
        )

        if containers:
            result["CONTAINER_NO"] = ",".join(
                dict.fromkeys(
                    container.upper()
                    for container in containers
                )
            )

    pol_match = re.search(
        r"Port\s+of\s+Loading\s*:\s*(.*?)"
        r"\s+Final\s+Destination\s*:",
        text,
        re.IGNORECASE
    )

    if pol_match:
        result["POL"] = clean_text(
            pol_match.group(1)
        )

    pod_match = re.search(
        r"Final\s+Destination\s*:\s*(.*?)"
        r"(?=\s+Vessel\s+Name/Voy\s*:)",
        text,
        re.IGNORECASE
    )

    if pod_match:
        result["POD"] = clean_text(
            pod_match.group(1)
        )

    charge_section_match = re.search(
        r"SN\s+Charge\s+Description\s+.*?"
        r"TOTAL\s+[\d,]+\.\d+\s+[\d,]+\.\d+",
        text,
        re.IGNORECASE | re.DOTALL
    )

    charge_names = []
    currencies = []

    if charge_section_match:
        charge_section = charge_section_match.group(0)

        charge_rows = re.findall(
            r"(?:^|\s)(\d+)\s+"
            r"(.+?)\s+"
            r"(996\d{3})\s+"
            r"[\d.]+\s+"
            r"(USD|INR|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|"
            r"MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)\s+"
            r"[\d,.]+\s+"
            r"[\d.]+\s+"
            r"[\d,.]+",
            charge_section,
            re.IGNORECASE
        )

        for row in charge_rows:
            description = clean_text(row[1])
            currency = row[3].upper()

            if description and description not in charge_names:
                charge_names.append(description)

            if currency not in currencies:
                currencies.append(currency)

    if charge_names:
        result["CHARGES_NAME"] = ", ".join(
            charge_names
        )

    if currencies:
        result["CURRENCY"] = ", ".join(
            currencies
        )

    gst_match = re.search(
        r"CGST\s+(\d+)\.\s*"
        r"SGST\s+(\d+)\.\s*"
        r"GST\s*"
        r"([\d,]+\.\d+)\s*"
        r"(\d+)\s+(\d+)",
        text,
        re.IGNORECASE
    )

    if gst_match:
        cgst_integer = int(gst_match.group(1))
        sgst_integer = int(gst_match.group(2))

        cgst_decimal = int(gst_match.group(4))
        sgst_decimal = int(gst_match.group(5))

        result["CGST"] = float(
            f"{cgst_integer}.{cgst_decimal:02d}"
        )

        result["SGST"] = float(
            f"{sgst_integer}.{sgst_decimal:02d}"
        )

    taxable_match = re.search(
        r"\bTOTAL\s+[\d,]+\.\d+\s+([\d,]+\.\d+)",
        text,
        re.IGNORECASE
    )

    if taxable_match:
        result["TAXABLE_AMOUNT"] = float(
            taxable_match.group(1).replace(",", "")
        )

    total_match = re.search(
        r"Total\s+invoice\s+value\s+\(in\s+figure\)\s+INR\s+"
        r"([\d,]+\.\d+)",
        text,
        re.IGNORECASE
    )

    if total_match:
        result["TOTAL_PAYABLE_AMOUNT"] = float(
            total_match.group(1).replace(",", "")
        )

    return result

def extract_one_invoice_no(text):
    patterns = [
        r"\bInvoice\s+No\s+([A-Z]{2}\d{8,})\b",
        r"\bInvoice\s+No\s*:\s*([A-Z0-9\-]+)\b",
        r"\bInvoice\s+No\.\s*:\s*([A-Z0-9\-]+)\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            value = clean_text(match.group(1))

            if value:
                return value

    return None


def parse_one_date(value):
    value = clean_text(value)
    formats = [
        "%d%b%Y",
        "%d%b%y",
        "%d-%b-%Y",
        "%d-%b-%y",
        "%d/%m/%Y",
        "%d/%m/%y",
        "%d-%m-%Y",
        "%d-%m-%y",
        "%Y%m%d",
        "%Y-%m-%d",
        "%d %b %Y",
        "%d %b %y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    return None


def extract_one_invoice_date(text):
    patterns = [
        r"\bIssue\s+Date\s+([0-9]{1,2}[A-Za-z]{3}[0-9]{2,4})\b",
        r"\bIssue\s+date\s+([0-9]{1,2}[A-Za-z]{3}[0-9]{2,4})\b",
        r"\bInvoice\s+Date\s*[:\-]?\s*([0-9]{1,2}[A-Za-z]{3}[0-9]{2,4})\b",
        r"\bInvoice\s+Date\s*[:\-]?\s*([0-9]{1,2}[/-][A-Za-z0-9]+[/-][0-9]{2,4})\b",
        r"\bIssue\s+Date\s*[:\-]?\s*([0-9]{1,2}[/-][A-Za-z0-9]+[/-][0-9]{2,4})\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = parse_one_date(match.group(1))
            if value:
                return value

    return None


def extract_one_due_date(text):
    patterns = [
        r"\bDue\s+Date\s+([0-9]{1,2}[A-Za-z]{3}[0-9]{2,4})\b",
        r"\bDue\s+date\s+([0-9]{1,2}[A-Za-z]{3}[0-9]{2,4})\b",
        r"\bDue\s+Date\s*[:\-]?\s*([0-9]{8})\b",
        r"\bDue\s+Date\s*[:\-]?\s*([0-9]{1,2}[/-][A-Za-z0-9]+[/-][0-9]{2,4})\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = parse_one_date(match.group(1))
            if value:
                return value

    return None

def extract_one_irn(text):
    patterns = [
        r"\bIRN\s*(?:NO|No|no)?\s*[:\-]?\s*([a-fA-F0-9]{64})\b",
        r"\bIRN\s*[:\-]?\s*([a-fA-F0-9]{64})\b",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE | re.DOTALL
        )

        if match:
            value = re.sub(r"\s+", "", match.group(1))

            if len(value) == 64:
                return value.lower()

    return None


def extract_one_company(text):
    patterns = [
        r"Customer\s+Name,\s*(SARJAK\s+CONTAINER\s+LINES\s+PRIVATE\s+LIMITED)",
        r"Customer\s+Name,\s*(SARJAK\s+CONTAINER\s+LINES\s+PVT\s+LTD)",
        r"Customer\s+Name,\s*(SARJAK\s+CONTAINER\s+LINES\s+PVT\.?\s*LTD\.?)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            return clean_text(match.group(1)).upper()

    return None


def extract_one_pan(text):
    patterns = [
        r"Customer\s+PAN\s+([A-Z]{5}\d{4}[A-Z])",
        r"Customer\s+PAN\s*[:\-]?\s*([A-Z]{5}\d{4}[A-Z])",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            return match.group(1).upper()

    return None


def extract_one_bl(text):
    patterns = [
        r"Reference\s+B/L\s+No\s+([A-Z0-9\-]+)",
        r"Reference\s+B/L\s+No\s*[:\-]?\s*([A-Z0-9\-]+)",
        r"B/L\s+Number\s+([A-Z0-9\-]+)",
        r"B/L\s+No\s*[:\-]?\s*([A-Z0-9\-]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            value = match.group(1).strip()

            if value.upper() not in {"NO", "NUMBER"}:
                return value

    return None


def extract_one_vessel(text, table_parts):
    for table in table_parts:
        if not re.search(r"Vessel\s+Name", table, re.IGNORECASE):
            continue

        match = re.search(
            r"Vessel\s+Name(?:\s*\|\s*)+([A-Z0-9][A-Z0-9 .&'()/\-]*?)(?:\s*\|\s*)+Invoice\s+No",
            table,
            re.IGNORECASE,
        )

        if match:
            vessel = clean_text(match.group(1))

            if vessel:
                return vessel

    patterns = [
        r"\bVessel\s+Name\s*:\s*([A-Z][A-Z0-9 .&'()/\-]+?)(?=\s+(?:Invoice|Voy|Issue|Reference|Port|Due)\b)",
        r"\bVessel\s*:\s*([A-Z][A-Z0-9 .&'()/\-]+?)(?=\s+(?:Voy|Invoice|Issue|Reference|Port|Due)\b)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            vessel = clean_text(match.group(1))

            if vessel:
                return vessel

    return None


def extract_one_route(text):
    match = re.search(
        r"Port\s+From/To\s+([A-Z0-9]+)\s*/\s*([A-Z0-9]+)",
        text,
        re.IGNORECASE,
    )

    if match:
        return (
            match.group(1).upper(),
            match.group(2).upper()
        )

    match = re.search(
        r"Port\s+From\s*/\s*To\s+([A-Z0-9]+)\s*/\s*([A-Z0-9]+)",
        text,
        re.IGNORECASE,
    )

    if match:
        return (
            match.group(1).upper(),
            match.group(2).upper()
        )

    return None, None


def extract_one_containers(text, table_parts):
    containers = []

    match = re.search(
        r"CONTAINER\s+NO\s*:\s*(.*?)(?=\n[A-Z][A-Z ]{2,}:|\Z)",
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if match:
        containers.extend(
            re.findall(
                r"\b[A-Z]{4}\d{7}\b",
                match.group(1),
                re.IGNORECASE,
            )
        )

    if not containers:
        for table in table_parts:
            if re.search(r"CONTAINER\s+NO", table, re.IGNORECASE):
                containers.extend(
                    re.findall(
                        r"\b[A-Z]{4}\d{7}\b",
                        table,
                        re.IGNORECASE,
                    )
                )

    cleaned = []

    for value in containers:
        value = value.upper()

        if value not in cleaned:
            cleaned.append(value)

    return ",".join(cleaned) if cleaned else None


def extract_one_dt_containers(text, table_parts):
    containers = []

    for table in table_parts:
        found = re.findall(
            r"\b[A-Z]{4}\d{7}\b",
            table,
            re.IGNORECASE,
        )

        for value in found:
            value = value.upper()

            if value not in containers:
                containers.append(value)

    if not containers:
        found = re.findall(
            r"\b[A-Z]{4}\d{7}\b",
            text,
            re.IGNORECASE,
        )

        for value in found:
            value = value.upper()

            if value not in containers:
                containers.append(value)

    return ",".join(containers) if containers else None


def extract_one_charges(text, table_parts):
    charge_codes = {
        "OFT",
        "EFS",
        "CSS",
        "SLF",
        "THL",
        "DOC",
        "LIO",
        "DTH",
        "DTOC",
        "DTC",
        "DEM",
        "DET",
        "PSS",
        "CAF",
        "BAF",
        "AMS",
        "ENS",
        "ISPS",
        "PCS",
        "WRS",
        "ERS",
        "IMO",
        "SEAL",
        "HANDLING",
        "FREIGHT"
    }

    charges = []

    for table_text in table_parts:
        if not table_text:
            continue

        lines = table_text.splitlines()

        for line in lines:
            line = clean_text(line)

            if not line:
                continue

            line = line.replace("|", " ")

            match = re.search(
                r"\b([A-Z]{2,6})\s+(.+?)(?=\s+\d{4,}\b|\s+[A-Z]\d\b|\s+\d[\d,]*\.\d{2}\b|$)",
                line,
                re.I
            )

            if not match:
                continue

            code = match.group(1).upper()
            description = clean_text(match.group(2))

            if code not in charge_codes:
                continue

            if not description:
                continue

            description = re.sub(r"\s+", " ", description).strip()

            value = f"{code} {description}"

            if value not in charges:
                charges.append(value)

    if not charges:
        for line in text.splitlines():
            line = clean_text(line)

            if not line:
                continue

            match = re.search(
                r"\b([A-Z]{2,6})\s+([A-Z][A-Z0-9 /&()'\-]+?)(?=\s+\d{4,}\b|\s+\d[\d,]*\.\d{2}\b|$)",
                line,
                re.I
            )

            if not match:
                continue

            code = match.group(1).upper()
            description = clean_text(match.group(2))

            if code not in charge_codes:
                continue

            value = f"{code} {description}"

            if value not in charges:
                charges.append(value)

    return ",".join(charges) if charges else None

def extract_one_dt_charge(text):
    match = re.search(
        r"\bCharge\s+([A-Z0-9]+)\b",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).upper()

    return None


def extract_one_currency(text, table_parts):
    currencies = []

    pattern = (
        r"\b(?:USD|INR|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|"
        r"HKD|MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)\b"
    )

    for match in re.finditer(
        pattern,
        text,
        re.IGNORECASE,
    ):
        value = match.group(0).upper()

        if value not in currencies:
            currencies.append(value)

    return ", ".join(currencies) if currencies else None


def extract_one_tax(text, table_parts):
    cgst = None
    sgst = None
    taxable = None
    total = None

    cgst_match = re.search(
        r"\bCGST\s+INR\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)",
        text,
        re.IGNORECASE,
    )

    if cgst_match:
        taxable = clean_number(cgst_match.group(1))
        cgst = clean_number(cgst_match.group(2))

    sgst_match = re.search(
        r"\bSGST\s*/\s*UGST\s+INR\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)",
        text,
        re.IGNORECASE,
    )

    if sgst_match:
        if taxable is None:
            taxable = clean_number(sgst_match.group(1))

        sgst = clean_number(sgst_match.group(2))

    total_match = re.search(
        r"Total\s+Invoice\s+Value\s*\(in\s+figure\)\s+([\d,]+\.\d+)",
        text,
        re.IGNORECASE,
    )

    if total_match:
        total = clean_number(total_match.group(1))

    if cgst is None or sgst is None or taxable is None or total is None:
        for table in table_parts:
            for line in table.splitlines():
                normalized = clean_text(line)

                values = re.findall(
                    r"\d[\d,]*\.\d{2}",
                    normalized,
                )

                if re.search(r"\bCGST\b", normalized, re.IGNORECASE):
                    if len(values) >= 2:
                        if taxable is None:
                            taxable = clean_number(values[0])

                        if cgst is None:
                            cgst = clean_number(values[-1])

                if re.search(
                    r"\bSGST\s*/\s*UGST\b",
                    normalized,
                    re.IGNORECASE,
                ):
                    if len(values) >= 2:
                        if taxable is None:
                            taxable = clean_number(values[0])

                        if sgst is None:
                            sgst = clean_number(values[-1])

                if re.search(
                    r"Total\s+Invoice\s+Value\s*\(in\s+figure\)",
                    normalized,
                    re.IGNORECASE,
                ):
                    if values and total is None:
                        total = clean_number(values[-1])

    return cgst, sgst, taxable, total


def extract_one_dt_tax(text, table_parts):
    cgst = None
    sgst = None
    taxable = None
    total = None

    for table in table_parts:
        for line in table.splitlines():
            normalized = clean_text(line)

            values = re.findall(
                r"\d[\d,]*\.\d{2}",
                normalized,
            )

            if re.search(r"\bCGST\b", normalized, re.IGNORECASE):
                if len(values) >= 2:
                    taxable = clean_number(values[-2])
                    cgst = clean_number(values[-1])

            if re.search(
                r"\bSGST\s*/\s*UGST\b",
                normalized,
                re.IGNORECASE,
            ):
                if len(values) >= 2:
                    if taxable is None:
                        taxable = clean_number(values[-2])

                    sgst = clean_number(values[-1])

            if re.search(
                r"Total\s+Invoice\s+Value\s*\(in\s+figure\)",
                normalized,
                re.IGNORECASE,
            ):
                if values:
                    total = clean_number(values[-1])

    if cgst is None:
        match = re.search(
            r"\bCGST\s+INR\s+[\d,]+\.\d+\s+([\d,]+\.\d+)",
            text,
            re.IGNORECASE,
        )

        if match:
            cgst = clean_number(match.group(1))

    if sgst is None:
        match = re.search(
            r"\bSGST\s*/\s*UGST\s+INR\s+[\d,]+\.\d+\s+([\d,]+\.\d+)",
            text,
            re.IGNORECASE,
        )

        if match:
            sgst = clean_number(match.group(1))

    if taxable is None:
        match = re.search(
            r"\bCGST\s+INR\s+([\d,]+\.\d+)",
            text,
            re.IGNORECASE,
        )

        if match:
            taxable = clean_number(match.group(1))

    if total is None:
        match = re.search(
            r"Total\s+Invoice\s+Value\s*\(in\s+figure\)\s+([\d,]+\.\d+)",
            text,
            re.IGNORECASE,
        )

        if match:
            total = clean_number(match.group(1))

    return cgst, sgst, taxable, total


def extract_one(text, table_parts):
    result = get_empty_result()

    if re.search(
        r"\*\*\*\s*TAX\s+INVOICE\s*\(\s*DETENTION\s*\)",
        text,
        re.IGNORECASE,
    ):
        document_type = "DT_INV"
    elif re.search(
        r"\bCharge\s+DTOC\b",
        text,
        re.IGNORECASE,
    ):
        document_type = "DT_INV"
    elif re.search(
        r"\bShipping\s+Instruction\b",
        text,
        re.IGNORECASE,
    ):
        document_type = "SI"
    elif re.search(
        r"\bSI\s+ONELINE\b",
        text,
        re.IGNORECASE,
    ):
        document_type = "SI"
    elif re.search(
        r"\bTAX\s+INVOICE\b",
        text,
        re.IGNORECASE,
    ):
        document_type = "FR_INV"
    else:
        document_type = "FR_INV"

    if document_type == "SI":
        return result

    result["INVOICE_NO"] = extract_one_invoice_no(text)
    result["INVOICE_DATE"] = extract_one_invoice_date(text)
    result["DUE_DATE"] = extract_one_due_date(text)
    result["IRN_NO"] = extract_one_irn(text)
    result["COMPANY"] = extract_one_company(text)
    result["PAN_NO"] = extract_one_pan(text)
    result["BILL_OF_LADING"] = extract_one_bl(text)
    result["VESSEL"] = extract_one_vessel(text, table_parts)

    pol, pod = extract_one_route(text)

    result["POL"] = pol
    result["POD"] = pod

    if document_type == "DT_INV":
        result["CONTAINER_NO"] = extract_one_dt_containers(
            text,
            table_parts
        )

        result["CHARGES_NAME"] = extract_one_dt_charge(text)
        result["CURRENCY"] = extract_one_currency(
            text,
            table_parts
        )

        cgst, sgst, taxable, total = extract_one_dt_tax(
            text,
            table_parts
        )

    else:
        result["CONTAINER_NO"] = extract_one_containers(
            text,
            table_parts
        )

        result["CHARGES_NAME"] = extract_one_charges(
            text,
            table_parts
        )

        result["CURRENCY"] = extract_one_currency(
            text,
            table_parts
        )

        cgst, sgst, taxable, total = extract_one_tax(
            text,
            table_parts
        )

    result["CGST"] = cgst
    result["SGST"] = sgst
    result["TAXABLE_AMOUNT"] = taxable
    result["TOTAL_PAYABLE_AMOUNT"] = total

    return result

def get_oocl_header_rows(table_text):
    rows = []

    if not table_text:
        return rows

    for line in str(table_text).splitlines():
        line = clean_text(line)

        if not line:
            continue

        cells = [
            clean_text(cell)
            for cell in line.split("|")
        ]

        rows.append(cells)

    return rows


def find_oocl_header_table(table_parts):
    best_rows = []

    for table_text in table_parts:
        rows = get_oocl_header_rows(table_text)

        if not rows:
            continue

        source = " ".join(
            " ".join(row)
            for row in rows
        ).upper()

        score = 0

        for keyword in [
            "BILL OF LADING",
            "VESSEL",
            "PORT OF LOADING",
            "PORT OF DISCHARGE",
            "DESCRIPTION",
            "CONTAINER",
        ]:
            if keyword in source:
                score += 1

        if score >= 2 and len(rows) > len(best_rows):
            best_rows = rows

    return best_rows


def extract_oocl_company(text, table_parts):
    source = "\n".join(
        str(table)
        for table in table_parts
    )

    if re.search(
        r"Orient\s+Overseas\s+Container\s+Line\s+Limited",
        source,
        re.IGNORECASE,
    ):
        return "Orient Overseas Container Line Limited"

    if re.search(
        r"Orient\s+Overseas\s+Container\s+Line\s+Limited",
        text,
        re.IGNORECASE,
    ):
        return "Orient Overseas Container Line Limited"

    return None


def extract_oocl_header_fields(table_parts):
    result = {
        "BILL_OF_LADING": None,
        "VESSEL": None,
        "POL": None,
        "POD": None,
    }

    rows = find_oocl_header_table(table_parts)

    if not rows:
        return result

    normalized_rows = []

    for row in rows:
        normalized_rows.append(
            [
                clean_text(cell)
                for cell in row
            ]
        )

    for row_index, row in enumerate(normalized_rows):
        row_text = " ".join(row)

        if result["BILL_OF_LADING"] is None:
            match = re.search(
                r"BILL\s+OF\s+LADING\s*[:\-]?\s*([A-Z0-9\-\/]+)",
                row_text,
                re.IGNORECASE,
            )

            if match:
                result["BILL_OF_LADING"] = clean_text(
                    match.group(1)
                )

        if result["VESSEL"] is None:
            match = re.search(
                r"VESSEL\s*[:\-]?\s*([A-Z0-9 .'\-\/]+)",
                row_text,
                re.IGNORECASE,
            )

            if match:
                vessel = clean_text(
                    match.group(1)
                )

                vessel = re.split(
                    r"\b(?:PORT|DESCRIPTION|CONTAINER|BILL)\b",
                    vessel,
                    flags=re.IGNORECASE,
                )[0]

                if vessel:
                    result["VESSEL"] = vessel

        if result["POL"] is None:
            match = re.search(
                r"PORT\s+OF\s+LOADING\s*[:\-]?\s*(.+)",
                row_text,
                re.IGNORECASE,
            )

            if match:
                value = clean_text(
                    match.group(1)
                )

                value = re.split(
                    r"\bPORT\s+OF\s+DISCHARGE\b",
                    value,
                    flags=re.IGNORECASE,
                )[0]

                if value:
                    result["POL"] = value

        if result["POD"] is None:
            match = re.search(
                r"PORT\s+OF\s+DISCHARGE\s*[:\-]?\s*(.+)",
                row_text,
                re.IGNORECASE,
            )

            if match:
                value = clean_text(
                    match.group(1)
                )

                if value:
                    result["POD"] = value

        if len(row) >= 2:
            for index, cell in enumerate(row):
                cell_upper = cell.upper()

                if result["BILL_OF_LADING"] is None and re.search(
                    r"BILL\s+OF\s+LADING",
                    cell_upper,
                ):
                    if index + 1 < len(row):
                        candidate = clean_text(
                            row[index + 1]
                        )

                        if candidate and not re.search(
                            r"VESSEL|PORT|DESCRIPTION|CONTAINER",
                            candidate,
                            re.IGNORECASE,
                        ):
                            result["BILL_OF_LADING"] = candidate

                if result["VESSEL"] is None and re.fullmatch(
                    r"VESSEL",
                    cell_upper,
                ):
                    if index + 1 < len(row):
                        candidate = clean_text(
                            row[index + 1]
                        )

                        if candidate:
                            result["VESSEL"] = candidate

                if result["POL"] is None and re.search(
                    r"PORT\s+OF\s+LOADING",
                    cell_upper,
                ):
                    if index + 1 < len(row):
                        candidate = clean_text(
                            row[index + 1]
                        )

                        if candidate:
                            result["POL"] = candidate

                if result["POD"] is None and re.search(
                    r"PORT\s+OF\s+DISCHARGE",
                    cell_upper,
                ):
                    if index + 1 < len(row):
                        candidate = clean_text(
                            row[index + 1]
                        )

                        if candidate:
                            result["POD"] = candidate

        if row_index + 1 < len(normalized_rows):
            next_row = normalized_rows[row_index + 1]

            for index, cell in enumerate(row):
                cell_upper = cell.upper()

                if result["BILL_OF_LADING"] is None and re.search(
                    r"BILL\s+OF\s+LADING",
                    cell_upper,
                ):
                    if index < len(next_row):
                        candidate = clean_text(
                            next_row[index]
                        )

                        if candidate:
                            result["BILL_OF_LADING"] = candidate

                if result["VESSEL"] is None and re.fullmatch(
                    r"VESSEL",
                    cell_upper,
                ):
                    if index < len(next_row):
                        candidate = clean_text(
                            next_row[index]
                        )

                        if candidate:
                            result["VESSEL"] = candidate

                if result["POL"] is None and re.search(
                    r"PORT\s+OF\s+LOADING",
                    cell_upper,
                ):
                    if index < len(next_row):
                        candidate = clean_text(
                            next_row[index]
                        )

                        if candidate:
                            result["POL"] = candidate

                if result["POD"] is None and re.search(
                    r"PORT\s+OF\s+DISCHARGE",
                    cell_upper,
                ):
                    if index < len(next_row):
                        candidate = clean_text(
                            next_row[index]
                        )

                        if candidate:
                            result["POD"] = candidate

    return result


def extract_oocl_invoice_no(text):
    patterns = [
        r"INVOICE\s*NO\.?\s*:\s*([0-9A-Z][0-9A-Z \-/]{4,30})",
        r"INVOICE\s*NO\.?\s+([0-9A-Z][0-9A-Z \-/]{4,30})",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match:
            value = clean_text(
                match.group(1)
            )

            value = re.split(
                r"\b(?:ISSUE\s*DATE|DUE\s*DATE|TAX\s*INVOICE|INVOICE\s*TO)\b",
                value,
                flags=re.IGNORECASE,
            )[0]

            value = clean_text(value)

            if value:
                return value

    return None


def extract_oocl_invoice_date(text):
    patterns = [
        r"ISSUE\s*DATE\s*:\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
        r"ISSUE\s*DATE\s*:\s*(\d{1,2}[-/]\s*[A-Za-z0-9]{3,9}[-/]\s*\d{4})",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match:
            value = parse_date(
                match.group(1),
                [
                    "%d %b %Y",
                    "%d %B %Y",
                    "%d-%b-%Y",
                    "%d-%B-%Y",
                    "%d/%m/%Y",
                ],
            )

            if value:
                return value

    return None


def extract_oocl_due_date(text):
    patterns = [
        r"DUE\s*DATE\s*:\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
        r"DUE\s*DATE\s*:\s*(\d{1,2}[-/]\s*[A-Za-z0-9]{3,9}[-/]\s*\d{4})",
        r"DUE\s*DATE\s*:\s*(\d{8})",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match:
            value = parse_date(
                match.group(1),
                [
                    "%d %b %Y",
                    "%d %B %Y",
                    "%d-%b-%Y",
                    "%d-%B-%Y",
                    "%d/%m/%Y",
                    "%Y%m%d",
                ],
            )

            if value:
                return value

    return None


def extract_oocl_irn(text):
    lines = text.splitlines()

    for i, line in enumerate(lines):
        match = re.search(
            r"\bIRN\s*:\s*(.*)",
            line,
            re.IGNORECASE,
        )

        if not match:
            continue

        parts = []

        first_part = re.sub(
            r"\bRECIPIENT\b",
            "",
            match.group(1),
            flags=re.IGNORECASE,
        )

        first_part = re.sub(
            r"\s+",
            "",
            first_part,
        )

        if re.fullmatch(
            r"[0-9A-Fa-f]+",
            first_part,
        ):
            parts.append(first_part)

        for j in range(
            i + 1,
            min(i + 12, len(lines)),
        ):
            current = lines[j].strip()

            if not current:
                continue

            current = re.sub(
                r"\bRECIPIENT\b",
                "",
                current,
                flags=re.IGNORECASE,
            )

            current = re.sub(
                r"\s+",
                "",
                current,
            )

            if not current:
                continue

            if re.fullmatch(
                r"[0-9A-Fa-f]+",
                current,
            ):
                parts.append(current)

                combined = "".join(parts)

                if len(combined) >= 64:
                    return combined[:64].lower()

                continue

            if re.search(
                r"\bPAGE\s*NO\b|\bINVOICE\s*NO\b|\bISSUE\s*DATE\b|\bDUE\s*DATE\b",
                current,
                re.IGNORECASE,
            ):
                break

            if parts:
                break

        combined = "".join(parts)

        if combined:
            return combined.lower()

    return None


def extract_oocl_pan(text):
    match = re.search(
        r"\bPAN\s*(?:NO\.?)?\s*:\s*([A-Z]{5}\d{4}[A-Z])",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).upper()

    match = re.search(
        r"\bPAN\s+(?:NO\.?)?\s+([A-Z]{5}\d{4}[A-Z])",
        text,
        re.IGNORECASE,
    )

    if match:
        return match.group(1).upper()

    return None


def extract_oocl_containers(text):
    containers = re.findall(
        r"\b[A-Z]{4}\d{7}\b",
        text.upper(),
    )

    if not containers:
        return None

    return ",".join(
        dict.fromkeys(containers)
    )


def extract_oocl_charges(text, table_parts):
    source = text + "\n" + "\n".join(
        str(table)
        for table in table_parts
    )

    charge_names = [
        "OCEAN FREIGHT",
        "ORIG TRML HANDLG",
        "TOLL CHARGE ORIG",
        "GATE IN CHARGE",
        "O/B DOC FEE",
        "DETENTION CHRG",
        "HI SEC SEAL CHG",
        "TRUCK OVERTIME",
        "DOC FEE",
    ]

    charges = []

    for charge in charge_names:
        if re.search(
            r"\b" + re.escape(charge) + r"\b",
            source,
            re.IGNORECASE,
        ):
            if charge not in charges:
                charges.append(charge)

    return ",".join(charges) if charges else None


def extract_oocl_currency(text):
    currencies = []

    for currency in [
        "INR",
        "USD",
        "EUR",
        "GBP",
        "AED",
    ]:
        if re.search(
            r"\b" + currency + r"\b",
            text,
            re.IGNORECASE,
        ):
            currencies.append(currency)

    return ", ".join(currencies) if currencies else None


def extract_oocl_tax(text):
    taxable = None
    combined_gst = None
    total = None

    match = re.search(
        r"\bSUB[\-\s]*TOTAL\b\s+([0-9][0-9,]*\.\d{2})",
        text,
        re.IGNORECASE,
    )

    if match:
        taxable = clean_number(
            match.group(1)
        )

    match = re.search(
        r"\bCGST\s*\+\s*SGST\b\s+([0-9][0-9,]*\.\d{2})",
        text,
        re.IGNORECASE,
    )

    if match:
        combined_gst = clean_number(
            match.group(1)
        )

    match = re.search(
        r"\bAMOUNT\s+DUE\s+(?:INR|USD|EUR|GBP|AED)?\s*"
        r"([0-9][0-9,]*\.\d{2})",
        text,
        re.IGNORECASE,
    )

    if match:
        total = clean_number(
            match.group(1)
        )

    if taxable is not None and combined_gst is not None:
        cgst = round(
            combined_gst / 2,
            2,
        )

        sgst = round(
            combined_gst - cgst,
            2,
        )

        return cgst, sgst, taxable, total

    if taxable is not None and total is not None:
        combined_gst = round(
            total - taxable,
            2,
        )

        if combined_gst >= 0:
            cgst = round(
                combined_gst / 2,
                2,
            )

            sgst = round(
                combined_gst - cgst,
                2,
            )

            return cgst, sgst, taxable, total

    return None, None, taxable, total


def extract_oocl(text, table_parts):
    result = get_empty_result()

    source_text = text or ""

    table_source = "\n".join(
        str(table)
        for table in table_parts
        if table
    )

    combined_source = source_text + "\n" + table_source

    def clean_oocl_value(value):
        if value is None:
            return None

        value = str(value)
        value = value.replace("\xa0", " ")
        value = re.sub(r"\s+", " ", value)
        value = value.strip(" |:-")

        return value if value else None

    def extract_invoice_no():
        patterns = [
            r"\bINVOICE\s*NO\.?\s*:\s*(\d{3}\s+\d{6}[A-Z])\b",
            r"\bINVOICE\s*NO\.?\s+(\d{3}\s+\d{6}[A-Z])\b",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                combined_source,
                re.IGNORECASE,
            )

            if match:
                return clean_oocl_value(
                    match.group(1)
                )

        return None

    def extract_invoice_date():
        patterns = [
            r"\bISSUE\s*DATE\s*:\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
            r"\bISSUE\s*DATE\s*:\s*(\d{1,2}[-/][A-Za-z]{3,9}[-/]\d{4})",
            r"\bISSUE\s*DATE\s*:\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                combined_source,
                re.IGNORECASE,
            )

            if match:
                parsed = parse_date(
                    match.group(1),
                    [
                        "%d %b %Y",
                        "%d %B %Y",
                        "%d-%b-%Y",
                        "%d-%B-%Y",
                        "%d/%b/%Y",
                        "%d/%B/%Y",
                        "%d/%m/%Y",
                    ],
                )

                if parsed:
                    return parsed

        return None

    def extract_due_date():
        patterns = [
            r"\bDUE\s*DATE\s*:\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
            r"\bDUE\s*DATE\s*:\s*(\d{1,2}[-/][A-Za-z]{3,9}[-/]\d{4})",
            r"\bDUE\s*DATE\s*:\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})",
            r"\bDUE\s*DATE\s*:\s*(\d{8})",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                combined_source,
                re.IGNORECASE,
            )

            if match:
                parsed = parse_date(
                    match.group(1),
                    [
                        "%d %b %Y",
                        "%d %B %Y",
                        "%d-%b-%Y",
                        "%d-%B-%Y",
                        "%d/%b/%Y",
                        "%d/%B/%Y",
                        "%d/%m/%Y",
                        "%Y%m%d",
                    ],
                )

                if parsed:
                    return parsed

        return None

    def extract_irn():
        lines = combined_source.splitlines()

        for index, line in enumerate(lines):
            if not re.search(
                r"\bIRN\b",
                line,
                re.IGNORECASE,
            ):
                continue

            after_irn = re.split(
                r"\bIRN\b\s*:?",
                line,
                maxsplit=1,
                flags=re.IGNORECASE,
            )

            fragments = []

            if len(after_irn) == 2:
                first = after_irn[1]

                first = re.sub(
                    r"\bRECIPIENT\b",
                    "",
                    first,
                    flags=re.IGNORECASE,
                )

                first = re.sub(
                    r"[^0-9A-Fa-f]",
                    "",
                    first,
                )

                if first:
                    fragments.append(first)

            for next_index in range(
                index + 1,
                min(index + 15, len(lines)),
            ):
                current = lines[next_index].strip()

                if not current:
                    continue

                if re.search(
                    r"\b(?:INVOICE\s*NO|ISSUE\s*DATE|DUE\s*DATE|PAGE\s*NO|INVOICE\s*TO)\b",
                    current,
                    re.IGNORECASE,
                ):
                    break

                current = re.sub(
                    r"\bRECIPIENT\b",
                    "",
                    current,
                    flags=re.IGNORECASE,
                )

                fragment = re.sub(
                    r"[^0-9A-Fa-f]",
                    "",
                    current,
                )

                if not fragment:
                    continue

                if len(fragment) >= 8:
                    fragments.append(fragment)

                combined_irn = "".join(fragments)

                if len(combined_irn) >= 64:
                    return combined_irn[:64].lower()

            combined_irn = "".join(fragments)

            if len(combined_irn) >= 32:
                return combined_irn[:64].lower()

        return None

    def extract_company():
        match = re.search(
            r"\bOrient\s+Overseas\s+Container\s+Line\s+Limited\b",
            combined_source,
            re.IGNORECASE,
        )

        if match:
            return "Orient Overseas Container Line Limited"

        return None

    def extract_pan():
        match = re.search(
            r"\bPAN\s*(?:NO\.?)?\s*[:\-]?\s*([A-Z]{5}\d{4}[A-Z])\b",
            combined_source,
            re.IGNORECASE,
        )

        if match:
            return match.group(1).upper()

        return None

    def extract_bl():
        patterns = [
            r"\bBILL\s+OF\s+LADING\s*[:\-]?\s*(\d{8,15})\b",
            r"\bBILL\s+OF\s+LADING\s+(\d{8,15})\b",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                combined_source,
                re.IGNORECASE,
            )

            if match:
                value = match.group(1)

                if value.upper() not in {
                    "NO",
                    "NONE",
                }:
                    return value

        rows = get_oocl_header_rows(
            table_source
        )

        for row in rows:
            row_text = " ".join(
                clean_oocl_value(cell) or ""
                for cell in row
            )

            if not re.search(
                r"BILL\s+OF\s+LADING",
                row_text,
                re.IGNORECASE,
            ):
                continue

            numbers = re.findall(
                r"\b\d{8,15}\b",
                row_text,
            )

            if numbers:
                return numbers[0]

        return None

    def extract_vessel():
        patterns = [
            r"\bVESSEL\s+VOYAGE\s+BOUND\s+(.+?)\s+ARRIVED/DEPARTED\b",
            r"\bVESSEL\s+VOYAGE\s+BOUND\s+(.+?)\s+ARRIVED\s*/\s*DEPARTED\b",
            r"\bVESSEL\s*[:\-]?\s*([A-Z][A-Z0-9 .'\-]+?)\s+ARRIVED/DEPARTED\b",
            r"\bVESSEL\s*[:\-]?\s*([A-Z][A-Z0-9 .'\-]+?)\s+ARRIVED\s*/\s*DEPARTED\b",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                combined_source,
                re.IGNORECASE,
            )

            if match:
                value = clean_oocl_value(
                    match.group(1)
                )

                if value:
                    value = re.sub(
                        r"\bVOYAGE\s+BOUND\b",
                        "",
                        value,
                        flags=re.IGNORECASE,
                    )

                    value = clean_oocl_value(
                        value
                    )

                    if value:
                        return value

        rows = get_oocl_header_rows(
            table_source
        )

        for row in rows:
            row_text = " ".join(
                clean_oocl_value(cell) or ""
                for cell in row
            )

            match = re.search(
                r"\bVESSEL\b.*?\bBOUND\b\s+(.+?)(?:\bARRIVED\b|\bDEPARTED\b|$)",
                row_text,
                re.IGNORECASE,
            )

            if match:
                value = clean_oocl_value(
                    match.group(1)
                )

                if value:
                    return value

        return None

def extract_oocl(text, table_parts):
    result = get_empty_result()

    source_text = text or ""

    table_source = "\n".join(
        str(table)
        for table in table_parts
        if table
    )

    combined_source = source_text + "\n" + table_source

    def clean_oocl_value(value):
        if value is None:
            return None

        value = str(value)
        value = value.replace("\xa0", " ")
        value = re.sub(r"\s+", " ", value)
        value = value.strip(" |:-")

        return value if value else None

    def extract_invoice_no():
        patterns = [
            r"\bINVOICE\s*NO\.?\s*:\s*(\d{3}\s+\d{6}[A-Z])\b",
            r"\bINVOICE\s*NO\.?\s+(\d{3}\s+\d{6}[A-Z])\b",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                combined_source,
                re.IGNORECASE,
            )

            if match:
                return clean_oocl_value(
                    match.group(1)
                )

        return None

    def extract_invoice_date():
        patterns = [
            r"\bISSUE\s*DATE\s*:\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
            r"\bISSUE\s*DATE\s*:\s*(\d{1,2}[-/][A-Za-z]{3,9}[-/]\d{4})",
            r"\bISSUE\s*DATE\s*:\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                combined_source,
                re.IGNORECASE,
            )

            if match:
                parsed = parse_date(
                    match.group(1),
                    [
                        "%d %b %Y",
                        "%d %B %Y",
                        "%d-%b-%Y",
                        "%d-%B-%Y",
                        "%d/%b/%Y",
                        "%d/%B/%Y",
                        "%d/%m/%Y",
                    ],
                )

                if parsed:
                    return parsed

        return None

    def extract_due_date():
        patterns = [
            r"\bDUE\s*DATE\s*:\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})",
            r"\bDUE\s*DATE\s*:\s*(\d{1,2}[-/][A-Za-z]{3,9}[-/]\d{4})",
            r"\bDUE\s*DATE\s*:\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})",
            r"\bDUE\s*DATE\s*:\s*(\d{8})",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                combined_source,
                re.IGNORECASE,
            )

            if match:
                parsed = parse_date(
                    match.group(1),
                    [
                        "%d %b %Y",
                        "%d %B %Y",
                        "%d-%b-%Y",
                        "%d-%B-%Y",
                        "%d/%b/%Y",
                        "%d/%B/%Y",
                        "%d/%m/%Y",
                        "%Y%m%d",
                    ],
                )

                if parsed:
                    return parsed

        return None

    def extract_irn():
        lines = combined_source.splitlines()

        for index, line in enumerate(lines):
            if not re.search(
                r"\bIRN\b",
                line,
                re.IGNORECASE,
            ):
                continue

            after_irn = re.split(
                r"\bIRN\b\s*:?",
                line,
                maxsplit=1,
                flags=re.IGNORECASE,
            )

            fragments = []

            if len(after_irn) == 2:
                first = after_irn[1]

                first = re.sub(
                    r"\bRECIPIENT\b",
                    "",
                    first,
                    flags=re.IGNORECASE,
                )

                first = re.sub(
                    r"[^0-9A-Fa-f]",
                    "",
                    first,
                )

                if first:
                    fragments.append(first)

            for next_index in range(
                index + 1,
                min(index + 15, len(lines)),
            ):
                current = lines[next_index].strip()

                if not current:
                    continue

                if re.search(
                    r"\b(?:INVOICE\s*NO|ISSUE\s*DATE|DUE\s*DATE|PAGE\s*NO|INVOICE\s*TO)\b",
                    current,
                    re.IGNORECASE,
                ):
                    break

                current = re.sub(
                    r"\bRECIPIENT\b",
                    "",
                    current,
                    flags=re.IGNORECASE,
                )

                fragment = re.sub(
                    r"[^0-9A-Fa-f]",
                    "",
                    current,
                )

                if not fragment:
                    continue

                if len(fragment) >= 8:
                    fragments.append(fragment)

                combined_irn = "".join(fragments)

                if len(combined_irn) >= 64:
                    return combined_irn[:64].lower()

            combined_irn = "".join(fragments)

            if len(combined_irn) >= 32:
                return combined_irn[:64].lower()

        return None

    def extract_company():
        match = re.search(
            r"\bOrient\s+Overseas\s+Container\s+Line\s+Limited\b",
            combined_source,
            re.IGNORECASE,
        )

        if match:
            return "Orient Overseas Container Line Limited"

        return None

    def extract_pan():
        match = re.search(
            r"\bPAN\s*(?:NO\.?)?\s*[:\-]?\s*([A-Z]{5}\d{4}[A-Z])\b",
            combined_source,
            re.IGNORECASE,
        )

        if match:
            return match.group(1).upper()

        return None

    def extract_bl():
        patterns = [
            r"\bBILL\s+OF\s+LADING\s*[:\-]?\s*(\d{8,15})\b",
            r"\bBILL\s+OF\s+LADING\s+(\d{8,15})\b",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                combined_source,
                re.IGNORECASE,
            )

            if match:
                value = match.group(1)

                if value.upper() not in {
                    "NO",
                    "NONE",
                }:
                    return value

        rows = get_oocl_header_rows(
            table_source
        )

        for row in rows:
            row_text = " ".join(
                clean_oocl_value(cell) or ""
                for cell in row
            )

            if not re.search(
                r"BILL\s+OF\s+LADING",
                row_text,
                re.IGNORECASE,
            ):
                continue

            numbers = re.findall(
                r"\b\d{8,15}\b",
                row_text,
            )

            if numbers:
                return numbers[0]

        return None

    def extract_vessel():
        patterns = [
            r"\bVESSEL\s+VOYAGE\s+BOUND\s+(.+?)\s+ARRIVED/DEPARTED\b",
            r"\bVESSEL\s+VOYAGE\s+BOUND\s+(.+?)\s+ARRIVED\s*/\s*DEPARTED\b",
            r"\bVESSEL\s*[:\-]?\s*([A-Z][A-Z0-9 .'\-]+?)\s+ARRIVED/DEPARTED\b",
            r"\bVESSEL\s*[:\-]?\s*([A-Z][A-Z0-9 .'\-]+?)\s+ARRIVED\s*/\s*DEPARTED\b",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                combined_source,
                re.IGNORECASE,
            )

            if match:
                value = clean_oocl_value(
                    match.group(1)
                )

                if value:
                    value = re.sub(
                        r"\bVOYAGE\s+BOUND\b",
                        "",
                        value,
                        flags=re.IGNORECASE,
                    )

                    value = clean_oocl_value(
                        value
                    )

                    if value:
                        return value

        rows = get_oocl_header_rows(
            table_source
        )

        for row in rows:
            row_text = " ".join(
                clean_oocl_value(cell) or ""
                for cell in row
            )

            match = re.search(
                r"\bVESSEL\b.*?\bBOUND\b\s+(.+?)(?:\bARRIVED\b|\bDEPARTED\b|$)",
                row_text,
                re.IGNORECASE,
            )

            if match:
                value = clean_oocl_value(
                    match.group(1)
                )

                if value:
                    return value

        return None

    def extract_containers():
        containers = re.findall(
            r"\b[A-Z]{4}\d{7}\b",
            combined_source.upper(),
        )

        containers = list(
            dict.fromkeys(containers)
        )

        return (
            ",".join(containers)
            if containers
            else None
        )

    def extract_pol():
        known_ports = [
            "Nhava Sheva",
            "Chennai",
            "Mundra",
            "Mumbai",
            "Kolkata",
            "Kandla",
            "Pipavav",
            "Hazira",
            "Tuticorin",
            "Cochin",
            "Visakhapatnam",
            "Kattupalli",
            "Krishnapatnam",
            "Ennore",
            "Vishakhapatnam",
            "Pipavav Port",
            "Mundra Port",
            "Nhava Sheva Port",
        ]

        for table in table_parts:
            if not table:
                continue

            table_text = str(table)

            lines = [
                line.strip()
                for line in table_text.splitlines()
                if line.strip()
            ]

            for line in lines:
                clean_line = clean_oocl_value(line)

                if not clean_line:
                    continue

                if not re.search(
                    r"\bPORT\s+OF\s+LOADING\b",
                    clean_line,
                    re.IGNORECASE,
                ):
                    continue

                after_loading = re.split(
                    r"\bPORT\s+OF\s+LOADING\b",
                    clean_line,
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )

                if len(after_loading) != 2:
                    continue

                candidate = clean_oocl_value(
                    after_loading[1]
                )

                if not candidate:
                    continue

                candidate = re.split(
                    r"\bPORT\s+OF\s+DISCHARGE\b",
                    candidate,
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )[0]

                candidate = re.split(
                    r"\bFINAL\s+DESTINATION\b",
                    candidate,
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )[0]

                candidate = re.split(
                    r"\bSHIP\s+TO/BY\b",
                    candidate,
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )[0]

                candidate = clean_oocl_value(
                    candidate
                )

                if not candidate:
                    continue

                for port in known_ports:
                    if re.search(
                        r"\b" + re.escape(port) + r"\b",
                        candidate,
                        re.IGNORECASE,
                    ):
                        return port

                if "|" in line:
                    cells = [
                        clean_oocl_value(cell)
                        for cell in line.split("|")
                    ]

                    for index, cell in enumerate(cells):
                        if not cell:
                            continue

                        if re.search(
                            r"\bPORT\s+OF\s+LOADING\b",
                            cell,
                            re.IGNORECASE,
                        ):
                            if index + 1 < len(cells):
                                value = clean_oocl_value(
                                    cells[index + 1]
                                )

                                if value:
                                    for port in known_ports:
                                        if re.search(
                                            r"\b"
                                            + re.escape(port)
                                            + r"\b",
                                            value,
                                            re.IGNORECASE,
                                        ):
                                            return port

                                    if not re.search(
                                        r"\b(?:PAN|GST|SARJAK|SHIP\s+TO|FINAL\s+DESTINATION)\b",
                                        value,
                                        re.IGNORECASE,
                                    ):
                                        return value

        for line in combined_source.splitlines():
            clean_line = clean_oocl_value(line)

            if not clean_line:
                continue

            if not re.search(
                r"\bPORT\s+OF\s+LOADING\b",
                clean_line,
                re.IGNORECASE,
            ):
                continue

            for port in known_ports:
                pattern = (
                    r"\bPORT\s+OF\s+LOADING\b"
                    r".{0,120}?"
                    r"\b"
                    + re.escape(port)
                    + r"\b"
                )

                if re.search(
                    pattern,
                    clean_line,
                    re.IGNORECASE,
                ):
                    return port

        return None

    def extract_pod():
        patterns = [
            r"\bPORT\s+OF\s+DISCHARGE\s*[:\-]?\s*(.+?)(?=\s+FINAL\s+DESTINATION\b|$)",
            r"\bPORT\s+OF\s+DISCHARGE\s+(.+?)(?=\s+FINAL\s+DESTINATION\b|$)",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                combined_source,
                re.IGNORECASE,
            )

            if match:
                value = clean_oocl_value(
                    match.group(1)
                )

                if value:
                    return value

        return None

    def extract_charges():
        charge_names = [
            "OCEAN FREIGHT",
            "ORIG TRML HANDLG",
            "TOLL CHARGE ORIG",
            "GATE IN CHARGE",
            "O/B DOC FEE",
            "DETENTION CHRG",
            "HI SEC SEAL CHG",
            "TRUCK OVERTIME",
            "DOC FEE",
        ]

        charges = []

        for charge in charge_names:
            if re.search(
                r"\b" + re.escape(charge) + r"\b",
                combined_source,
                re.IGNORECASE,
            ):
                if charge not in charges:
                    charges.append(charge)

        return (
            ",".join(charges)
            if charges
            else None
        )

    def extract_currency():
        currencies = []

        for currency in [
            "INR",
            "USD",
            "EUR",
            "GBP",
            "AED",
        ]:
            if re.search(
                r"\b" + currency + r"\b",
                combined_source,
                re.IGNORECASE,
            ):
                currencies.append(currency)

        return (
            ", ".join(currencies)
            if currencies
            else None
        )

    def extract_tax():
        taxable = None
        combined_gst = None
        total = None

        match = re.search(
            r"\bSUB[\-\s]*TOTAL\b\s+([0-9][0-9,]*\.\d{2})",
            combined_source,
            re.IGNORECASE,
        )

        if match:
            taxable = clean_number(
                match.group(1)
            )

        match = re.search(
            r"\bCGST\s*\+\s*SGST\b\s+([0-9][0-9,]*\.\d{2})",
            combined_source,
            re.IGNORECASE,
        )

        if match:
            combined_gst = clean_number(
                match.group(1)
            )

        match = re.search(
            r"\bAMOUNT\s+DUE\s+(?:INR|USD|EUR|GBP|AED)?\s*"
            r"([0-9][0-9,]*\.\d{2})",
            combined_source,
            re.IGNORECASE,
        )

        if match:
            total = clean_number(
                match.group(1)
            )

        if (
            combined_gst is not None
            and taxable is not None
        ):
            cgst = round(
                combined_gst / 2,
                2,
            )

            sgst = round(
                combined_gst - cgst,
                2,
            )

            return (
                cgst,
                sgst,
                taxable,
                total,
            )

        if (
            taxable is not None
            and total is not None
        ):
            combined_gst = round(
                total - taxable,
                2,
            )

            if combined_gst >= 0:
                cgst = round(
                    combined_gst / 2,
                    2,
                )

                sgst = round(
                    combined_gst - cgst,
                    2,
                )

                return (
                    cgst,
                    sgst,
                    taxable,
                    total,
                )

        return (
            None,
            None,
            taxable,
            total,
        )

    result["INVOICE_NO"] = extract_invoice_no()
    result["INVOICE_DATE"] = extract_invoice_date()
    result["DUE_DATE"] = extract_due_date()
    result["IRN_NO"] = extract_irn()
    result["COMPANY"] = extract_company()
    result["PAN_NO"] = extract_pan()
    result["BILL_OF_LADING"] = extract_bl()
    result["VESSEL"] = extract_vessel()
    result["CONTAINER_NO"] = extract_containers()
    result["POL"] = extract_pol()
    result["POD"] = extract_pod()
    result["CHARGES_NAME"] = extract_charges()
    result["CURRENCY"] = extract_currency()

    cgst, sgst, taxable, total = extract_tax()

    result["CGST"] = cgst
    result["SGST"] = sgst
    result["TAXABLE_AMOUNT"] = taxable
    result["TOTAL_PAYABLE_AMOUNT"] = total

    return result

def extract_pil(text, table_parts):
    result = get_empty_result()

    if not text:
        return result

    source = text

    result["COMPANY"] = "PIL (INDIA) PRIVATE LIMITED"

    invoice_match = re.search(
        r"Invoice\s+No\s*:\s*([A-Z0-9]+)",
        source,
        re.IGNORECASE,
    )

    if invoice_match:
        result["INVOICE_NO"] = clean_text(invoice_match.group(1))

    invoice_date_match = re.search(
        r"Invoice\s+Date\s*:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})",
        source,
        re.IGNORECASE,
    )

    if invoice_date_match:
        result["INVOICE_DATE"] = parse_date(
            invoice_date_match.group(1),
            ["%d/%m/%Y"],
        )

    due_date_match = re.search(
        r"Invoice\s+Due\s+Date\s*:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})",
        source,
        re.IGNORECASE,
    )

    if due_date_match:
        result["DUE_DATE"] = parse_date(
            due_date_match.group(1),
            ["%d/%m/%Y"],
        )

    pan_match = re.search(
        r"Pacific\s+Intl\s+Lines\s+Private\s+Limited\s+SG\s+PAN\s*:\s*([A-Z0-9]+)",
        source,
        re.IGNORECASE,
    )

    if pan_match:
        result["PAN_NO"] = clean_text(pan_match.group(1))

    bl_match = re.search(
        r"External\s+BL\s+No\s*:\s*([A-Z0-9]+)",
        source,
        re.IGNORECASE,
    )

    if bl_match:
        result["BILL_OF_LADING"] = clean_text(bl_match.group(1))

    vessel_match = re.search(
        r"Voyage\s*:\s*[^\n]*?\s+\d{1,2}/\d{1,2}/\d{4}\s+(.+?)\s+Invoice\s+No\s*:",
        source,
        re.IGNORECASE,
    )

    if vessel_match:
        result["VESSEL"] = clean_text(vessel_match.group(1))

    container_matches = re.findall(
        r"\b[A-Z]{4}\d{7}\b",
        source,
    )

    containers = []

    for container in container_matches:
        if container not in containers:
            containers.append(container)

    if containers:
        result["CONTAINER_NO"] = ",".join(containers)

    pol_match = re.search(
        r"\bLoaded\s*:\s*(.+?)(?=\s+Invoice\s+Due\s+Date\s*:)",
        source,
        re.IGNORECASE,
    )

    if pol_match:
        result["POL"] = clean_text(pol_match.group(1))

    pod_match = re.search(
        r"\bDischarge\s*:\s*(.+?)(?=\s+External\s+BL\s+No\s*:)",
        source,
        re.IGNORECASE,
    )

    if pod_match:
        result["POD"] = clean_text(pod_match.group(1))

    charge_names = [
        "EQUIPMENT CONTAINER HANDLING (L)",
        "BASIC OCEAN FREIGHT",
        "PTCMU MISCELLANEOUS - PMS",
        "SEAL FEE CHARGE (L)",
        "SYSTEM FACILITATION FEE (L)",
        "TERMINAL HANDLING CHARGE (L)",
        "WAYBILL FEE",
    ]

    found_charges = []

    for charge in charge_names:
        if re.search(
            re.escape(charge),
            source,
            re.IGNORECASE,
        ):
            found_charges.append(charge)

    if found_charges:
        result["CHARGES_NAME"] = " | ".join(found_charges)

    currencies = []

    if re.search(r"\bUSD\b", source, re.IGNORECASE):
        currencies.append("USD")

    if re.search(r"\bINR\b", source, re.IGNORECASE):
        currencies.append("INR")

    if currencies:
        result["CURRENCY"] = ", ".join(currencies)

    taxable_match = re.search(
        r"Total\s+Amount\s+Before\s+Tax\s+[\d,]+\.\d+\s+([\d,]+\.\d+)",
        source,
        re.IGNORECASE,
    )

    if taxable_match:
        result["TAXABLE_AMOUNT"] = clean_number(
            taxable_match.group(1)
        )

    cgst_match = re.search(
        r"BCGST\d*\s*-\s*CENTRAL\s+GOODS\s+AND\s+SERVICES.*?"
        r"\d+(?:\.\d+)?%\s+[\d,]+\.\d+\s+([\d,]+\.\d+)",
        source,
        re.IGNORECASE,
    )

    if cgst_match:
        result["CGST"] = clean_number(
            cgst_match.group(1)
        )

    sgst_match = re.search(
        r"BSGST\d*\s*-\s*STATE\s+GOODS\s+AND\s+SERVICES.*?"
        r"\d+(?:\.\d+)?%\s+[\d,]+\.\d+\s+([\d,]+\.\d+)",
        source,
        re.IGNORECASE,
    )

    if sgst_match:
        result["SGST"] = clean_number(
            sgst_match.group(1)
        )

    total_match = re.search(
        r"Total\s+Amount\s+[\d,]+\.\d+\s+([\d,]+\.\d+)",
        source,
        re.IGNORECASE,
    )

    if total_match:
        result["TOTAL_PAYABLE_AMOUNT"] = clean_number(
            total_match.group(1)
        )

    return result

def extract_promise_date(value):
    value = clean_text(value)

    formats = [
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d/%m/%y",
        "%d-%m-%y",
        "%d.%m.%Y",
        "%d.%m.%y",
        "%d %B %Y",
        "%d %b %Y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except Exception:
            pass

    return None


def extract_promise_invoice_no(text):
    patterns = [
        r"\bInv\s*#\s*([A-Z0-9][A-Z0-9/_-]{5,40})",
        r"\bInvoice\s*(?:No|Number|#)\s*[:#.\-]?\s*([A-Z0-9][A-Z0-9/_-]{5,40})",
        r"\bTAX\s+INVOICE\s+Inv\s*#\s*([A-Z0-9][A-Z0-9/_-]{5,40})",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            value = m.group(1).strip()
            value = re.sub(r"[.,;:]+$", "", value)
            if value:
                return value

    return None


def extract_promise_invoice_date(text):
    patterns = [
        r"\bOriginal\s+for\s+Recipient\s+Date\s+(\d{1,2}/\d{1,2}/\d{4})",
        r"\bOriginal\s+for\s+Recipient\s+Date\s+(\d{1,2}-\d{1,2}-\d{4})",
        r"\bDate\s+(\d{1,2}/\d{1,2}/\d{4})",
        r"\bDate\s+(\d{1,2}-\d{1,2}-\d{4})",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            value = extract_promise_date(m.group(1))
            if value:
                return value

    return None


def extract_promise_due_date(text):
    patterns = [
        r"\bDue\s+Date\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{4})",
        r"\bDue\s+Date\s*[:\-]?\s*(\d{1,2}-\d{1,2}-\d{4})",
        r"\bPayment\s+Due\s*[:\-]?\s*(\d{1,2}/\d{1,2}/\d{4})",
        r"\bPayment\s+Due\s*[:\-]?\s*(\d{1,2}-\d{1,2}-\d{4})",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            value = extract_promise_date(m.group(1))
            if value:
                return value

    return None


def extract_promise_irn(text):
    patterns = [
        r"\bIRN\s*#\s*([a-fA-F0-9]{64})",
        r"\bIRN\s*(?:No|Number)?\s*[:#]?\s*([a-fA-F0-9]{64})",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            return m.group(1)

    return None


def extract_promise_company(text, table_parts):
    for source in [text] + table_parts:
        m = re.search(
            r"\b(PROMISE\s+SHIPPING\s+LINE\s+PRIVATE\s+LIMITED)\b",
            source,
            re.I
        )
        if m:
            return m.group(1).upper()

    return None


def extract_promise_pan(text, table_parts):
    sources = [text] + table_parts

    patterns = [
        r"\bPAN\s*#\s*[:\-]?\s*([A-Z]{5}\d{4}[A-Z])\b",
        r"\bPAN\s*(?:NO|NUMBER)?\s*[:#\-]?\s*([A-Z]{5}\d{4}[A-Z])\b",
        r"\bPAN\s*[:#\-]?\s*([A-Z]{5}\d{4}[A-Z])\b",
    ]

    for source in sources:
        for pattern in patterns:
            m = re.search(pattern, source, re.I)
            if m:
                return m.group(1).upper()

    return None


def extract_promise_bl(text):
    patterns = [
        r"\bBL\s*#\s*([A-Z0-9][A-Z0-9/_-]{8,40})",
        r"\bB\/L\s*#?\s*([A-Z0-9][A-Z0-9/_-]{8,40})",
        r"\bMBL\s*#?\s*([A-Z0-9][A-Z0-9/_-]{8,40})",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            value = m.group(1).strip()
            value = re.sub(r"[.,;:]+$", "", value)
            if value:
                return value

    return None


def extract_promise_vessel(text):
    patterns = [
        r"\bVessel\s+([A-Z][A-Z0-9 .'\-]{2,80}?)(?=\s+Job\s*#|\s*$)",
        r"\bVessel\s*:\s*([A-Z][A-Z0-9 .'\-]{2,80}?)(?=\s+Job\s*#|\s*$)",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, re.I | re.M)
        if m:
            value = re.sub(r"\s+", " ", m.group(1)).strip()
            value = re.sub(r"\s+Job\s*$", "", value, flags=re.I)
            if value:
                return value

    return None


def extract_promise_containers(text, table_parts):
    sources = [text] + table_parts
    found = []

    for source in sources:
        sections = re.findall(
            r"Container\s+Details(.*?)(?:Remarks|Bank\s+Details|Authorised\s+Signatory|$)",
            source,
            re.I | re.S
        )

        if sections:
            search_text = "\n".join(sections)
        else:
            search_text = source

        matches = re.findall(
            r"\b([A-Z]{4}\d{7})\b",
            search_text,
            re.I
        )

        for value in matches:
            value = value.upper()

            if value not in found:
                found.append(value)

    return ",".join(found) if found else None


def extract_promise_route(text):
    m = re.search(
        r"\bPoL\s*/\s*Pod\s+([A-Z][A-Z .'\-]{1,80}?)\s*/\s*([A-Z][A-Z .'\-]{1,80}?)(?=\s+Ex\s+rate|\s+No\s+of|\s+PoS|\s*$)",
        text,
        re.I
    )

    if m:
        pol = re.sub(r"\s+", " ", m.group(1)).strip()
        pod = re.sub(r"\s+", " ", m.group(2)).strip()

        return pol, pod

    m = re.search(
        r"\bPoL\s*/\s*Pod\s+([A-Z][A-Z .'\-]{1,80})\s*/\s*([A-Z][A-Z .'\-]{1,80})",
        text,
        re.I
    )

    if m:
        return (
            re.sub(r"\s+", " ", m.group(1)).strip(),
            re.sub(r"\s+", " ", m.group(2)).strip()
        )

    return None, None


def extract_promise_charges(text, table_parts):
    source = "\n".join([text] + table_parts)

    charge_patterns = [
        r"\bBL\s+CHARGES\b",
        r"\bSLOT\s+CHARGES\b",
        r"\bOCEAN\s+FREIGHT\s+EXPORT\b",
        r"\bTERMINAL\s+HANDLING\s+CHARGES\s+ORIGIN\b",
        r"\bTERMINAL\s+HANDLING\s+CHARGES\s+DESTINATION\b",
        r"\bMUC\s+CHARGES\b",
        r"\bWEIGHMENT\s+CHARGES\b",
        r"\bPARKING\s+CHARGES\b",
        r"\bSEAL\s+CHARGES\b",
        r"\bSURRENDER\s+FEE\b",
        r"\bPORT\s+ADDITIONAL\s+PORT\s+CHARGE\b",
        r"\bPORT\s+FEES\b",
        r"\bPORT\s+STORAGE\s+CHARGES\b",
        r"\bFEEDER\s+COST\s+RECOVERY\b",
        r"\bSSR\s+CHARGES\b",
    ]

    found = []

    for pattern in charge_patterns:
        m = re.search(pattern, source, re.I)
        if m:
            value = re.sub(r"\s+", " ", m.group(0)).strip().upper()

            if value not in found:
                found.append(value)

    return " | ".join(found) if found else None


def extract_promise_currency(text, table_parts):
    source = "\n".join([text] + table_parts)

    currencies = []

    for value in re.findall(
        r"\b(INR|USD|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)\b",
        source,
        re.I
    ):
        value = value.upper()

        if value not in currencies:
            currencies.append(value)

    return ", ".join(currencies) if currencies else None


def extract_promise_tax(text, table_parts):
    source = "\n".join([text] + table_parts)

    cgst = None
    sgst = None
    taxable = None
    total = None

    total_match = re.search(
        r"\bTotal\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})",
        source,
        re.I
    )

    if total_match:
        taxable = clean_number(total_match.group(1))
        cgst = clean_number(total_match.group(2))
        sgst = clean_number(total_match.group(3))
        total = clean_number(total_match.group(4))

        return cgst, sgst, taxable, total

    taxable_match = re.search(
        r"\bTaxable\s+([\d,]+\.\d{2})",
        source,
        re.I
    )

    if taxable_match:
        taxable = clean_number(taxable_match.group(1))

    cgst_match = re.search(
        r"\bCGST\s+([\d,]+\.\d{2})",
        source,
        re.I
    )

    if cgst_match:
        cgst = clean_number(cgst_match.group(1))

    sgst_match = re.search(
        r"\bSGST\s+([\d,]+\.\d{2})",
        source,
        re.I
    )

    if sgst_match:
        sgst = clean_number(sgst_match.group(1))

    return cgst, sgst, taxable, total


def extract_promise(text, table_parts):
    result = get_empty_result()

    if not re.search(
        r"\bPROMISE\s+SHIPPING\s+LINE\s+PRIVATE\s+LIMITED\b",
        text,
        re.I
    ):
        return result

    if not re.search(
        r"\bTAX\s+INVOICE\b",
        text,
        re.I
    ):
        return result

    result["INVOICE_NO"] = extract_promise_invoice_no(text)
    result["INVOICE_DATE"] = extract_promise_invoice_date(text)
    result["DUE_DATE"] = extract_promise_due_date(text)
    result["IRN_NO"] = extract_promise_irn(text)
    result["COMPANY"] = extract_promise_company(text, table_parts)
    result["PAN_NO"] = extract_promise_pan(text, table_parts)
    result["BILL_OF_LADING"] = extract_promise_bl(text)
    result["VESSEL"] = extract_promise_vessel(text)

    pol, pod = extract_promise_route(text)

    result["POL"] = pol
    result["POD"] = pod

    result["CONTAINER_NO"] = extract_promise_containers(
        text,
        table_parts
    )

    result["CHARGES_NAME"] = extract_promise_charges(
        text,
        table_parts
    )

    result["CURRENCY"] = extract_promise_currency(
        text,
        table_parts
    )

    cgst, sgst, taxable, total = extract_promise_tax(
        text,
        table_parts
    )

    result["CGST"] = cgst
    result["SGST"] = sgst
    result["TAXABLE_AMOUNT"] = taxable
    result["TOTAL_PAYABLE_AMOUNT"] = total

    return result

def extract_psa_invoice_no(text):
    match = re.search(
        r"INVOICE\s+NUMBER\s+.*?\n\s*([A-Z0-9/.-]+)\s+(\d{2}\.\d{2}\.\d{4})",
        text,
        re.IGNORECASE | re.DOTALL
    )

    if match:
        return match.group(1).strip()

    match = re.search(
        r"INVOICE\s+NUMBER\s*[-\s]*\n?[-\s]*\n?([A-Z0-9/.-]+)",
        text,
        re.IGNORECASE
    )

    if match:
        return match.group(1).strip()

    return None


def extract_psa_invoice_date(text):
    match = re.search(
        r"INVOICE\s+NUMBER.*?\n\s*[A-Z0-9/.-]+\s+(\d{2}\.\d{2}\.\d{4})",
        text,
        re.IGNORECASE | re.DOTALL
    )

    if match:
        return parse_date(match.group(1), ["%d.%m.%Y"])

    match = re.search(
        r"INVOICE\s+DATE\s*[-\s]*\n?[-\s]*(\d{2}\.\d{2}\.\d{4})",
        text,
        re.IGNORECASE
    )

    if match:
        return parse_date(match.group(1), ["%d.%m.%Y"])

    return None


def extract_psa_due_date(text):
    return None


def extract_psa_irn(text):
    return None


def extract_psa_company(text):
    match = re.search(
        r"^\s*(Bharat\s+Mumbai\s+Container\s+Terminals\s+Pvt\.?\s*Ltd\.?)",
        text,
        re.IGNORECASE | re.MULTILINE
    )

    if match:
        return clean_text(match.group(1))

    return None


def extract_psa_pan(text):
    match = re.search(
        r"PAN\s+No\s*:\s*([A-Z]{5}[0-9]{4}[A-Z])",
        text,
        re.IGNORECASE
    )

    if match:
        return match.group(1).upper()

    return None


def extract_psa_bl(text):
    return None


def extract_psa_vessel(table_parts, text):
    for table in table_parts:
        match = re.search(
            r"VESSEL\s+NAME\s*\n\s*([^|\n]+?)(?:\s*\||\s+ATA\b|\s+ATD\b|$)",
            table,
            re.IGNORECASE
        )

        if match:
            vessel = clean_text(match.group(1))
            if vessel:
                return vessel.upper()

    match = re.search(
        r"VESSEL\s+NAME\s*\n?\s*([^|\n]+?)(?:\s*\||\s+ATA\b|\s+ATD\b|$)",
        text,
        re.IGNORECASE
    )

    if match:
        vessel = clean_text(match.group(1))
        if vessel:
            return vessel.upper()

    return None


def extract_psa_containers(text):
    return None


def extract_psa_pol(text):
    return None


def extract_psa_pod(text):
    return None


def extract_psa_charges(table_parts, text):
    charges = []

    charge_patterns = [
        r"STEVEDORING/\s*TERMINAL\s+HANDLING\s+CHARGES\s*\(IMPORT\s*-\s*RAIL/ROAD\)",
        r"STEVEDORING/\s*TERMINAL\s+HANDLING\s+CHARGES\s*\(IMPORT\s*-\s*",
        r"STEVEDORING/\s*TERMINAL\s+HANDLING\s+CHARGES\s*\(EXPORT\s*-\s*RAIL/ROAD\)",
        r"STEVEDORING/\s*TERMINAL\s+HANDLING\s+CHARGES\s*\(EXPORT\s*-\s*",
    ]

    combined_text = "\n".join(table_parts) + "\n" + text

    for pattern in charge_patterns:
        matches = re.finditer(
            pattern,
            combined_text,
            re.IGNORECASE
        )

        for match in matches:
            charge = clean_text(match.group(0))
            charge = re.sub(r"\s+", " ", charge).strip()

            if charge not in charges:
                charges.append(charge)

    return " | ".join(charges) if charges else None


def extract_psa_currency(text):
    if re.search(r"AMOUNT\s*\(INR\)", text, re.IGNORECASE):
        return "INR"

    return None


def extract_psa_invoice_no(table_parts, text):
    for table in table_parts:
        match = re.search(
            r"INVOICE\s+NUMBER\s*\n\s*([A-Z0-9/.-]+)",
            table,
            re.IGNORECASE
        )

        if match:
            value = match.group(1).strip()

            if value.upper() not in {"INVOICE", "NUMBER", "DATE"}:
                return value

    match = re.search(
        r"INVOICE\s+NUMBER\s+INVOICE\s+DATE\s*[-\s]*\n\s*[-\s]*\n\s*([A-Z0-9/.-]+)\s+(\d{2}\.\d{2}\.\d{4})",
        text,
        re.IGNORECASE
    )

    if match:
        return match.group(1).strip()

    return None


def extract_psa_invoice_date(table_parts, text):
    for table in table_parts:
        match = re.search(
            r"INVOICE\s+DATE\s*\n\s*(\d{2}\.\d{2}\.\d{4})",
            table,
            re.IGNORECASE
        )

        if match:
            return parse_date(
                match.group(1),
                ["%d.%m.%Y"]
            )

    match = re.search(
        r"INVOICE\s+NUMBER\s+INVOICE\s+DATE\s*[-\s]*\n\s*[-\s]*\n\s*[A-Z0-9/.-]+\s+(\d{2}\.\d{2}\.\d{4})",
        text,
        re.IGNORECASE
    )

    if match:
        return parse_date(
            match.group(1),
            ["%d.%m.%Y"]
        )

    return None


def extract_psa_due_date(text):
    return None


def extract_psa_irn(text):
    return None


def extract_psa_company(text):
    return "PSA"


def extract_psa_pan(text):
    match = re.search(
        r"PAN\s+No\s*:\s*([A-Z]{5}[0-9]{4}[A-Z])",
        text,
        re.IGNORECASE
    )

    if match:
        return match.group(1).upper()

    return None


def extract_psa_bl(text):
    return None


def extract_psa_vessel(table_parts, text):
    for table in table_parts:
        match = re.search(
            r"VESSEL\s+NAME\s*\n\s*([^|\n]+?)(?:\s*\||\s+ATA\b|\s+ATD\b|$)",
            table,
            re.IGNORECASE
        )

        if match:
            vessel = clean_text(match.group(1))

            if vessel:
                return vessel.upper()

    return None


def extract_psa_containers(text):
    return None


def extract_psa_pol(text):
    return None


def extract_psa_pod(text):
    return None


def extract_psa_charges(table_parts, text):
    charges = []

    charge_patterns = [
        r"STEVEDORING/\s*TERMINAL\s+HANDLING\s+CHARGES\s*\(IMPORT\s*-\s*RAIL/ROAD\)",
        r"STEVEDORING/\s*TERMINAL\s+HANDLING\s+CHARGES\s*\(IMPORT\s*-\s*",
        r"STEVEDORING/\s*TERMINAL\s+HANDLING\s+CHARGES\s*\(EXPORT\s*-\s*RAIL/ROAD\)",
        r"STEVEDORING/\s*TERMINAL\s+HANDLING\s+CHARGES\s*\(EXPORT\s*-\s*",
    ]

    combined_text = "\n".join(table_parts) + "\n" + text

    for pattern in charge_patterns:
        matches = re.finditer(
            pattern,
            combined_text,
            re.IGNORECASE
        )

        for match in matches:
            charge = clean_text(match.group(0))
            charge = re.sub(r"\s+", " ", charge).strip()

            if charge not in charges:
                charges.append(charge)

    return " | ".join(charges) if charges else None


def extract_psa_currency(text):
    if re.search(
        r"AMOUNT\s*\(INR\)",
        text,
        re.IGNORECASE
    ):
        return "INR"

    return None


def extract_psa_tax(text):
    cgst = None
    sgst = None
    taxable = None
    total = None

    match = re.search(
        r"Total\s+Amount\s+Before\s+Tax\s+([\d,]+\.\d{2})",
        text,
        re.IGNORECASE
    )

    if match:
        taxable = clean_number(match.group(1))

    match = re.search(
        r"Add\s*:\s*CGST\s*@\s*[\d.]+%\s+([\d,]+\.\d{2})",
        text,
        re.IGNORECASE
    )

    if match:
        cgst = clean_number(match.group(1))

    match = re.search(
        r"Add\s*:\s*SGST\s*@\s*[\d.]+%\s+([\d,]+\.\d{2})",
        text,
        re.IGNORECASE
    )

    if match:
        sgst = clean_number(match.group(1))

    match = re.search(
        r"TOTAL\s+AMOUNT\s+DUE:.*?\s([\d,]+\.\d{2})",
        text,
        re.IGNORECASE | re.DOTALL
    )

    if match:
        total = clean_number(match.group(1))

    return cgst, sgst, taxable, total


def extract_psa_invoice_no(text, table_parts):
    for table in table_parts:
        match = re.search(
            r"INVOICE\s+NUMBER\s*(?:\|\s*|\n\s*)"
            r"([A-Z0-9]+/[A-Z0-9]+/[A-Z0-9]+)",
            table,
            re.IGNORECASE
        )

        if match:
            return match.group(1).strip()

    match = re.search(
        r"INVOICE\s+NUMBER\s+INVOICE\s+DATE.*?"
        r"\b([A-Z0-9]+/[A-Z0-9]+/[A-Z0-9]+)\b",
        text,
        re.IGNORECASE | re.DOTALL
    )

    if match:
        return match.group(1).strip()

    return None


def extract_psa_invoice_date(text, table_parts):
    for table in table_parts:
        match = re.search(
            r"INVOICE\s+DATE\s*(?:\|\s*|\n\s*)"
            r"(\d{2}\.\d{2}\.\d{4})",
            table,
            re.IGNORECASE
        )

        if match:
            return parse_date(
                match.group(1),
                ["%d.%m.%Y"]
            )

    match = re.search(
        r"INVOICE\s+NUMBER\s+INVOICE\s+DATE.*?"
        r"\b\d{2}\.\d{2}\.\d{4}\b",
        text,
        re.IGNORECASE | re.DOTALL
    )

    if match:
        date_match = re.search(
            r"\b(\d{2}\.\d{2}\.\d{4})\b",
            match.group(0)
        )

        if date_match:
            return parse_date(
                date_match.group(1),
                ["%d.%m.%Y"]
            )

    return None


def extract_psa_due_date(text, table_parts):
    return None


def extract_psa_irn(text, table_parts):
    return None


def extract_psa_company(text, table_parts):
    return "PSA"


def extract_psa_pan(text, table_parts):
    match = re.search(
        r"PAN\s+No\s*:\s*([A-Z]{5}[0-9]{4}[A-Z])",
        text,
        re.IGNORECASE
    )

    if match:
        return match.group(1).upper()

    return None


def extract_psa_bl(text, table_parts):
    return None


def extract_psa_vessel(text, table_parts):
    for table in table_parts:
        normalized = re.sub(r"\s+", " ", table).strip()

        match = re.search(
            r"VESSEL\s+NAME\s+(?:\|\s*)?(.+?)(?=\s+\|\s*ATA\b|\s+\|\s*ATD\b|\s+ATA\b|\s+ATD\b|$)",
            normalized,
            re.IGNORECASE
        )

        if match:
            vessel = clean_text(match.group(1))

            if vessel:
                return vessel.upper()

    normalized = re.sub(r"\s+", " ", text).strip()

    match = re.search(
        r"VESSEL\s+NAME\s+(?:\|\s*)?(.+?)(?=\s+\|\s*ATA\b|\s+\|\s*ATD\b|\s+ATA\b|\s+ATD\b|$)",
        normalized,
        re.IGNORECASE
    )

    if match:
        vessel = clean_text(match.group(1))

        if vessel:
            return vessel.upper()

    return None
def extract_psa_containers(text, table_parts):
    return None


def extract_psa_pol(text, table_parts):
    return None


def extract_psa_pod(text, table_parts):
    return None


def extract_psa_charges(text, table_parts):
    charges = []

    combined_text = "\n".join(table_parts) + "\n" + text

    patterns = [
        r"STEVEDORING\s*/\s*TERMINAL\s+HANDLING\s+CHARGES\s*\(\s*IMPORT\s*-\s*RAIL/ROAD\s*\)",
        r"STEVEDORING\s*/\s*TERMINAL\s+HANDLING\s+CHARGES\s*\(\s*IMPORT\s*-\s*",
        r"STEVEDORING\s*/\s*TERMINAL\s+HANDLING\s+CHARGES\s*\(\s*EXPORT\s*-\s*RAIL/ROAD\s*\)",
        r"STEVEDORING\s*/\s*TERMINAL\s+HANDLING\s+CHARGES\s*\(\s*EXPORT\s*-\s*",
    ]

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            combined_text,
            re.IGNORECASE
        ):
            charge = clean_text(match.group(0))
            charge = re.sub(r"\s+", " ", charge).strip()

            if charge and charge not in charges:
                charges.append(charge)

    return " | ".join(charges) if charges else None


def extract_psa_currency(text, table_parts):
    if re.search(
        r"AMOUNT\s*\(\s*INR\s*\)",
        text,
        re.IGNORECASE
    ):
        return "INR"

    for table in table_parts:
        if re.search(
            r"AMOUNT\s*\(\s*INR\s*\)",
            table,
            re.IGNORECASE
        ):
            return "INR"

    return None


def extract_psa_tax(text, table_parts):
    cgst = None
    sgst = None
    taxable = None
    total = None

    combined_text = "\n".join(table_parts) + "\n" + text

    match = re.search(
        r"Total\s+Amount\s+Before\s+Tax\s*"
        r"(?:\|\s*|\s+)"
        r"([\d,]+\.\d{2})",
        combined_text,
        re.IGNORECASE
    )

    if match:
        taxable = clean_number(match.group(1))

    match = re.search(
        r"Add\s*:\s*CGST\s*@\s*[\d.]+\s*%\s*"
        r"(?:\|\s*|\s+)"
        r"([\d,]+\.\d{2})",
        combined_text,
        re.IGNORECASE
    )

    if match:
        cgst = clean_number(match.group(1))

    match = re.search(
        r"Add\s*:\s*SGST\s*@\s*[\d.]+\s*%\s*"
        r"(?:\|\s*|\s+)"
        r"([\d,]+\.\d{2})",
        combined_text,
        re.IGNORECASE
    )

    if match:
        sgst = clean_number(match.group(1))

    match = re.search(
        r"TOTAL\s+AMOUNT\s+DUE:"
        r".*?"
        r"(?:\|\s*|\s+)"
        r"([\d,]+\.\d{2})",
        combined_text,
        re.IGNORECASE | re.DOTALL
    )

    if match:
        total = clean_number(match.group(1))

    if total is None:
        match = re.search(
            r"TOTAL\s+AMOUNT\s+DUE:.*?"
            r"(\d{1,3}(?:,\d{3})+\.\d{2})",
            combined_text,
            re.IGNORECASE | re.DOTALL
        )

        if match:
            total = clean_number(match.group(1))

    return cgst, sgst, taxable, total


def extract_psa(text, table_parts):
    cgst, sgst, taxable, total = extract_psa_tax(
        text,
        table_parts
    )

    return {
        "INVOICE_NO": extract_psa_invoice_no(
            text,
            table_parts
        ),
        "INVOICE_DATE": extract_psa_invoice_date(
            text,
            table_parts
        ),
        "DUE_DATE": extract_psa_due_date(
            text,
            table_parts
        ),
        "IRN_NO": extract_psa_irn(
            text,
            table_parts
        ),
        "COMPANY": extract_psa_company(
            text,
            table_parts
        ),
        "PAN_NO": extract_psa_pan(
            text,
            table_parts
        ),
        "BILL_OF_LADING": extract_psa_bl(
            text,
            table_parts
        ),
        "VESSEL": extract_psa_vessel(
            text,
            table_parts
        ),
        "CONTAINER_NO": extract_psa_containers(
            text,
            table_parts
        ),
        "POL": extract_psa_pol(
            text,
            table_parts
        ),
        "POD": extract_psa_pod(
            text,
            table_parts
        ),
        "CHARGES_NAME": extract_psa_charges(
            text,
            table_parts
        ),
        "CURRENCY": extract_psa_currency(
            text,
            table_parts
        ),
        "CGST": cgst,
        "SGST": sgst,
        "TAXABLE_AMOUNT": taxable,
        "TOTAL_PAYABLE_AMOUNT": total,
    }

def extract_rcl_invoice_no(text):
    match = re.search(
        r"Invoice\s+No\.\s*:\s*([A-Z0-9]+)",
        text,
        re.IGNORECASE
    )

    if match:
        return clean_text(match.group(1))

    return None


def extract_rcl_invoice_date(text):
    match = re.search(
        r"Invoice\s+Print\s+Date\s*:\s*(\d{2}/\d{2}/\d{4})",
        text,
        re.IGNORECASE
    )

    if match:
        return parse_date(
            match.group(1),
            ["%d/%m/%Y"]
        )

    return None


def extract_rcl_due_date(text):
    match = re.search(
        r"Invoice\s+Due\s+Date\s*:\s*(\d{2}/\d{2}/\d{4})",
        text,
        re.IGNORECASE
    )

    if match:
        return parse_date(
            match.group(1),
            ["%d/%m/%Y"]
        )

    return None


def extract_rcl_irn(text):
    match = re.search(
        r"IRN\s*:\s*((?:[A-Fa-f0-9]\s*){64})",
        text,
        re.IGNORECASE
    )

    if match:
        return re.sub(r"\s+", "", match.group(1))

    return None


def extract_rcl_company(text):
    return "RCL"


def extract_rcl_pan(text):
    matches = re.findall(
        r"PAN\s+NO\s*:\s*([A-Z]{5}[0-9]{4}[A-Z])",
        text,
        re.IGNORECASE
    )

    if matches:
        return matches[-1].upper()

    return None


def extract_rcl_bill_of_lading(text):
    match = re.search(
        r"B/L\s+No\s*:\s*([A-Z0-9]+)",
        text,
        re.IGNORECASE
    )

    if match:
        return clean_text(match.group(1))

    return None


def extract_rcl_vessel(text):
    match = re.search(
        r"Vessel/Voyage\s*:\s*(.+?)\s*/\s*[A-Z0-9]+",
        text,
        re.IGNORECASE
    )

    if match:
        return clean_text(match.group(1))

    return None


def extract_rcl_containers(text):
    return None


def extract_rcl_pol(text):
    match = re.search(
        r"POL\s*:\s*[A-Z0-9]+\s*-\s*([A-Z][A-Z\s]+?)\s+POD\s*:",
        text,
        re.IGNORECASE
    )

    if match:
        return clean_text(match.group(1)).upper()

    return None


def extract_rcl_pod(text):
    match = re.search(
        r"POD\s*:\s*[A-Z0-9]+\s*-\s*(.+?)\s+Cust\s+Ref",
        text,
        re.IGNORECASE
    )

    if match:
        return clean_text(match.group(1)).upper()

    return None


def extract_rcl_charges(table_parts):
    charges = []

    for table_text in table_parts:
        if not table_text:
            continue

        lines = table_text.splitlines()

        charge_header_index = None
        data_started = False

        for line in lines:
            normalized = clean_text(line)

            if not normalized:
                continue

            parts = [
                clean_text(part)
                for part in normalized.split("|")
            ]

            if charge_header_index is None:
                for index, part in enumerate(parts):
                    if re.fullmatch(
                        r"Charge\s+Description",
                        part or "",
                        re.IGNORECASE
                    ):
                        charge_header_index = index
                        break

                continue

            if re.match(
                r"^Total\s+INR\b",
                normalized,
                re.IGNORECASE
            ):
                break

            if charge_header_index >= len(parts):
                continue

            charge_cell = parts[charge_header_index]

            if not charge_cell:
                continue

            data_started = True

            charge_lines = [
                re.sub(r"\s+", " ", value).strip()
                for value in charge_cell.splitlines()
                if value.strip()
            ]

            current_charge = None

            for value in charge_lines:
                if re.match(
                    r"^\d{3,5}[A-Z0-9]*-",
                    value,
                    re.IGNORECASE
                ):
                    if current_charge:
                        current_charge = re.sub(
                            r"\s+",
                            " ",
                            current_charge
                        ).strip()

                        if current_charge not in charges:
                            charges.append(current_charge)

                    current_charge = value

                else:
                    if current_charge:
                        current_charge += " " + value

            if current_charge:
                current_charge = re.sub(
                    r"\s+",
                    " ",
                    current_charge
                ).strip()

                if current_charge not in charges:
                    charges.append(current_charge)

        if data_started:
            continue

    return " | ".join(charges) if charges else None


def extract_rcl_currency(text):
    currencies = []

    pattern = (
        r"\b(?:USD|INR|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|"
        r"HKD|MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)\b"
    )

    for match in re.finditer(
        pattern,
        text,
        re.IGNORECASE
    ):
        value = match.group(0).upper()

        if value not in currencies:
            currencies.append(value)

    return ", ".join(currencies) if currencies else None


def extract_rcl_total_inr_row(table_parts):
    for table_text in table_parts:
        if not table_text:
            continue

        for line in table_text.splitlines():
            normalized = clean_text(line)

            if not normalized:
                continue

            if not re.search(
                r"^Total\s+INR\b",
                normalized,
                re.IGNORECASE
            ):
                continue

            parts = [
                clean_text(part)
                for part in normalized.split("|")
            ]

            numeric_values = []

            for part in parts[1:]:
                values = re.findall(
                    r"-?[\d,\s]+\.\d{2}",
                    part
                )

                for value in values:
                    number = clean_number(value)

                    if number is not None:
                        numeric_values.append(number)

            if len(numeric_values) >= 4:
                return (
                    numeric_values[0],
                    numeric_values[1],
                    numeric_values[2]
                )

    return None, None, None


def extract_rcl_cgst(text, table_parts):
    taxable, cgst, sgst = extract_rcl_total_inr_row(
        table_parts
    )

    if cgst is not None:
        return cgst

    matches = re.findall(
        r"\bCGST\b[^\d]*([\d,\s]+\.\d{2})",
        text,
        re.IGNORECASE
    )

    if matches:
        return clean_number(matches[-1])

    return None


def extract_rcl_sgst(text, table_parts):
    taxable, cgst, sgst = extract_rcl_total_inr_row(
        table_parts
    )

    if sgst is not None:
        return sgst

    matches = re.findall(
        r"\bSGST\b[^\d]*([\d,\s]+\.\d{2})",
        text,
        re.IGNORECASE
    )

    if matches:
        return clean_number(matches[-1])

    return None


def extract_rcl_taxable_amount(text, table_parts):
    taxable, cgst, sgst = extract_rcl_total_inr_row(
        table_parts
    )

    if taxable is not None:
        return taxable

    match = re.search(
        r"Amount\s+of\s+Tax\s+subject\s+to\s+GST\s*"
        r"([\d,\s]+\.\d{2})",
        text,
        re.IGNORECASE
    )

    if match:
        return clean_number(match.group(1))

    match = re.search(
        r"Amount\s+of\s+Tax\s+subject\s+to\s+GST.*?"
        r"([\d,\s]+\.\d{2})\s+"
        r"[\d,\s]+\.\d{2}\s+"
        r"[\d,\s]+\.\d{2}",
        text,
        re.IGNORECASE | re.DOTALL
    )

    if match:
        return clean_number(match.group(1))

    return None


def extract_rcl_total_payable_amount(text, table_parts):
    taxable, cgst, sgst = extract_rcl_total_inr_row(
        table_parts
    )

    if taxable is not None and cgst is not None and sgst is not None:
        return round(
            taxable + cgst + sgst,
            2
        )

    return None

def extract_rcl(text, table_parts):
    result = get_empty_result()

    result["INVOICE_NO"] = extract_rcl_invoice_no(text)
    result["INVOICE_DATE"] = extract_rcl_invoice_date(text)
    result["DUE_DATE"] = extract_rcl_due_date(text)
    result["IRN_NO"] = extract_rcl_irn(text)
    result["COMPANY"] = extract_rcl_company(text)
    result["PAN_NO"] = extract_rcl_pan(text)
    result["BILL_OF_LADING"] = extract_rcl_bill_of_lading(text)
    result["VESSEL"] = extract_rcl_vessel(text)
    result["CONTAINER_NO"] = extract_rcl_containers(text)
    result["POL"] = extract_rcl_pol(text)
    result["POD"] = extract_rcl_pod(text)
    result["CHARGES_NAME"] = extract_rcl_charges(table_parts)
    result["CURRENCY"] = extract_rcl_currency(text)
    result["CGST"] = extract_rcl_cgst(text, table_parts)
    result["SGST"] = extract_rcl_sgst(text, table_parts)
    result["TAXABLE_AMOUNT"] = extract_rcl_taxable_amount(
        text,
        table_parts
    )
    result["TOTAL_PAYABLE_AMOUNT"] = extract_rcl_total_payable_amount(
        text,
        table_parts
    )

    return result

def extract_sjlogistics(text, table_parts):
    result = get_empty_result()

    invoice_match = re.search(
        r"\bInvoice\s*(?:No|Number)?\s*[:#]?\s*([A-Z0-9][A-Z0-9/-]+)",
        text,
        re.I
    )
    if invoice_match:
        result["INVOICE_NO"] = invoice_match.group(1).strip()

    date_match = re.search(
        r"(?:Invoice\s*Date|Invoice\s*Dt)\s*[:\-]?\s*(\d{1,2}[-/][A-Za-z0-9]{3,9}[-/]\d{2,4}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
        text,
        re.I
    )
    if date_match:
        result["INVOICE_DATE"] = parse_date(
            date_match.group(1),
            [
                "%d-%b-%Y",
                "%d/%b/%Y",
                "%d-%B-%Y",
                "%d/%B/%Y",
                "%d/%m/%Y",
                "%d-%m-%Y"
            ]
        )

    due_match = re.search(
        r"(?:Due\s*Date|Due\s*Dt)\s*[:\-]?\s*(\d{1,2}[-/][A-Za-z0-9]{3,9}[-/]\d{2,4}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
        text,
        re.I
    )
    if due_match:
        result["DUE_DATE"] = parse_date(
            due_match.group(1),
            [
                "%d-%b-%Y",
                "%d/%b/%Y",
                "%d-%B-%Y",
                "%d/%B/%Y",
                "%d/%m/%Y",
                "%d-%m-%Y"
            ]
        )

    irn_match = re.search(
        r"\bIRN\s*[:\-]?\s*([a-f0-9]{64})\b",
        text,
        re.I
    )
    if irn_match:
        result["IRN_NO"] = irn_match.group(1)

    result["COMPANY"] = "S J Logistics"

    pan_match = re.search(
        r"(?:PAN|PAN\s*No\.?)\s*[:#]?\s*([A-Z]{5}\d{4}[A-Z])",
        text,
        re.I
    )
    if pan_match:
        result["PAN_NO"] = pan_match.group(1).upper()

    bl_match = re.search(
        r"\bMBL\s*No\s*:\s*([A-Z0-9-]+)",
        text,
        re.I
    )
    if bl_match:
        value = bl_match.group(1).strip()
        if value.upper() not in {
            "DESTINATION",
            "DATE",
            "FPOD",
            "LOAD"
        }:
            result["BILL_OF_LADING"] = value

    vessel_match = re.search(
        r"\bVessel\s*:\s*(.*?)(?=\s+Container\s+Numbers\s*:|\s+MBL\s+No\s*:|\s+Loading\s+Port\s*:|\s+Destination\s+Port\s*:|\s+Remarks\s*:)",
        text,
        re.I | re.S
    )
    if vessel_match:
        result["VESSEL"] = re.sub(
            r"\s+",
            " ",
            vessel_match.group(1)
        ).strip()

    container_match = re.search(
        r"Container\s+Numbers\s*:\s*(.*?)(?=\s+Remarks\s*:|\s+MBL\s+No\s*:|\s+Loading\s+Port\s*:|\s+Destination\s+Port\s*:)",
        text,
        re.I | re.S
    )
    if container_match:
        containers = re.findall(
            r"\b[A-Z]{4}\d{7}\b",
            container_match.group(1).upper()
        )
        if containers:
            result["CONTAINER_NO"] = ",".join(
                dict.fromkeys(containers)
            )

    pol_match = re.search(
        r"\bLoading\s+Port\s*:\s*(.*?)(?=\s+ETD\s*:|\s+Destination\s+Port\s*:|\s+MBL\s+No\s*:|\s+Vessel\s*:)",
        text,
        re.I | re.S
    )
    if pol_match:
        result["POL"] = re.sub(
            r"\s+",
            " ",
            pol_match.group(1)
        ).strip()

    pod_match = re.search(
        r"\bDestination\s+Port\s*:\s*(.*?)(?=\s+MBL\s+Date\s*:|\s+MBL\s+No\s*:|\s+FPOD\s*:|\s+Load\s+type\s*:|\s+Remarks\s*:|\s+Container\s+Numbers\s*:|\s+Vessel\s*:)",
        text,
        re.I | re.S
    )
    if pod_match:
        result["POD"] = re.sub(
            r"\s+",
            " ",
            pod_match.group(1)
        ).strip()

    if not result["POD"]:
        pod_match = re.search(
            r"\bDestination\s+Port\s*:\s*(.*?)(?=\s+\bMBL\s+Date\b|\s+\bMBL\b|\s+\bFPOD\b|\s+\bLoad\s+type\b|\s+\bRemarks\b)",
            text,
            re.I | re.S
        )
        if pod_match:
            result["POD"] = re.sub(
                r"\s+",
                " ",
                pod_match.group(1)
            ).strip()

    result["CHARGES_NAME"] = None

    charge_patterns = [
        r"\b\d+\s+(OCEAN\s+FREIGHT\s+EXPORT)\s+(?=996521\b)",
        r"\b\d+\s+(OCEAN\s+FREIGHT\s+EXPORT)\b",
        r"\b(OCEAN\s+FREIGHT\s+EXPORT)\s+996521\b"
    ]

    for table in table_parts:
        normalized = re.sub(
            r"\s+",
            " ",
            table
        ).strip()

        for pattern in charge_patterns:
            charge_match = re.search(
                pattern,
                normalized,
                re.I
            )

            if charge_match:
                result["CHARGES_NAME"] = re.sub(
                    r"\s+",
                    " ",
                    charge_match.group(1)
                ).strip()
                break

        if result["CHARGES_NAME"]:
            break

    if not result["CHARGES_NAME"]:
        normalized_text = re.sub(
            r"\s+",
            " ",
            text
        )

        charge_match = re.search(
            r"\b\d+\s+(OCEAN\s+FREIGHT\s+EXPORT)\s+(?=996521\b)",
            normalized_text,
            re.I
        )

        if charge_match:
            result["CHARGES_NAME"] = charge_match.group(1).strip()

    currencies = re.findall(
        r"\b(?:INR|USD|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)\b",
        text.upper()
    )
    if currencies:
        result["CURRENCY"] = ", ".join(
            dict.fromkeys(currencies)
        )

    tax_found = False

    for table in table_parts:
        normalized = re.sub(
            r"\s+",
            " ",
            table
        ).strip()

        row_match = re.search(
            r"OCEAN\s+FREIGHT\s+EXPORT\s+996521\s+(?:USD|INR)\s+[\d,]+\.\d+\s+\d+\s+[\d,]+\.\d+\s+[A-Z]\s+([\d,]+\.\d+)\s+2\.5\s+([\d,]+\.\d+)\s+2\.5\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)",
            normalized,
            re.I
        )

        if row_match:
            result["TAXABLE_AMOUNT"] = float(
                row_match.group(1).replace(",", "")
            )
            result["CGST"] = float(
                row_match.group(2).replace(",", "")
            )
            result["SGST"] = float(
                row_match.group(3).replace(",", "")
            )
            result["TOTAL_PAYABLE_AMOUNT"] = float(
                row_match.group(4).replace(",", "")
            )
            tax_found = True
            break

        row_match = re.search(
            r"OCEAN\s+FREIGHT\s+EXPORT\s+996521\s+USD\s+[\d,]+\.\d+\s+\d+\s+T\s+([\d,]+\.\d+)\s+2\.5\s+([\d,]+\.\d+)\s+2\.5\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)",
            normalized,
            re.I
        )

        if row_match:
            result["TAXABLE_AMOUNT"] = float(
                row_match.group(1).replace(",", "")
            )
            result["CGST"] = float(
                row_match.group(2).replace(",", "")
            )
            result["SGST"] = float(
                row_match.group(3).replace(",", "")
            )
            result["TOTAL_PAYABLE_AMOUNT"] = float(
                row_match.group(4).replace(",", "")
            )
            tax_found = True
            break

    if not tax_found:
        taxable_match = re.search(
            r"Total\s+Amount\s+before\s+Tax\s*[:\-]?\s*(?:INR|USD)?\s*([\d,]+\.\d+)",
            text,
            re.I
        )

        if taxable_match:
            result["TAXABLE_AMOUNT"] = float(
                taxable_match.group(1).replace(",", "")
            )

        gst_match = re.search(
            r"Add\s*:\s*GST\s*[:\-]?\s*(?:INR|USD)?\s*([\d,]+\.\d+)",
            text,
            re.I
        )

        if gst_match:
            gst = float(
                gst_match.group(1).replace(",", "")
            )
            result["CGST"] = round(
                gst / 2,
                2
            )
            result["SGST"] = round(
                gst / 2,
                2
            )

        total_match = re.search(
            r"(?:Total\s+Amount\s+After\s+Tax|Net\s+Payable)\s*[:\-]?\s*(?:INR|USD)?\s*([\d,]+\.\d+)",
            text,
            re.I
        )

        if total_match:
            result["TOTAL_PAYABLE_AMOUNT"] = float(
                total_match.group(1).replace(",", "")
            )

    return result     

def extract_sci(text, table_parts):
    result = get_empty_result()

    invoice_match = re.search(
        r"\bInvoice\s+No\s*:?\s*([A-Z0-9-]+)",
        text,
        re.I
    )
    if invoice_match:
        result["INVOICE_NO"] = invoice_match.group(1).strip()

    date_match = re.search(
        r"\bInvoice\s+Date\s*:?\s*(\d{2}\.\d{2}\.\d{4})",
        text,
        re.I
    )
    if date_match:
        result["INVOICE_DATE"] = parse_date(
            date_match.group(1),
            ["%d.%m.%Y"]
        )

    result["DUE_DATE"] = None
    result["IRN_NO"] = None
    result["COMPANY"] = "SCI"

    pan_match = re.search(
        r"\bPAN\s+No\s*:?\s*([A-Z]{5}\d{4}[A-Z])",
        text,
        re.I
    )
    if pan_match:
        result["PAN_NO"] = pan_match.group(1).upper()

    bl_match = re.search(
        r"\bB/L\s+No\s*:?\s*([A-Z0-9]+)",
        text,
        re.I
    )
    if bl_match:
        result["BILL_OF_LADING"] = bl_match.group(1).strip()

    vessel_match = re.search(
        r"\bLoad\s+Vessel/Voyage\s*:?\s*([^/\n]+)",
        text,
        re.I
    )
    if vessel_match:
        result["VESSEL"] = vessel_match.group(1).strip()

    result["CONTAINER_NO"] = None

    pol_match = re.search(
        r"\bPort\s+of\s+Loading\s*:?\s*(.*?)(?=\s+Port\s+of\s+Discharge\s*:|\s+Place\s+of\s+Delivery\s*:|\s+Description\b|\s+USD\s*=|\s+INR\s*=|\n|$)",
        text,
        re.I | re.S
    )
    if pol_match:
        pol = pol_match.group(1).strip()
        pol = re.sub(r"\s+", " ", pol).strip()
        result["POL"] = pol

    pod_match = re.search(
        r"\bPort\s+of\s+Discharge\s*:?\s*(.*?)(?=\s+Place\s+of\s+Delivery\s*:|\s+Description\b|\s+USD\s*=|\s+INR\s*=|\n|$)",
        text,
        re.I | re.S
    )
    if pod_match:
        pod = pod_match.group(1).strip()
        pod = re.sub(r"\s+", " ", pod).strip()
        result["POD"] = pod

    charges = []

    for table_text in table_parts:
        normalized = re.sub(r"\s+", " ", table_text).strip()

        for match in re.finditer(
            r"\b([A-Z][A-Z0-9/&-]*)\s+HSN/SAC\s*:?\s*\d{5,6}\b",
            normalized,
            re.I
        ):
            charge = match.group(1).strip().upper()

            if charge not in charges:
                charges.append(charge)

    if not charges:
        for match in re.finditer(
            r"\b([A-Z][A-Z0-9/&-]*)\s+HSN/SAC\s*:?\s*\d{5,6}\b",
            text,
            re.I
        ):
            charge = match.group(1).strip().upper()

            if charge not in charges:
                charges.append(charge)

    result["CHARGES_NAME"] = ", ".join(charges) if charges else None

    currency_matches = re.findall(
        r"\b(USD|INR|EUR|GBP|AED|SGD|CNY|RMB|JPY|AUD|CAD|CHF|HKD|MYR|SAR|QAR|OMR|KWD|BHD|NZD|THB|IDR|KRW|VND)\b",
        text,
        re.I
    )

    currencies = []

    for currency in currency_matches:
        currency = currency.upper()

        if currency not in currencies:
            currencies.append(currency)

    result["CURRENCY"] = ", ".join(currencies) if currencies else None

    taxable_match = re.search(
        r"\bTotal\s+Taxable\s+Amount\s+INR\s*:?\s*([\d,]+\.\d{2})",
        text,
        re.I
    )

    if taxable_match:
        result["TAXABLE_AMOUNT"] = clean_number(
            taxable_match.group(1)
        )

    tax_match = re.search(
        r"\bTotal\s+Tax\s+Amount\s+INR\s*:?\s*([\d,]+\.\d{2})",
        text,
        re.I
    )

    if tax_match:
        total_tax = clean_number(tax_match.group(1))

        if total_tax is not None:
            result["CGST"] = round(total_tax / 2, 2)
            result["SGST"] = round(total_tax - result["CGST"], 2)

    total_match = re.search(
        r"\bTotal\s+Invoice\s+Amount\s+INR\s*:?\s*([\d,]+\.\d{2})",
        text,
        re.I
    )

    if total_match:
        result["TOTAL_PAYABLE_AMOUNT"] = clean_number(
            total_match.group(1)
        )

    return result

def extract_seabridge_invoice_no(text):
    match = re.search(
        r"\bInvoice\s+No\s*:\s*([A-Z0-9]+)",
        text,
        re.I
    )
    return match.group(1).strip() if match else None


def extract_seabridge_invoice_date(text):
    match = re.search(
        r"\bInvoice\s+Date\s*:\s*(\d{1,2}-[A-Za-z]{3}-\d{4})",
        text,
        re.I
    )

    if match:
        try:
            return datetime.strptime(
                match.group(1),
                "%d-%b-%Y"
            ).date()
        except ValueError:
            pass

    return None


def extract_seabridge_due_date(text):
    return None


def extract_seabridge_irn(text):
    match = re.search(
        r"\bTAX\s+INVOICE\s+IRN\s*:\s*([a-f0-9]{64})\b",
        text,
        re.I
    )

    if match:
        return match.group(1).strip()

    match = re.search(
        r"\bIRN\s*:\s*([a-f0-9]{64})\b",
        text,
        re.I
    )

    return match.group(1).strip() if match else None


def extract_seabridge_pan(text):
    match = re.search(
        r"\bPAN\s+NO\s*:\s*([A-Z]{5}[0-9]{4}[A-Z])",
        text,
        re.I
    )

    return match.group(1).upper() if match else None


def extract_seabridge_bill_of_lading(text):
    match = re.search(
        r"\bB/L\s+No\s*:\s*([A-Z0-9\/\-]+)",
        text,
        re.I
    )

    return match.group(1).strip() if match else None


def extract_seabridge_vessel(text):
    match = re.search(
        r"\bVessel\s*:\s*(.*?)(?=\s+Port\s+Of\s+Loading\s*:)",
        text,
        re.I | re.S
    )

    if match:
        value = re.sub(r"\s+", " ", match.group(1)).strip()
        return value if value else None

    return None


def extract_seabridge_containers(text):
    match = re.search(
        r"\bContainer\s+No['’]?s\s*:\s*(.*?)(?=\s+Taxable\s+SAC\s*\/|\s+Taxable\b|\n|$)",
        text,
        re.I | re.S
    )

    if match:
        value = match.group(1)

        containers = re.findall(
            r"\b[A-Z]{4}\d{7}\b",
            value.upper()
        )

        containers = list(dict.fromkeys(containers))

        if containers:
            return ",".join(containers)

    containers = re.findall(
        r"\b[A-Z]{4}\d{7}\b",
        text.upper()
    )

    containers = list(dict.fromkeys(containers))

    return ",".join(containers) if containers else None


def extract_seabridge_pol(text):
    match = re.search(
        r"\bPort\s+Of\s+Loading\s*:\s*(.*?)(?=\s+Voyage\s+No\s*:)",
        text,
        re.I | re.S
    )

    if match:
        value = re.sub(r"\s+", " ", match.group(1)).strip()
        return value if value else None

    return None


def extract_seabridge_pod(text):
    match = re.search(
        r"\bPort\s+Of\s+Discharge\s*:\s*(.*?)(?=\s+B/L\s+No\s*:)",
        text,
        re.I | re.S
    )

    if match:
        value = re.sub(r"\s+", " ", match.group(1)).strip()
        return value if value else None

    return None




def extract_placeholder(text, tables):
    return get_empty_result()


CARRIER_TEMPLATES = {
    "Maersk_Only": "extract_maersk",
    "CMA CGM": "extract_cma_cgm",
    "Hapag-Lloyd": "extract_hapag_lloyd",
    "HMM": "extract_hmm",
    "Hub and Links Logistics": "extract_hub_and_links",
    "J M Baxi": "extract_jm_baxi",
    "Nhava Sheva": "extract_nhava_sheva",
    "Mundra": "extract_mundra",
    "MSC": "extract_msc",
    "Nhava Sheva Freeport Terminal": "extract_nhava_sheva_freeport",
    "Oasis Shipping": "extract_oasis_shipping",
    "Ocean Generation Shipping": "extract_ocean_generation_shipping",
    "ONE": "extract_one",
    "OOCL": "extract_oocl",
    "PIL": "extract_pil",
    "Promise Shipping Line": "extract_promise",
    "PSA": "extract_psa",
    "RCL" : "extract_rcl", 
    "S J Logistics": "extract_sjlogistics",
    "SCI" : "extract_sci",

}

def process_carrier(carrier_name, limit=None):
    if carrier_name not in CARRIER_TEMPLATES:
        print(f"Carrier not registered: {carrier_name}")
        return

    folder = BASE_DIR / carrier_name

    if not folder.exists():
        print(f"Folder not found: {folder}")
        return

    function_name = CARRIER_TEMPLATES[carrier_name]
    extractor = globals()[function_name]

    pdf_files, duplicate_count = get_unique_pdf_files(
        folder,
        limit=limit,
    )

    print("=" * 70)
    print(f"CARRIER: {carrier_name}")
    print("=" * 70)
    print(f"Folder: {folder}")
    print(f"Unique PDFs selected: {len(pdf_files)}")
    print(f"Exact duplicates skipped: {duplicate_count}")
    print()

    for pdf_path in pdf_files:
        print("=" * 70)
        print(pdf_path.name)
        print("=" * 70)

        text, tables, error = extract_pdf_content(pdf_path)

        if error:
            print(f"ERROR: {error}")
            print()
            continue

        result = extractor(
            text,
            tables
        )

        issues = validate_result(result)

        for field in TARGET_FIELDS:
            print(f"{field}: {result.get(field)}")

        if issues:
            print()
            print("VALIDATION ISSUES:")

            for issue in issues:
                print(issue)
        else:
            print()
            print("VALIDATION: OK")

        print()


if __name__ == "__main__":
    process_carrier(
        "Maersk_Only",
        limit= 30
    )

