# Invoice PDF to SQL Pipeline

An automated data extraction, validation, and staging pipeline designed to parse semi-structured multi-carrier ocean freight PDF invoices, enforce SHA-256 duplicate protection, and ingest relational invoice data into Microsoft SQL Server with charge-master reconciliation.

## 📌 Architecture & Data Flow

```text
               Incoming PDF Invoice
                        │
                        ▼
               invoice_automation.py
            ┌───────────┴───────────┐
            ▼                       ▼
 master_invoice_pipeline.py     charge_extraction_templates.py
 (17 Header & Logistics Fields)  (Line-Item Charges & Currency)
            │                       │
            ▼                       ▼
     sql_insertion.py           charges_name_insertion.py
 (SHA-256 Check & Staging Load) (Charge-level Deduplication)
            │                       │
            ▼                       ▼
 dbo.OceanFreightInvoices_All   dbo.InvoiceCharges
                                    │
                                    ▼
                         dbo.InvoiceChargeSummary
                       (Reconciliation vs ChargeMaster)
```

## 🛠️ Tech Stack
- **Language:** Python (`pdfplumber`, `pyodbc`, `hashlib`, `re`)
- **Database:** Microsoft SQL Server (T-SQL)
- **Concepts:** ETL Pipeline, Data Normalization, Database Staging, Transaction Safety, SHA-256 Deduplication

## 📂 Core Scripts
- `master_invoice_pipeline.py`: Carrier-specific extraction of 17 core header and logistics fields.
- `charge_extraction_templates.py`: Carrier-specific line-item fee and currency extraction templates.
- `sql_insertion.py`: Transactional bulk-loading into `dbo.OceanFreightInvoices_Staging`.
- `charges_name_insertion.py`: Bulk insertion of individual charge items into `dbo.InvoiceCharges`.
- `invoice_automation.py`: Master directory watcher daemon and ChargeMaster reconciliation orchestrator.

## 🛡️ Data Privacy Notice
All connection strings, server endpoints, and proprietary logistics documents have been sanitized with synthetic mock configurations in compliance with non-disclosure obligations.