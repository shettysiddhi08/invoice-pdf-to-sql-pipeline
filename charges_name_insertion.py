import importlib.util
from pathlib import Path
import pyodbc

BASE_DIR = Path(r"C:\Users\Siddhi\Desktop\sorted_PDFs")
MASTER_FILE = BASE_DIR / "charge_extraction_templates.py"

DB_CONFIG = {
    "server": "10.10.0.72",
    "database": "Shipping_invo_db",
    "username": "sa",
    "password": "pass@2020$",
    "driver": "ODBC Driver 17 for SQL Server",
}

CHARGE_TABLE = "dbo.InvoiceCharges"

CARRIER_TEMPLATES = [
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


def load_master_module():
    spec = importlib.util.spec_from_file_location(
        "master_charge_extraction",
        MASTER_FILE,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"Unable to load master file: {MASTER_FILE}"
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def get_connection():
    connection_string = (
        f"DRIVER={{{DB_CONFIG['driver']}}};"
        f"SERVER={DB_CONFIG['server']};"
        f"DATABASE={DB_CONFIG['database']};"
        f"UID={DB_CONFIG['username']};"
        f"PWD={DB_CONFIG['password']};"
        f"TrustServerCertificate=yes;"
    )

    return pyodbc.connect(connection_string)


def validate_charge_rows(rows):
    limits = {
        "INVOICE_NO": 200,
        "CARRIER": 200,
        "CHARGE_NAME": 500,
        "CURRENCY_TYPE": 20,
    }

    valid_rows = []

    for row in rows:
        valid = True

        for field, limit in limits.items():
            value = row.get(field)

            if value is not None and len(str(value)) > limit:
                print(
                    f"WARNING: {field} exceeds {limit} characters. "
                    f"Value will be truncated."
                )
                row[field] = str(value)[:limit]

        if row.get("INVOICE_NO") is not None:
            row["INVOICE_NO"] = str(row["INVOICE_NO"]).strip()

        if row.get("CARRIER") is not None:
            row["CARRIER"] = str(row["CARRIER"]).strip()

        if row.get("CHARGE_NAME") is not None:
            row["CHARGE_NAME"] = str(row["CHARGE_NAME"]).strip()

        if row.get("CURRENCY_TYPE") is not None:
            row["CURRENCY_TYPE"] = str(row["CURRENCY_TYPE"]).strip().upper()

        if row.get("AMOUNT") is not None:
            try:
                row["AMOUNT"] = float(row["AMOUNT"])
            except Exception:
                print(
                    f"WARNING: Invalid amount skipped: "
                    f"{row.get('AMOUNT')}"
                )
                valid = False

        if valid:
            valid_rows.append(row)

    return valid_rows


def normalize_charge_rows(invoice_no, carrier_name, charges):
    rows = []

    if not charges:
        return rows

    for charge in charges:
        if not isinstance(charge, dict):
            continue

        charge_name = charge.get("CHARGE_NAME")
        currency_type = charge.get("CURRENCY_TYPE")
        amount = charge.get("AMOUNT")

        if charge_name is None:
            continue

        if str(charge_name).strip() == "":
            continue

        rows.append(
            {
                "INVOICE_NO": invoice_no,
                "CARRIER": carrier_name,
                "CHARGE_NAME": str(charge_name).strip(),
                "CURRENCY_TYPE": (
                    str(currency_type).strip().upper()
                    if currency_type is not None
                    else None
                ),
                "AMOUNT": amount,
            }
        )

    return rows


def process_carrier(module, carrier_name):
    folder = BASE_DIR / carrier_name

    if not folder.exists():
        print(
            f"WARNING: Folder not found: {folder}"
        )
        return []

    if carrier_name not in module.CHARGE_TEMPLATES:
        print(
            f"WARNING: Charge template not found for: "
            f"{carrier_name}"
        )
        return []

    if carrier_name not in module.INVOICE_TEMPLATES:
        print(
            f"WARNING: Invoice template not found for: "
            f"{carrier_name}"
        )
        return []

    charge_extractor = module.CHARGE_TEMPLATES[carrier_name]
    invoice_extractor = module.INVOICE_TEMPLATES[carrier_name]

    pdf_files, duplicate_count = module.get_unique_pdf_files(
        folder,
        limit=None,
    )

    print()
    print("=" * 70)
    print(f"CARRIER: {carrier_name}")
    print("=" * 70)
    print(f"Folder: {folder}")
    print(f"Unique PDFs: {len(pdf_files)}")
    print(f"Exact duplicates skipped: {duplicate_count}")

    carrier_rows = []
    failed_files = 0
    invoices_with_charges = 0

    for index, pdf_path in enumerate(pdf_files, start=1):
        print()
        print(
            f"[{index}/{len(pdf_files)}] "
            f"{pdf_path.name}"
        )

        try:
            text, tables, error = module.extract_pdf_content(
                pdf_path
            )

            if error:
                print(f"ERROR: {error}")
                failed_files += 1
                continue

            invoice_no = invoice_extractor(text)

            if not invoice_no:
                print("Invoice No: None")
            else:
                print(f"Invoice No: {invoice_no}")

            charges = charge_extractor(
                text,
                tables,
            )

            if not charges:
                print("Charges found: 0")
                continue

            invoices_with_charges += 1

            print(
                f"Charges found: {len(charges)}"
            )

            rows = normalize_charge_rows(
                invoice_no,
                carrier_name,
                charges,
            )

            for row in rows:
                print(
                    f"  {row['CHARGE_NAME']} | "
                    f"{row['CURRENCY_TYPE']} | "
                    f"{row['AMOUNT']}"
                )

            carrier_rows.extend(rows)

        except Exception as e:
            failed_files += 1
            print(
                f"ERROR PROCESSING: "
                f"{pdf_path.name} -> {e}"
            )

    print()
    print("-" * 70)
    print(f"CARRIER SUMMARY: {carrier_name}")
    print(f"Unique PDFs: {len(pdf_files)}")
    print(f"Duplicates skipped: {duplicate_count}")
    print(f"Invoices with charges: {invoices_with_charges}")
    print(f"Charge rows: {len(carrier_rows)}")
    print(f"Failed files: {failed_files}")
    print("-" * 70)

    return carrier_rows


def insert_into_charge_table(rows):
    if not rows:
        print()
        print("No charge rows to insert.")
        return

    rows = validate_charge_rows(rows)

    if not rows:
        print()
        print("No valid charge rows to insert.")
        return

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        insert_sql = f"""
            INSERT INTO {CHARGE_TABLE}
            (
                INVOICE_NO,
                CARRIER,
                CHARGE_NAME,
                CURRENCY_TYPE,
                AMOUNT,
                DATE_EXTRACTED
            )
            VALUES
            (
                ?,
                ?,
                ?,
                ?,
                ?,
                GETDATE()
            )
        """

        data = [
            (
                row["INVOICE_NO"],
                row["CARRIER"],
                row["CHARGE_NAME"],
                row["CURRENCY_TYPE"],
                row["AMOUNT"],
            )
            for row in rows
        ]

        cursor.fast_executemany = True

        cursor.executemany(
            insert_sql,
            data,
        )

        cursor.execute(
            f"SELECT COUNT(*) FROM {CHARGE_TABLE}"
        )

        total_count = cursor.fetchone()[0]

        connection.commit()

        print()
        print("=" * 70)
        print("SQL INSERT COMPLETED")
        print("=" * 70)
        print(f"Rows inserted: {len(rows)}")
        print(
            f"Total rows in {CHARGE_TABLE}: "
            f"{total_count}"
        )

    except Exception as e:
        if connection:
            connection.rollback()

        print()
        print("=" * 70)
        print("SQL INSERT FAILED")
        print("=" * 70)
        print(e)

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()


def main():
    print("=" * 70)
    print("CHARGES SQL INSERTION")
    print("=" * 70)
    print(f"Master file: {MASTER_FILE}")
    print(f"Target table: {CHARGE_TABLE}")
    print("=" * 70)

    module = load_master_module()

    all_rows = []

    carrier_summary = []

    for carrier_name in CARRIER_TEMPLATES:
        rows = process_carrier(
            module,
            carrier_name,
        )

        all_rows.extend(rows)

        carrier_summary.append(
            (
                carrier_name,
                len(rows),
            )
        )

    print()
    print("=" * 70)
    print("FINAL EXTRACTION SUMMARY")
    print("=" * 70)

    for carrier_name, row_count in carrier_summary:
        print(
            f"{carrier_name}: "
            f"{row_count} charge rows"
        )

    print()
    print(
        f"TOTAL CHARGE ROWS: {len(all_rows)}"
    )

    insert_into_charge_table(all_rows)

    print()
    print("=" * 70)
    print("PROCESS COMPLETED")
    print("=" * 70)


if __name__ == "__main__":
    main()