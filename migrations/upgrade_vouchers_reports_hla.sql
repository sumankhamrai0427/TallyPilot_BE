-- =====================================================================
-- TallyPilot V2: HLA Section 7 (Vouchers) & Section 10 (Reporting Engine)
-- Database Upgrade Script for MySQL
-- Database: TallyPilot_V2
-- =====================================================================

USE TallyPilot_V2;

-- 1. Expand vouchers.voucher_type to 13 HLA standard types
ALTER TABLE vouchers MODIFY COLUMN voucher_type ENUM(
    'Payment', 'Receipt', 'Contra', 'Journal', 'Purchase', 'Sales',
    'Debit Note', 'Credit Note', 'Payroll', 'Opening Balance',
    'Fixed Asset', 'Depreciation', 'Adjustment'
) NOT NULL DEFAULT 'Journal';

-- 2. Add reversal tracking columns to vouchers table
ALTER TABLE vouchers 
    ADD COLUMN reversal_voucher_id INT NULL AFTER status,
    ADD COLUMN reversed_at DATETIME NULL AFTER posted_at,
    ADD COLUMN reversal_reason VARCHAR(255) NULL AFTER reversal_voucher_id;

-- 3. Add line item enhancements to voucher_lines table
ALTER TABLE voucher_lines 
    ADD COLUMN cost_centre VARCHAR(100) NULL AFTER narration,
    ADD COLUMN tax_code VARCHAR(50) NULL AFTER cost_centre,
    ADD COLUMN party_reference VARCHAR(100) NULL AFTER tax_code;

