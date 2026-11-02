-- =====================================================================
-- TallyPilot V2: Clean Reset for Fresh Testing
-- Truncates all transactional, posting, audit, and batch data.
-- KEEPS MASTER TABLES: companies, financial_years, account_groups,
--                      ledger_accounts, parties, application_settings,
--                      ledger_mappings, tally_ledgers.
-- =====================================================================

USE TallyPilot_V2;

-- Disable Foreign Key Checks to allow truncation
SET FOREIGN_KEY_CHECKS = 0;

-- 1. Truncate AI Assistant & Chat logs
TRUNCATE TABLE chat_messages;
TRUNCATE TABLE chat_sessions;

-- 2. Truncate Audit Logs & Tally Submissions
TRUNCATE TABLE audit_logs;
TRUNCATE TABLE tally_submissions;

-- 3. Truncate Bank Reconciliation
TRUNCATE TABLE bank_reconciliation_items;
TRUNCATE TABLE bank_reconciliations;

-- 4. Truncate Double-Entry General Ledger & Vouchers
TRUNCATE TABLE general_ledger;
TRUNCATE TABLE voucher_approvals;
TRUNCATE TABLE voucher_lines;
TRUNCATE TABLE vouchers;

-- 5. Truncate Bank Transaction Pipeline & Classifications
TRUNCATE TABLE approval_records;
TRUNCATE TABLE human_reviews;
TRUNCATE TABLE transaction_classifications;
TRUNCATE TABLE bank_transactions;

-- 6. Truncate Document & Batch Hub
TRUNCATE TABLE documents;
TRUNCATE TABLE import_batches;

-- Re-enable Foreign Key Checks
SET FOREIGN_KEY_CHECKS = 1;

-- 7. Reset Ledger Account Current Balances back to their Opening Balances
UPDATE ledger_accounts SET current_balance = opening_balance;

SELECT 'Successfully truncated all transactions! Master tables and Chart of Accounts are preserved.' AS Status;

