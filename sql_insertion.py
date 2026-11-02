import importlib.util
from pathlib import Path

import pyodbc


BASE_DIR = Path(r"C:\Users\Siddhi\Desktop\sorted_PDFs")
MASTER_FILE = BASE_DIR / "master_invoice_pipeline.py"

DB_CONFIG = {
    "server": "10.10.0.72",
    "database": "Shipping_invo_db",
    "username": "[user_name]",
    "password": "**********",
    "driver": "ODBC Driver 17 for SQL Server",
}

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

CARRIER_TEMPLATES = [
    "Maersk_Only"
    "CMA CGM",
    "Hapag-Lloyd",
    "HMM",
    "Hub and Links Logistics",
    "J M Baxi",
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
        "master_invoice_pipeline",
        MASTER_FILE,
    )

    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"Could not load master pipeline: {MASTER_FILE}"
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
        "TrustServerCertificate=yes;"
    )

    return pyodbc.connect(connection_string)


def validate_string_lengths(rows):
    limits = {
        "INVOICE_NO": 200,
        "IRN_NO": 500,
        "COMPANY": 500,
        "PAN_NO": 100,
        "BILL_OF_LADING": 500,
        "VESSEL": 500,
        "POL": 300,
        "POD": 300,
        "CURRENCY": 50,
    }

    errors = []

    for row_number, row in enumerate(rows, start=1):
        for field, limit in limits.items():
            value = row.get(field)

            if value is None:
                continue

            value = str(value)

            if len(value) > limit:
                errors.append(
                    (
                        row_number,
                        field,
                        len(value),
                        limit,
                        value[:300],
                    )
                )

    return errors


def normalize_row(result):
    row = {}

    for field in TARGET_FIELDS:
        value = result.get(field)

        if value == "":
            value = None

        row[field] = value

    return row


def process_carrier(module, carrier_name):
    folder = BASE_DIR / carrier_name

    print()
    print("=" * 70)
    print(f"PROCESSING: {carrier_name}")
    print("=" * 70)

    if not folder.exists():
        print(f"Folder not found: {folder}")
        return []

    extractor_name = module.CARRIER_TEMPLATES.get(carrier_name)

    if not extractor_name:
        print(f"No extractor registered for: {carrier_name}")
        return []

    extractor = getattr(module, extractor_name)

    pdf_files, duplicate_count = module.get_unique_pdf_files(
        folder,
        limit=None,
    )

    total_pdf_files = len(list(folder.glob("*.pdf")))

    print(f"PDFs found           : {total_pdf_files}")
    print(f"Unique PDFs processed: {len(pdf_files)}")
    print(f"Duplicates skipped   : {duplicate_count}")

    rows = []
    failed = []

    for index, pdf_path in enumerate(pdf_files, start=1):
        try:
            text, tables, error = module.extract_pdf_content(pdf_path)

            if error:
                raise RuntimeError(error)

            result = extractor(text, tables)
            row = normalize_row(result)

            rows.append(row)

        except Exception as exc:
            failed.append(
                {
                    "file": pdf_path.name,
                    "error": str(exc),
                }
            )

        if index % 100 == 0 or index == len(pdf_files):
            print(
                f"Processed: {index}/{len(pdf_files)} | "
                f"Successful: {len(rows)} | "
                f"Failed: {len(failed)}"
            )

    print()
    print(f"{carrier_name} summary")
    print("-" * 70)
    print(f"PDFs found           : {total_pdf_files}")
    print(f"Unique PDFs processed: {len(pdf_files)}")
    print(f"Duplicates skipped   : {duplicate_count}")
    print(f"Successful            : {len(rows)}")
    print(f"Failed                : {len(failed)}")

    if failed:
        print()
        print("FAILED FILES")
        print("-" * 70)

        for item in failed:
            print(item["file"])
            print(f"  Error: {item['error']}")

    return rows


def insert_into_staging(rows):
    if not rows:
        print()
        print("No rows available for SQL insertion.")
        return

    length_errors = validate_string_lengths(rows)

    if length_errors:
        print()
        print("=" * 70)
        print("STRING LENGTH VALIDATION FAILED")
        print("=" * 70)

        for row_number, field, actual, allowed, value in length_errors:
            print(
                f"Row {row_number} | "
                f"{field} | "
                f"Length {actual} | "
                f"Allowed {allowed}"
            )
            print(f"Value: {value}")
            print()

        print("SQL insertion stopped.")
        print("Staging table was NOT truncated.")

        return

    connection = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        print()
        print("=" * 70)
        print("SQL SERVER CONNECTION")
        print("=" * 70)
        print("Connected successfully.")

        print()
        print("=" * 70)
        print("PREPARING STAGING TABLE")
        print("=" * 70)

        cursor.execute(
            f"TRUNCATE TABLE {STAGING_TABLE}"
        )

        print("Staging table truncated inside transaction.")

        column_sql = ", ".join(
            f"[{field}]"
            for field in TARGET_FIELDS
        )

        placeholders = ", ".join(
            "?"
            for _ in TARGET_FIELDS
        )

        insert_sql = (
            f"INSERT INTO {STAGING_TABLE} "
            f"({column_sql}) "
            f"VALUES ({placeholders})"
        )

        values = [
            tuple(
                row.get(field)
                for field in TARGET_FIELDS
            )
            for row in rows
        ]

        print()
        print("=" * 70)
        print("INSERTING INTO STAGING TABLE")
        print("=" * 70)

        cursor.fast_executemany = True

        cursor.executemany(
            insert_sql,
            values,
        )

        inserted = len(values)

        print(f"Rows inserted: {inserted}")

        cursor.execute(
            f"SELECT COUNT(*) FROM {STAGING_TABLE}"
        )

        count = cursor.fetchone()[0]

        if count != inserted:
            raise RuntimeError(
                f"SQL row count mismatch. "
                f"Expected {inserted}, found {count}."
            )

        connection.commit()

        print()
        print("=" * 70)
        print("SQL INSERTION COMPLETE")
        print("=" * 70)
        print(f"Rows prepared : {len(rows)}")
        print(f"Rows inserted : {inserted}")
        print(f"Rows in table : {count}")

    except Exception:
        if connection is not None:
            connection.rollback()

        print()
        print("=" * 70)
        print("SQL INSERTION FAILED")
        print("=" * 70)
        print("Transaction rolled back.")
        print("Existing staging data was preserved.")

        raise

    finally:
        if connection is not None:
            connection.close()


def main():
    print("=" * 70)
    print("MULTI-CARRIER SQL INSERTION PIPELINE")
    print("=" * 70)

    if not MASTER_FILE.exists():
        print()
        print("Master file not found:")
        print(MASTER_FILE)
        return

    module = load_master_module()

    all_rows = []
    carrier_counts = {}

    for carrier_name in CARRIER_TEMPLATES:
        rows = process_carrier(
            module,
            carrier_name,
        )

        carrier_counts[carrier_name] = len(rows)
        all_rows.extend(rows)

    print()
    print("=" * 70)
    print("ALL CARRIERS PROCESSING COMPLETE")
    print("=" * 70)

    for carrier_name, count in carrier_counts.items():
        print(
            f"{carrier_name}: {count}"
        )

    print()
    print(f"Total rows ready for SQL: {len(all_rows)}")

    if not all_rows:
        print("No rows to insert.")
        return

    insert_into_staging(all_rows)

    print()
    print("=" * 70)
    print("FINAL STATUS")
    print("=" * 70)
    print(
        f"{STAGING_TABLE} was rebuilt successfully."
    )


if __name__ == "__main__":
    main()