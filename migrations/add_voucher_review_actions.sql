-- ============================================================================
-- TallyPilot Database Migration: HLA Section 9.4 Voucher Review Actions
-- Database: TallyPilot_V2
-- ============================================================================

USE TallyPilot_V2;

-- ১. Vouchers টেবিলে REJECTED এবং HOLD স্ট্যাটাস সাপোর্ট যোগ করা
ALTER TABLE vouchers 
  MODIFY COLUMN status ENUM('DRAFT', 'UNDER_REVIEW', 'APPROVED', 'POSTED', 'REVERSED', 'CANCELLED', 'REJECTED', 'HOLD') 
  NOT NULL DEFAULT 'DRAFT';

-- ২. Vouchers টেবিলে রিজেকশনের কারণ লিখে রাখার কলাম যোগ করা
ALTER TABLE vouchers 
  ADD COLUMN rejection_reason TEXT NULL AFTER narration;

-- ৩. Bank Transactions টেবিলে রিজেকশনের কারণ লিখে রাখার কলাম যোগ করা
ALTER TABLE bank_transactions 
  ADD COLUMN rejection_reason TEXT NULL AFTER skip_reason;

