import os
import re
import sys
import time
import json
import hashlib
import shutil
import importlib.util
from pathlib import Path

import pyodbc


BASE_DIR = Path(r"C:\Users\Siddhi\Desktop\sorted_PDFs")
INCOMING_DIR = Path(r"C:\Users\Siddhi\Desktop\parseable_documents")
UNTEMPLATED_DIR = INCOMING_DIR / "Untemplated_Files"
PROCESSED_DIR = INCOMING_DIR / "Processed_PDFs"
FAILED_DIR = INCOMING_DIR / "Failed_Files"
HASH_FILE = INCOMING_DIR / ".processed_hashes.json"

MASTER_FILE = BASE_DIR / "master_invoice_pipeline.py"
CHARGE_FILE = BASE_DIR / "charge_extraction_templates.py"

DB_CONFIG = {
    "server": "10.10.0.72",
    "database": "Shipping_invo_db",
    "username": "sa",
    "password": "pass@2020$",
    "driver": "ODBC Driver 17 for SQL Server",
}

POLL_SECONDS = 3600

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
    "RCL": "extract_rcl",
    "S J Logistics": "extract_sjlogistics",
    "SCI": "extract_sci",
}

CARRIER_SIGNATURES = {
    "Maersk_Only": [
        "MAERSK",
        "A.P. MOLLER",
        "MAERSK LINE",
        "SEALAND",
        "SAFMARINE",
    ],
    "CMA CGM": [
        "CMA CGM",
        "CMA CGM SA",
        "CNC LINE",
        "ANL CONTAINER",
    ],
    "Hapag-Lloyd": [
        "HAPAG-LLOYD",
        "HAPAG LLOYD",
    ],
    "HMM": [
        "HYUNDAI MERCHANT MARINE",
        "HMM CO LTD",
        "HMM COMPANY",
        "HMM INDIA",
    ],
    "Hub and Links Logistics": [
        "HUB AND LINKS LOGISTICS",
        "HUB & LINKS LOGISTICS",
        "HUB AND LINKS",
    ],
    "J M Baxi": [
        "J M BAXI",
        "JM BAXI",
        "J.M. BAXI",
    ],
    "Nhava Sheva": [
        "NHAVA SHEVA",
        "NSICT",
        "NSIGT",
    ],
    "Mundra": [
        "MUNDRA",
        "MUNDRA PORT",
        "MUNDRA INTERNATIONAL CONTAINER TERMINAL",
    ],
    "MSC": [
        "MEDITERRANEAN SHIPPING COMPANY",
        "MSC MEDITERRANEAN",
        "MSC INDIA",
    ],
    "Nhava Sheva Freeport Terminal": [
        "NHAVA SHEVA FREEPORT TERMINAL",
        "NSFT",
        "FREEPORT TERMINAL",
    ],
    "Oasis Shipping": [
        "OASIS SHIPPING",
        "OASIS",
    ],
    "Ocean Generation Shipping": [
        "OCEAN GENERATION SHIPPING",
        "OCEAN GENERATION",
    ],
    "ONE": [
        "OCEAN NETWORK EXPRESS",
        "ONE SHIPPING PARTNER",
        "YOUR NUMBER ONE SHIPPING PARTNER",
    ],
    "OOCL": [
        "ORIENT OVERSEAS CONTAINER LINE",
        "ORIENT OVERSEAS CONTAINER",
        "OOCL INDIA",
    ],
    "PIL": [
        "PACIFIC INTERNATIONAL LINES",
        "PIL INDIA",
    ],
    "Promise Shipping Line": [
        "PROMISE SHIPPING LINE",
        "PROMISE SHIPPING",
    ],
    "PSA": [
        "BHARAT MUMBAI CONTAINER TERMINALS",
        "PSA MUMBAI",
        "PSA TERMINALS",
    ],
    "RCL": [
        "REGIONAL CONTAINER LINES",
        "RCL AGENCIES",
        "RCL FEEDER",
    ],
    "S J Logistics": [
        "S J LOGISTICS",
        "SJ LOGISTICS",
        "S.J. LOGISTICS",
    ],
    "SCI": [
        "THE SHIPPING CORPORATION OF INDIA",
        "SHIPPING CORPORATION OF INDIA",
        "SHIPINDIA",
        "SCI",
    ],
    "LMT": [
        "LMT LOGISTICS PRIVATE LIMITED",
        "LMT LOGISTICS PVT LTD",
        "LMT LOGISTICS",
        "LMT SUPPLY CHAIN",
        "LMT SUPPLY",
    ],
}

