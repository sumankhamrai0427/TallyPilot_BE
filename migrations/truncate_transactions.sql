-- =====================================================================
-- TallyPilot V2: Clean Database Reset Scripts
-- Two Modes available:
--   MODE 1 (RECOMMENDED): Operational & Transactional Reset (Zero state)
--   MODE 2: 100% Complete Ground Zero Reset (All tables wiped)
-- =====================================================================

USE TallyPilot_V2;

-- Disable Foreign Key Checks to allow clean truncation
SET FOREIGN_KEY_CHECKS = 0;

-- =====================================================================
-- SECTION A: Truncate All Transactional, Processing & Audit Data
-- =====================================================================

-- 1. AI Assistant & Chat History
TRUNCATE TABLE chat_messages;
TRUNCATE TABLE chat_sessions;

-- 2. Audit Trails & External Sync Logs
TRUNCATE TABLE audit_logs;
TRUNCATE TABLE tally_submissions;

-- 3. Bank Reconciliation Module
TRUNCATE TABLE bank_reconciliation_items;
TRUNCATE TABLE bank_reconciliations;

-- 4. Double-Entry Core: General Ledger & Vouchers
TRUNCATE TABLE general_ledger;
TRUNCATE TABLE voucher_approvals;
TRUNCATE TABLE voucher_lines;
TRUNCATE TABLE vouchers;

-- 5. Ingestion Pipeline, Approvals & Review Queue
TRUNCATE TABLE approval_records;
TRUNCATE TABLE human_reviews;
TRUNCATE TABLE transaction_classifications;
TRUNCATE TABLE bank_transactions;

-- 6. Statement Files, Document Store & Batches
TRUNCATE TABLE documents;
TRUNCATE TABLE import_batches;

-- 7. Tally Sync & Mappings (Optional: Clears external sync cache)
TRUNCATE TABLE ledger_mappings;
TRUNCATE TABLE tally_ledgers;

-- =====================================================================
-- SECTION B: Reset Master Balances to ₹0.00
-- =====================================================================
-- Resets all ledger current balances to ₹0.00 (or opening_balance)
UPDATE ledger_accounts SET current_balance = 0.00;

-- Re-enable Foreign Key Checks
SET FOREIGN_KEY_CHECKS = 1;

SELECT 'SUCCESS: All 16 transactional and log tables truncated to 0! Ledger balances reset to ₹0.00. Ready for fresh statement testing.' AS Status;


