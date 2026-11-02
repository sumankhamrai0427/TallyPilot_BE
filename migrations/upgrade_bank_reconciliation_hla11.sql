-- =====================================================================
-- TallyPilot V2: HLA Section 11 (Bank Statement Processing & Reconciliation)
-- Database Upgrade Script for MySQL
-- Database: TallyPilot_V2
-- =====================================================================

USE TallyPilot_V2;

-- Add duplicate and existing voucher matching fields to bank_transactions
ALTER TABLE bank_transactions 
    ADD COLUMN matched_voucher_id INT NULL AFTER bank_ledger_id,
    ADD COLUMN clearance_date DATE NULL AFTER value_date,
    ADD COLUMN is_duplicate TINYINT(1) NOT NULL DEFAULT 0 AFTER is_skipped;