CHARGE_CARRIERS = [
    "Maersk_Only",
    "CMA CGM",
    "Hapag-Lloyd",
    "HMM",
    "Hub and Links Logistics",
    "J M Baxi",
    "LMT",
    "Nhava Sheva",
    "Mundra",
    "MSC",
    "Nhava Sheva Freeport Terminal",
    "Oasis Shipping",
    "Ocean Generation Shipping",
    "ONE",
    "OOCL",
    "PIL",
    "Promise Shipping Line",
    "PSA",
    "RCL",
    "S J Logistics",
    "SCI",
]


def load_module(module_name, file_path):
    if not file_path.exists():
        raise FileNotFoundError(str(file_path))

    spec = importlib.util.spec_from_file_location(
        module_name,
        str(file_path),
    )

    if spec is None or spec.loader is None:
        raise ImportError(
            f"Unable to load {file_path}"
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def load_hashes():
    if not HASH_FILE.exists():
        return set()

    try:
        with open(
            HASH_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        if isinstance(data, list):
            return set(data)

        if isinstance(data, dict):
            return set(data.keys())

    except Exception:
        return set()

    return set()


def save_hashes(hashes):
    INCOMING_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_file = HASH_FILE.with_suffix(".tmp")

    with open(
        temporary_file,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            sorted(hashes),
            file,
            indent=2,
        )

    temporary_file.replace(HASH_FILE)


def calculate_sha256(pdf_path):
    sha256 = hashlib.sha256()

    with open(
        pdf_path,
        "rb",
    ) as file:
        while True:
            chunk = file.read(1024 * 1024)

            if not chunk:
                break

            sha256.update(chunk)

    return sha256.hexdigest()


def clean_text(value):
    if value is None:
        return ""

    value = str(value)
    value = value.replace("\xa0", " ")
    value = value.replace("\u200b", "")
    value = value.replace("\ufeff", "")
    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def normalize_detection_text(text):
    if text is None:
        return ""

    text = str(text).upper()
    text = text.replace("\xa0", " ")
    text = text.replace("\u200b", "")
    text = text.replace("\ufeff", "")
    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text


def get_pdf_files():
    INCOMING_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    return sorted(
        [
            path
            for path in INCOMING_DIR.iterdir()
            if path.is_file()
            and path.suffix.lower() == ".pdf"
        ],
        key=lambda path: path.stat().st_mtime,
    )


def extract_master_pdf_content(
    master_module,
    pdf_path,
):
    return master_module.extract_pdf_content(
        pdf_path
    )


def extract_charge_pdf_content(
    charge_module,
    master_module,
    pdf_path,
):
    charge_extract_function = getattr(
        charge_module,
        "extract_pdf_content",
        None,
    )

    if callable(charge_extract_function):
        return charge_extract_function(
            pdf_path
        )

    return master_module.extract_pdf_content(
        pdf_path
    )


def detect_carrier(pdf_path, text):
    detection_text = normalize_detection_text(
        text
    )

    filename_text = normalize_detection_text(
        pdf_path.name
    )

    combined_text = (
        f"{filename_text} {detection_text}"
    )

    candidates = []

    for carrier, signatures in CARRIER_SIGNATURES.items():
        score = 0
        matched = []

        for signature in signatures:
            signature_normalized = (
                normalize_detection_text(
                    signature
                )
            )

            if (
                signature_normalized
                and signature_normalized
                in combined_text
            ):
                score += len(
                    signature_normalized
                )

                matched.append(
                    signature
                )

        if score > 0:
            candidates.append(
                (
                    score,
                    carrier,
                    matched,
                )
            )

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    best_score = candidates[0][0]
    best_carrier = candidates[0][1]

    tied = [
        item
        for item in candidates
        if item[0] == best_score
    ]

    if len(tied) > 1:
        return None

    return best_carrier


def get_master_extractor(
    master_module,
    carrier,
):
    if carrier not in CARRIER_TEMPLATES:
        return None

    function_name = CARRIER_TEMPLATES[
        carrier
    ]

    extractor = getattr(
        master_module,
        function_name,
        None,
    )

    if callable(extractor):
        return extractor

    return None


def get_charge_extractor(
    charge_module,
    carrier,
):
    templates = getattr(
        charge_module,
        "CHARGE_TEMPLATES",
        {},
    )

    extractor = templates.get(
        carrier
    )

    if callable(extractor):
        return extractor

    return None


def get_charge_invoice_extractor(
    charge_module,
    carrier,
):
    templates = getattr(
        charge_module,
        "INVOICE_TEMPLATES",
        {},
    )

    extractor = templates.get(
        carrier
    )

    if callable(extractor):
        return extractor

    return None


def normalize_invoice_result(result):
    normalized = {}

    if not isinstance(
        result,
        dict,
    ):
        return {
            field: None
            for field in TARGET_FIELDS
        }

    for field in TARGET_FIELDS:
        value = result.get(field)

        if isinstance(
            value,
            str,
        ):
            value = value.strip()

            if not value:
                value = None

        normalized[field] = value

    return normalized


def connect_database():
    connection_string = (
        f"DRIVER={{{DB_CONFIG['driver']}}};"
        f"SERVER={DB_CONFIG['server']};"
        f"DATABASE={DB_CONFIG['database']};"
        f"UID={DB_CONFIG['username']};"
        f"PWD={DB_CONFIG['password']};"
        "TrustServerCertificate=yes;"
    )

    return pyodbc.connect(
        connection_string,
        timeout=30,
    )


def invoice_exists(
    connection,
    invoice_no,
):
    if not invoice_no:
        return False

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT COUNT(1)
        FROM dbo.OceanFreightInvoices_All
        WHERE INVOICE_NO = ?
        """,
        invoice_no,
    )

    count = cursor.fetchone()[0]

    cursor.close()

    return count > 0


def insert_invoice(
    connection,
    result,
):
    result = normalize_invoice_result(
        result
    )

    invoice_no = result[
        "INVOICE_NO"
    ]

    if not invoice_no:
        return False

    if invoice_exists(
        connection,
        invoice_no,
    ):
        print(
            f"INVOICE ALREADY EXISTS: "
            f"{invoice_no}"
        )

        return False

    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO dbo.OceanFreightInvoices_All
        (
            INVOICE_NO,
            INVOICE_DATE,
            DUE_DATE,
            IRN_NO,
            COMPANY,
            PAN_NO,
            BILL_OF_LADING,
            VESSEL,
            CONTAINER_NO,
            POL,
            POD,
            CHARGES_NAME,
            CURRENCY,
            CGST,
            SGST,
            TAXABLE_AMOUNT,
            TOTAL_PAYABLE_AMOUNT
        )
        VALUES
        (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?
        )
        """,
        result["INVOICE_NO"],
        result["INVOICE_DATE"],
        result["DUE_DATE"],
        result["IRN_NO"],
        result["COMPANY"],
        result["PAN_NO"],
        result["BILL_OF_LADING"],
        result["VESSEL"],
        result["CONTAINER_NO"],
        result["POL"],
        result["POD"],
        result["CHARGES_NAME"],
        result["CURRENCY"],
        result["CGST"],
        result["SGST"],
        result["TAXABLE_AMOUNT"],
        result["TOTAL_PAYABLE_AMOUNT"],
    )

    cursor.close()

    return True


def normalize_charge(charge):
    if not isinstance(
        charge,
        dict,
    ):
        return None

    charge_name = charge.get(
        "CHARGE_NAME"
    )

    currency = charge.get(
        "CURRENCY_TYPE"
    )

    amount = charge.get(
        "AMOUNT"
    )

    if charge_name is None:
        return None

    charge_name = clean_text(
        charge_name
    )

    if not charge_name:
        return None

    if currency is not None:
        currency = clean_text(
            currency
        ).upper()

    try:
        if amount is not None:
            amount = float(amount)
    except Exception:
        return None

    return {
        "CHARGE_NAME": charge_name,
        "CURRENCY_TYPE": currency,
        "AMOUNT": amount,
    }


def insert_charges(
    connection,
    invoice_no,
    carrier,
    charges,
):
    if not invoice_no:
        return 0

    if not charges:
        return 0

    cursor = connection.cursor()

    inserted = 0
    seen = set()

    for charge in charges:
        charge = normalize_charge(
            charge
        )

        if charge is None:
            continue

        key = (
            invoice_no,
            carrier,
            charge[
                "CHARGE_NAME"
            ].upper(),
            charge[
                "CURRENCY_TYPE"
            ],
            charge[
                "AMOUNT"
            ],
        )

        if key in seen:
            continue

        seen.add(key)

        cursor.execute(
            """
            IF NOT EXISTS
            (
                SELECT 1
                FROM dbo.InvoiceCharges
                WHERE INVOICE_NO = ?
                  AND CARRIER = ?
                  AND CHARGE_NAME = ?
                  AND ISNULL(CURRENCY_TYPE, '') =
                      ISNULL(?, '')
                  AND ISNULL(AMOUNT, 0) =
                      ISNULL(?, 0)
            )
            BEGIN
                INSERT INTO dbo.InvoiceCharges
                (
                    INVOICE_NO,
                    CARRIER,
                    CHARGE_NAME,
                    CURRENCY_TYPE,
                    AMOUNT
                )
                VALUES
                (
                    ?, ?, ?, ?, ?
                )
            END
            """,
            invoice_no,
            carrier,
            charge[
                "CHARGE_NAME"
            ],
            charge[
                "CURRENCY_TYPE"
            ],
            charge[
                "AMOUNT"
            ],
            invoice_no,
            carrier,
            charge[
                "CHARGE_NAME"
            ],
            charge[
                "CURRENCY_TYPE"
            ],
            charge[
                "AMOUNT"
            ],
        )

        inserted += 1

    cursor.close()

    return inserted


def rebuild_charge_summary(
    connection,
):
    cursor = connection.cursor()

    cursor.execute(
        """
        DELETE FROM dbo.InvoiceChargeSummary
        """
    )

    cursor.execute(
        """
        INSERT INTO dbo.InvoiceChargeSummary
        (
            CARRIER,
            CHARGE_NAME,
            CHARGE_COUNT
        )
        SELECT
            CARRIER,
            LOWER(
                LTRIM(
                    RTRIM(CHARGE_NAME)
                )
            ) AS CHARGE_NAME,
            COUNT(*) AS CHARGE_COUNT
        FROM dbo.InvoiceCharges
        WHERE CHARGE_NAME IS NOT NULL
        GROUP BY
            CARRIER,
            LOWER(
                LTRIM(
                    RTRIM(CHARGE_NAME)
                )
            )
        """
    )

    cursor.execute(
        """
        UPDATE ICS
        SET REMARK =
            CASE
                WHEN EXISTS
                (
                    SELECT 1
                    FROM ICMS.dbo.ChargeMaster CM
                    WHERE LOWER(
                        LTRIM(
                            RTRIM(
                                CM.ChargeName
                            )
                        )
                    ) =
                    LOWER(
                        LTRIM(
                            RTRIM(
                                ICS.CHARGE_NAME
                            )
                        )
                    )
                )
                THEN 'EXISTS'
                ELSE 'NEW'
            END
        FROM dbo.InvoiceChargeSummary ICS
        """
    )

    cursor.close()


def move_file(
    pdf_path,
    destination_dir,
):
    destination_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = (
        destination_dir
        / pdf_path.name
    )

    if destination.exists():
        stem = pdf_path.stem
        suffix = pdf_path.suffix
        counter = 1

        while destination.exists():
            destination = (
                destination_dir
                / f"{stem}_{counter}{suffix}"
            )

            counter += 1

    shutil.move(
        str(pdf_path),
        str(destination),
    )

    return destination


def move_to_failed(
    pdf_path,
):
    try:
        return move_file(
            pdf_path,
            FAILED_DIR,
        )
    except Exception:
        return None


def move_to_untemplated(
    pdf_path,
):
    return move_file(
        pdf_path,
        UNTEMPLATED_DIR,
    )


def process_pdf(
    pdf_path,
    master_module,
    charge_module,
    processed_hashes,
):
    print()
    print("=" * 90)
    print(
        f"NEW PDF: {pdf_path.name}"
    )
    print("=" * 90)

    try:
        pdf_hash = calculate_sha256(
            pdf_path
        )
    except Exception as exc:
        print(
            f"HASH ERROR: {exc}"
        )
        move_to_failed(
            pdf_path
        )
        return False

    if pdf_hash in processed_hashes:
        print(
            "EXACT DUPLICATE: SKIPPED"
        )

        try:
            destination = move_file(
                pdf_path,
                PROCESSED_DIR,
            )

            print(
                f"DUPLICATE MOVED TO: "
                f"{destination}"
            )

        except Exception as exc:
            print(
                f"DUPLICATE MOVE ERROR: "
                f"{exc}"
            )

            return False

        return True

    try:
        (
            master_text,
            master_tables,
            master_error,
        ) = extract_master_pdf_content(
            master_module,
            pdf_path,
        )
    except Exception as exc:
        print(
            f"MASTER PDF EXTRACTION ERROR: "
            f"{exc}"
        )

        try:
            move_to_failed(
                pdf_path
            )
        except Exception:
            pass

        return False

    if master_error:
        print(
            f"MASTER PDF EXTRACTION ERROR: "
            f"{master_error}"
        )

        try:
            move_to_failed(
                pdf_path
            )
        except Exception:
            pass

        return False

    carrier = detect_carrier(
        pdf_path,
        master_text,
    )

    if not carrier:
        print(
            "CARRIER: NOT DETECTED"
        )

        try:
            destination = move_to_untemplated(
                pdf_path
            )

            processed_hashes.add(
                pdf_hash
            )

            save_hashes(
                processed_hashes
            )

            print(
                f"MOVED TO: {destination}"
            )

            return True

        except Exception as exc:
            print(
                f"UNTEMPLATED MOVE ERROR: "
                f"{exc}"
            )

            return False

    print(
        f"CARRIER: {carrier}"
    )

    master_extractor = (
        get_master_extractor(
            master_module,
            carrier,
        )
    )

    charge_extractor = (
        get_charge_extractor(
            charge_module,
            carrier,
        )
    )

    charge_invoice_extractor = (
        get_charge_invoice_extractor(
            charge_module,
            carrier,
        )
    )

    invoice_result = None
    master_invoice_no = None
    charge_invoice_no = None
    charges = []

    try:
        (
            charge_text,
            charge_tables,
            charge_error,
        ) = extract_charge_pdf_content(
            charge_module,
            master_module,
            pdf_path,
        )
    except Exception as exc:
        print(
            f"CHARGE PDF EXTRACTION ERROR: "
            f"{exc}"
        )

        charge_text = master_text
        charge_tables = master_tables
        charge_error = str(exc)

    if charge_error:
        print(
            f"CHARGE PDF EXTRACTION WARNING: "
            f"{charge_error}"
        )

        charge_text = (
            master_text
            if master_text
            else ""
        )

        charge_tables = (
            master_tables
            if master_tables
            else []
        )

    if master_extractor is not None:
        try:
            invoice_result = master_extractor(
                master_text,
                master_tables,
            )

            if isinstance(
                invoice_result,
                dict,
            ):
                invoice_result = (
                    normalize_invoice_result(
                        invoice_result
                    )
                )

                master_invoice_no = (
                    invoice_result.get(
                        "INVOICE_NO"
                    )
                )

                print(
                    f"MASTER INVOICE NO: "
                    f"{master_invoice_no}"
                )

            else:
                print(
                    "MASTER EXTRACTOR RETURNED "
                    "INVALID RESULT"
                )

        except Exception as exc:
            print(
                f"MASTER EXTRACTION ERROR: "
                f"{exc}"
            )

    else:
        print(
            "MASTER INVOICE TEMPLATE: "
            "NOT AVAILABLE"
        )

    if charge_invoice_extractor is not None:
        try:
            charge_invoice_no = (
                charge_invoice_extractor(
                    charge_text
                )
            )

            if charge_invoice_no:
                charge_invoice_no = (
                    clean_text(
                        charge_invoice_no
                    )
                )

            print(
                f"CHARGE INVOICE NO: "
                f"{charge_invoice_no}"
            )

        except Exception as exc:
            print(
                f"CHARGE INVOICE NUMBER ERROR: "
                f"{exc}"
            )

    invoice_no = (
        master_invoice_no
        or charge_invoice_no
    )

    if carrier == "LMT":
        print(
            "LMT MODE: "
            "CHARGE EXTRACTION ONLY"
        )

    if charge_extractor is not None:
        try:
            charges = charge_extractor(
                charge_text,
                charge_tables,
            )

            if not isinstance(
                charges,
                list,
            ):
                charges = []

            print(
                f"CHARGES EXTRACTED: "
                f"{len(charges)}"
            )

        except Exception as exc:
            print(
                f"CHARGE EXTRACTION ERROR: "
                f"{exc}"
            )

            charges = []

    else:
        print(
            "CHARGE TEMPLATE: "
            "NOT AVAILABLE"
        )

    if carrier != "LMT":
        if invoice_result is None:
            print(
                "INVOICE RESULT NOT AVAILABLE"
            )

            try:
                destination = (
                    move_to_untemplated(
                        pdf_path
                    )
                )

                processed_hashes.add(
                    pdf_hash
                )

                save_hashes(
                    processed_hashes
                )

                print(
                    f"MOVED TO: {destination}"
                )

                return True

            except Exception as exc:
                print(
                    f"UNTEMPLATED MOVE ERROR: "
                    f"{exc}"
                )

                return False

        if not master_invoice_no:
            print(
                "MASTER INVOICE NUMBER "
                "NOT FOUND"
            )

            try:
                destination = (
                    move_to_untemplated(
                        pdf_path
                    )
                )

                processed_hashes.add(
                    pdf_hash
                )

                save_hashes(
                    processed_hashes
                )

                print(
                    f"MOVED TO: {destination}"
                )

                return True

            except Exception as exc:
                print(
                    f"UNTEMPLATED MOVE ERROR: "
                    f"{exc}"
                )

                return False

    if carrier == "LMT":
        if not charge_invoice_no:
            print(
                "LMT INVOICE NUMBER "
                "NOT FOUND"
            )

            try:
                destination = (
                    move_to_untemplated(
                        pdf_path
                    )
                )

                processed_hashes.add(
                    pdf_hash
                )

                save_hashes(
                    processed_hashes
                )

                print(
                    f"MOVED TO: {destination}"
                )

                return True

            except Exception as exc:
                print(
                    f"UNTEMPLATED MOVE ERROR: "
                    f"{exc}"
                )

                return False

    if not invoice_no:
        print(
            "NO INVOICE NUMBER AVAILABLE"
        )

        try:
            destination = (
                move_to_untemplated(
                    pdf_path
                )
            )

            processed_hashes.add(
                pdf_hash
            )

            save_hashes(
                processed_hashes
            )

            print(
                f"MOVED TO: {destination}"
            )

            return True

        except Exception as exc:
            print(
                f"UNTEMPLATED MOVE ERROR: "
                f"{exc}"
            )

            return False

    connection = None

    try:
        connection = connect_database()

        if carrier != "LMT":
            invoice_inserted = insert_invoice(
                connection,
                invoice_result,
            )

            print(
                f"INVOICE INSERTED: "
                f"{invoice_inserted}"
            )

        if charges:
            charges_inserted = insert_charges(
                connection,
                invoice_no,
                carrier,
                charges,
            )

            print(
                f"CHARGES INSERTED: "
                f"{charges_inserted}"
            )
        else:
            print(
                "CHARGES INSERTED: 0"
            )

        rebuild_charge_summary(
            connection
        )

        connection.commit()

        print(
            "CHARGE SUMMARY UPDATED"
        )

        connection.close()
        connection = None

    except Exception as exc:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass

            try:
                connection.close()
            except Exception:
                pass

        print(
            f"DATABASE ERROR: {exc}"
        )

        try:
            destination = move_to_failed(
                pdf_path
            )

            if destination:
                print(
                    f"FAILED PDF MOVED TO: "
                    f"{destination}"
                )

        except Exception:
            pass

        return False

    try:
        destination = move_file(
            pdf_path,
            PROCESSED_DIR,
        )

        print(
            f"PROCESSED PDF MOVED TO: "
            f"{destination}"
        )

    except Exception as exc:
        print(
            f"PROCESSED MOVE ERROR: "
            f"{exc}"
        )

        return False

    processed_hashes.add(
        pdf_hash
    )

    save_hashes(
        processed_hashes
    )

    print(
        f"SUCCESS: {pdf_path.name}"
    )

    return True


def process_existing_pdfs(
    master_module,
    charge_module,
    processed_hashes,
):
    pdf_files = get_pdf_files()

    if not pdf_files:
        return

    print(
        f"FOUND {len(pdf_files)} PDF(S) "
        f"IN INCOMING FOLDER"
    )

    for pdf_path in pdf_files:
        if not pdf_path.exists():
            continue

        process_pdf(
            pdf_path,
            master_module,
            charge_module,
            processed_hashes,
        )


def main():
    print("=" * 90)
    print(
        "INVOICE AUTOMATION WATCHER"
    )
    print("=" * 90)

    print(
        f"INCOMING DIRECTORY: "
        f"{INCOMING_DIR}"
    )

    print(
        f"MASTER FILE: "
        f"{MASTER_FILE}"
    )

    print(
        f"CHARGE FILE: "
        f"{CHARGE_FILE}"
    )

    print(
        f"DATABASE: "
        f"{DB_CONFIG['server']} / "
        f"{DB_CONFIG['database']}"
    )

    print(
        f"MASTER INVOICE CARRIERS: "
        f"{len(CARRIER_TEMPLATES)}"
    )

    print(
        f"CHARGE CARRIERS: "
        f"{len(CHARGE_CARRIERS)}"
    )

    print("=" * 90)

    INCOMING_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    UNTEMPLATED_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    PROCESSED_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    FAILED_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        master_module = load_module(
            "master_invoice_pipeline",
            MASTER_FILE,
        )

        charge_module = load_module(
            "charge_extraction_templates",
            CHARGE_FILE,
        )

    except Exception as exc:
        print(
            f"MODULE LOAD ERROR: {exc}"
        )

        sys.exit(1)

    processed_hashes = load_hashes()

    print(
        "MASTER MODULE LOADED"
    )

    print(
        "CHARGE MODULE LOADED"
    )

    print(
        "AUTOMATION IS RUNNING..."
    )

    process_existing_pdfs(
        master_module,
        charge_module,
        processed_hashes,
    )

    while True:
        try:
            pdf_files = get_pdf_files()

            for pdf_path in pdf_files:
                if not pdf_path.exists():
                    continue

                process_pdf(
                    pdf_path,
                    master_module,
                    charge_module,
                    processed_hashes,
                )

            time.sleep(
                POLL_SECONDS
            )

        except KeyboardInterrupt:
            print()
            print(
                "AUTOMATION STOPPED"
            )
            break

        except Exception as exc:
            print(
                f"WATCHER ERROR: {exc}"
            )

            time.sleep(
                POLL_SECONDS
            )


if __name__ == "__main__":
    main()

