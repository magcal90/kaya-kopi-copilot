-- Canonical parsed-data schema for the Kaya Kopi MySQL 8 database.
CREATE DATABASE IF NOT EXISTS kayakopi CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE kayakopi;

CREATE TABLE IF NOT EXISTS source_document (
    source_document_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    source_version_key CHAR(64) NOT NULL UNIQUE,
    source_uri VARCHAR(500) NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    document_type VARCHAR(40) NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    raw_text LONGTEXT NULL,
    ocr_json_uri VARCHAR(500) NULL,
    mean_ocr_confidence DECIMAL(5,2) NULL,
    extraction_status VARCHAR(30) NOT NULL,
    ingested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_source_document_type (document_type),
    INDEX idx_source_document_uri (source_uri(191))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS outlet_alias (
    outlet_alias_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    outlet_id INT NOT NULL,
    evidence_document_id BIGINT NOT NULL,
    alias_code VARCHAR(10) NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE NULL,
    validation_status VARCHAR(30) NOT NULL,
    UNIQUE KEY uk_outlet_alias_period (alias_code, effective_from),
    CONSTRAINT fk_outlet_alias_outlet FOREIGN KEY (outlet_id) REFERENCES outlets(outlet_id),
    CONSTRAINT fk_outlet_alias_evidence FOREIGN KEY (evidence_document_id)
        REFERENCES source_document(source_document_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS daily_outlet_summary (
    daily_summary_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    record_import_key VARCHAR(32) NOT NULL UNIQUE,
    source_document_id BIGINT NOT NULL,
    outlet_id INT NOT NULL,
    source_row_number INT NOT NULL,
    source_locator VARCHAR(30) NOT NULL,
    outlet_code_raw VARCHAR(10) NOT NULL,
    raw_business_date VARCHAR(20) NOT NULL,
    business_date DATE NOT NULL,
    raw_sales_amount VARCHAR(30) NOT NULL,
    sales_amount_sgd DECIMAL(12,2) NOT NULL,
    raw_reported_volume VARCHAR(20) NOT NULL,
    reported_volume INT NOT NULL,
    volume_measure VARCHAR(20) NOT NULL,
    raw_wastage_kg VARCHAR(20) NULL,
    wastage_kg DECIMAL(10,3) NULL,
    remarks VARCHAR(255) NULL,
    weather VARCHAR(20) NULL,
    validation_status VARCHAR(30) NOT NULL,
    validation_notes TEXT NULL,
    UNIQUE KEY uk_daily_source_row (source_document_id, source_row_number),
    INDEX idx_daily_outlet_date (outlet_id, business_date),
    CONSTRAINT fk_daily_source FOREIGN KEY (source_document_id)
        REFERENCES source_document(source_document_id),
    CONSTRAINT fk_daily_outlet FOREIGN KEY (outlet_id) REFERENCES outlets(outlet_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS staff_roster (
    staff_roster_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    source_document_id BIGINT NOT NULL UNIQUE,
    roster_month DATE NOT NULL,
    validation_status VARCHAR(30) NOT NULL,
    CONSTRAINT fk_staff_roster_source FOREIGN KEY (source_document_id)
        REFERENCES source_document(source_document_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS staff_assignment (
    staff_assignment_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    assignment_import_key VARCHAR(32) NOT NULL UNIQUE,
    staff_roster_id BIGINT NOT NULL,
    outlet_id INT NOT NULL,
    staff_key VARCHAR(32) NOT NULL,
    staff_name VARCHAR(160) NOT NULL,
    role VARCHAR(80) NOT NULL,
    raw_hourly_rate VARCHAR(30) NOT NULL,
    hourly_rate_sgd DECIMAL(8,2) NULL,
    rate_status VARCHAR(30) NOT NULL,
    source_row_number INT NOT NULL,
    source_locator VARCHAR(80) NOT NULL,
    UNIQUE KEY uk_staff_assignment_source_row (staff_roster_id, source_row_number),
    INDEX idx_staff_assignment_outlet (outlet_id),
    INDEX idx_staff_assignment_staff_key (staff_key),
    CONSTRAINT fk_staff_assignment_roster FOREIGN KEY (staff_roster_id)
        REFERENCES staff_roster(staff_roster_id),
    CONSTRAINT fk_staff_assignment_outlet FOREIGN KEY (outlet_id)
        REFERENCES outlets(outlet_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS staff_shift (
    staff_shift_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    shift_import_key VARCHAR(32) NOT NULL UNIQUE,
    staff_assignment_id BIGINT NOT NULL,
    day_of_week VARCHAR(3) NOT NULL,
    raw_shift_code VARCHAR(10) NOT NULL,
    paid_hours DECIMAL(5,2) NULL,
    validation_status VARCHAR(30) NOT NULL,
    UNIQUE KEY uk_staff_shift_assignment_day (staff_assignment_id, day_of_week),
    CONSTRAINT fk_staff_shift_assignment FOREIGN KEY (staff_assignment_id)
        REFERENCES staff_assignment(staff_assignment_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS supplier (
    supplier_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    supplier_code VARCHAR(10) NOT NULL UNIQUE,
    canonical_name VARCHAR(120) NOT NULL,
    validation_status VARCHAR(30) NOT NULL,
    UNIQUE KEY uk_supplier_canonical_name (canonical_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS supplier_invoice (
    supplier_invoice_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    source_document_id BIGINT NOT NULL UNIQUE,
    supplier_purchase_id INT NULL UNIQUE,
    invoice_number VARCHAR(24) NOT NULL,
    supplier_name VARCHAR(120) NOT NULL,
    supplier_address VARCHAR(255) NOT NULL,
    gst_registration_number VARCHAR(30) NOT NULL,
    invoice_date DATE NOT NULL,
    bill_to VARCHAR(255) NOT NULL,
    subtotal DECIMAL(12,2) NOT NULL,
    gst_rate_percent DECIMAL(5,2) NOT NULL,
    gst_amount DECIMAL(12,2) NOT NULL,
    total_amount DECIMAL(12,2) NOT NULL,
    payment_terms VARCHAR(80) NULL,
    received_condition VARCHAR(120) NULL,
    mean_ocr_confidence DECIMAL(5,2) NULL,
    arithmetic_valid BOOLEAN NOT NULL,
    extraction_status VARCHAR(30) NOT NULL,
    review_notes TEXT NULL,
    INDEX idx_invoice_number (invoice_number),
    INDEX idx_invoice_supplier_date (supplier_name, invoice_date),
    CONSTRAINT fk_invoice_source FOREIGN KEY (source_document_id)
        REFERENCES source_document(source_document_id),
    CONSTRAINT fk_invoice_purchase FOREIGN KEY (supplier_purchase_id)
        REFERENCES supplier_purchases(purchase_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS supplier_invoice_item (
    supplier_invoice_item_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    supplier_invoice_id BIGINT NOT NULL,
    line_number INT NOT NULL,
    description VARCHAR(255) NULL,
    quantity DECIMAL(12,3) NULL,
    unit_price DECIMAL(12,4) NULL,
    amount DECIMAL(12,2) NULL,
    mean_field_confidence DECIMAL(5,2) NULL,
    line_total_valid BOOLEAN NOT NULL,
    extraction_status VARCHAR(30) NOT NULL,
    review_notes TEXT NULL,
    UNIQUE KEY uk_invoice_item_line (supplier_invoice_id, line_number),
    INDEX idx_invoice_item_description (description),
    CONSTRAINT fk_invoice_item_invoice FOREIGN KEY (supplier_invoice_id)
        REFERENCES supplier_invoice(supplier_invoice_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS purchase_invoice_reconciliation (
    reconciliation_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    supplier_purchase_id INT NOT NULL UNIQUE,
    supplier_invoice_id BIGINT NULL UNIQUE,
    reconciliation_status VARCHAR(30) NOT NULL,
    match_method VARCHAR(50) NULL,
    legacy_subtotal_sgd DECIMAL(12,2) NOT NULL,
    scanned_subtotal_sgd DECIMAL(12,2) NULL,
    subtotal_difference_sgd DECIMAL(12,2) NULL,
    validation_status VARCHAR(30) NOT NULL,
    reconciled_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_reconciliation_purchase FOREIGN KEY (supplier_purchase_id)
        REFERENCES supplier_purchases(purchase_id),
    CONSTRAINT fk_reconciliation_invoice FOREIGN KEY (supplier_invoice_id)
        REFERENCES supplier_invoice(supplier_invoice_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS document_chunk (
    document_chunk_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    chunk_import_key VARCHAR(32) NOT NULL UNIQUE,
    source_document_id BIGINT NOT NULL,
    source_type VARCHAR(30) NOT NULL,
    occurred_at DATETIME NULL,
    author VARCHAR(160) NULL,
    title VARCHAR(255) NULL,
    chunk_text LONGTEXT NOT NULL,
    source_locator VARCHAR(60) NOT NULL,
    embedding_ref VARCHAR(255) NULL,
    FULLTEXT KEY ft_document_chunk_text (title, chunk_text),
    INDEX idx_chunk_source_type_time (source_type, occurred_at),
    CONSTRAINT fk_chunk_source FOREIGN KEY (source_document_id)
        REFERENCES source_document(source_document_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS document_entity_mention (
    mention_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    document_chunk_id BIGINT NOT NULL,
    resolved_outlet_id INT NULL,
    entity_type VARCHAR(20) NOT NULL,
    mention_text VARCHAR(160) NOT NULL,
    canonical_key VARCHAR(160) NOT NULL,
    resolution_status VARCHAR(30) NOT NULL,
    UNIQUE KEY uk_chunk_entity (document_chunk_id, entity_type, canonical_key),
    INDEX idx_mention_canonical (entity_type, canonical_key),
    CONSTRAINT fk_mention_chunk FOREIGN KEY (document_chunk_id)
        REFERENCES document_chunk(document_chunk_id),
    CONSTRAINT fk_mention_outlet FOREIGN KEY (resolved_outlet_id) REFERENCES outlets(outlet_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS data_quality_issue (
    issue_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    issue_import_key VARCHAR(32) NOT NULL UNIQUE,
    source_document_id BIGINT NOT NULL,
    record_type VARCHAR(40) NOT NULL,
    record_key VARCHAR(64) NULL,
    source_locator VARCHAR(60) NULL,
    rule_code VARCHAR(60) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    details TEXT NOT NULL,
    resolution_status VARCHAR(30) NOT NULL,
    detected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_quality_status (resolution_status, severity),
    INDEX idx_quality_rule (rule_code),
    CONSTRAINT fk_quality_source FOREIGN KEY (source_document_id)
        REFERENCES source_document(source_document_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
