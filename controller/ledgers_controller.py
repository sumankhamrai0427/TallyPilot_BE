"""Ledgers & Chart of Accounts controller.
Handles multi-tenant Chart of Accounts, ledgers, groups, and parties.
"""
from flask import jsonify, request
from decimal import Decimal
from database.dbConnection import SessionLocal
from database.repositories import LedgerRepository, CompanyRepository
from helper.tenant import resolve_tenant_context
from model.models import LedgerAccount, AccountGroup, Party
from utils.logger import logger


def list_companies():
    """Lists all active companies with their full credentials and status."""
    db = SessionLocal()
    try:
        repo = CompanyRepository(db)
        companies = repo.list_all(is_active=False)  # list all to manage active/inactive
        return jsonify([
            {
                "id": c.id,
                "company_code": c.code,
                "company_name": c.name,
                "currency": c.currency,
                "pan": c.pan,
                "gstin": c.gstin,
                "financial_year_start_month": c.financial_year_start_month,
                "tally_company_name": c.tally_company_name or c.name,
                "tally_url": c.tally_url or "http://localhost:9000",
                "default_bank_ledger": c.default_bank_ledger or "HDFC Bank",
                "tally_simulation_mode": bool(c.tally_simulation_mode),
                "is_active": bool(c.is_active)
            }
            for c in companies
        ]), 200
    except Exception as e:
        logger.error(f"Error listing companies: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()


def get_company(company_id: int):
    """Retrieves a single company profile with credentials."""
    db = SessionLocal()
    try:
        repo = CompanyRepository(db)
        c = repo.get_by_id(company_id)
        if not c:
            return jsonify({"detail": "Company not found"}), 404
        return jsonify({
            "id": c.id,
            "company_code": c.code,
            "company_name": c.name,
            "currency": c.currency,
            "pan": c.pan,
            "gstin": c.gstin,
            "financial_year_start_month": c.financial_year_start_month,
            "tally_company_name": c.tally_company_name or c.name,
            "tally_url": c.tally_url or "http://localhost:9000",
            "default_bank_ledger": c.default_bank_ledger or "HDFC Bank",
            "tally_simulation_mode": bool(c.tally_simulation_mode),
            "is_active": bool(c.is_active)
        }), 200
    finally:
        db.close()


def create_company():
    """Creates a new company master with credentials and initial FY."""
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        return jsonify({"detail": "Company name is required"}), 400

    db = SessionLocal()
    try:
        repo = CompanyRepository(db)
        company = repo.create_company(data)
        
        # Initialize default FY (e.g. FY 2026-27) if not already existing
        from datetime import date
        current_year = date.today().year
        fy_code = f"FY {current_year}-{str(current_year + 1)[-2:]}"
        repo.create_financial_year(company.id, {
            "fy_code": fy_code,
            "start_date": f"{current_year}-04-01",
            "end_date": f"{current_year + 1}-03-31",
            "is_current": True,
            "is_closed": False
        })
        
        return jsonify({
            "message": "Company created successfully",
            "company": {
                "id": company.id,
                "company_code": company.code,
                "company_name": company.name,
                "tally_url": company.tally_url,
                "tally_company_name": company.tally_company_name
            }
        }), 201
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating company: {e}")
        return jsonify({"detail": str(e)}), 400
    finally:
        db.close()


def update_company(company_id: int):
    """Updates company details and Tally Prime credentials."""
    data = request.get_json(silent=True) or {}
    db = SessionLocal()
    try:
        repo = CompanyRepository(db)
        comp = repo.update_company(company_id, data)
        if not comp:
            return jsonify({"detail": "Company not found"}), 404
        return jsonify({
            "message": "Company credentials updated successfully",
            "company": {
                "id": comp.id,
                "company_code": comp.code,
                "company_name": comp.name,
                "currency": comp.currency,
                "pan": comp.pan,
                "gstin": comp.gstin,
                "financial_year_start_month": comp.financial_year_start_month,
                "tally_company_name": comp.tally_company_name,
                "tally_url": comp.tally_url,
                "default_bank_ledger": comp.default_bank_ledger,
                "tally_simulation_mode": bool(comp.tally_simulation_mode),
                "is_active": bool(comp.is_active)
            }
        }), 200
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating company: {e}")
        return jsonify({"detail": str(e)}), 400
    finally:
        db.close()


def test_company_tally(company_id: int):
    """Tests live connection to Tally Prime for a specific company."""
    import time
    import requests
    db = SessionLocal()
    try:
        repo = CompanyRepository(db)
        comp = repo.get_by_id(company_id)
        if not comp:
            return jsonify({"detail": "Company not found"}), 404

        tally_url = comp.tally_url or "http://localhost:9000"
        tally_company = comp.tally_company_name or comp.name
        
        start_t = time.time()
        try:
            # Ping Tally XML endpoint
            test_xml = (
                '<ENVELOPE>'
                '<HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Data</TYPE><ID>Company</ID></HEADER>'
                '<BODY><DESC><STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT></STATICVARIABLES></DESC></BODY>'
                '</ENVELOPE>'
            )
            resp = requests.post(tally_url, data=test_xml, headers={"Content-Type": "text/xml"}, timeout=3)
            elapsed_ms = round((time.time() - start_t) * 1000, 1)
            if resp.status_code == 200:
                return jsonify({
                    "connected": True,
                    "status": "connected",
                    "tally_url": tally_url,
                    "company_name": tally_company,
                    "response_time_ms": elapsed_ms,
                    "message": f"Successfully connected to Tally Prime at {tally_url} ({elapsed_ms}ms)"
                }), 200
            else:
                return jsonify({
                    "connected": False,
                    "status": "error",
                    "tally_url": tally_url,
                    "message": f"Tally responded with HTTP status {resp.status_code}"
                }), 200
        except requests.exceptions.RequestException as rex:
            return jsonify({
                "connected": False,
                "status": "offline",
                "tally_url": tally_url,
                "message": f"Could not connect to Tally Prime at {tally_url}. Please ensure Tally Prime is running and ODBC/XML port is open. ({str(rex)})"
            }), 200
    finally:
        db.close()


def list_financial_years():
    """Lists financial years for the active company."""
    db = SessionLocal()
    try:
        company_id, _ = resolve_tenant_context(db)
        repo = CompanyRepository(db)
        fys = repo.list_financial_years(company_id)
        return jsonify([
            {
                "id": f.id,
                "company_id": f.company_id,
                "fy_code": f.fy_code,
                "start_date": f.start_date.isoformat(),
                "end_date": f.end_date.isoformat(),
                "is_current": bool(f.is_current),
                "is_closed": bool(f.is_closed)
            }
            for f in fys
        ]), 200
    except Exception as e:
        logger.error(f"Error listing financial years: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()


def create_financial_year():
    """Creates a new financial year for the active company."""
    data = request.get_json(silent=True) or {}
    if not data.get("fy_code") or not data.get("start_date") or not data.get("end_date"):
        return jsonify({"detail": "fy_code, start_date, and end_date are required"}), 400

    db = SessionLocal()
    try:
        company_id, _ = resolve_tenant_context(db)
        repo = CompanyRepository(db)
        fy = repo.create_financial_year(company_id, data)
        return jsonify({
            "message": "Financial Year created successfully",
            "financial_year": {
                "id": fy.id,
                "company_id": fy.company_id,
                "fy_code": fy.fy_code,
                "start_date": fy.start_date.isoformat(),
                "end_date": fy.end_date.isoformat(),
                "is_current": bool(fy.is_current),
                "is_closed": bool(fy.is_closed)
            }
        }), 201
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating financial year: {e}")
        return jsonify({"detail": str(e)}), 400
    finally:
        db.close()


def set_current_financial_year(fy_id: int):
    """Marks a specific financial year as active/current for the company."""
    db = SessionLocal()
    try:
        company_id, _ = resolve_tenant_context(db)
        repo = CompanyRepository(db)
        fy = repo.set_current_financial_year(company_id, fy_id)
        if not fy:
            return jsonify({"detail": "Financial year not found"}), 404
        return jsonify({
            "message": f"Financial Year {fy.fy_code} is now set as Current",
            "fy_id": fy.id,
            "fy_code": fy.fy_code
        }), 200
    except Exception as e:
        db.rollback()
        logger.error(f"Error setting current FY: {e}")
        return jsonify({"detail": str(e)}), 400
    finally:
        db.close()


def toggle_financial_year_lock(fy_id: int):
    """Toggles or sets the closed/locked state of a financial year (Closing Control)."""
    data = request.get_json(silent=True) or {}
    is_closed = data.get("is_closed")
    db = SessionLocal()
    try:
        repo = CompanyRepository(db)
        fy = repo.toggle_financial_year_lock(fy_id, is_closed)
        if not fy:
            return jsonify({"detail": "Financial year not found"}), 404
        status_text = "Locked/Closed" if fy.is_closed else "Open for Posting"
        return jsonify({
            "message": f"Financial Year {fy.fy_code} is now {status_text}",
            "fy_id": fy.id,
            "is_closed": bool(fy.is_closed)
        }), 200
    except Exception as e:
        db.rollback()
        logger.error(f"Error toggling FY lock: {e}")
        return jsonify({"detail": str(e)}), 400
    finally:
        db.close()


def get_chart_of_accounts():
    """Returns the hierarchical Chart of Accounts tree."""
    db = SessionLocal()
    try:
        company_id, _ = resolve_tenant_context(db)
        repo = LedgerRepository(db)
        tree = repo.get_chart_of_accounts_tree(company_id)
        return jsonify(tree), 200
    except Exception as e:
        logger.error(f"Error getting Chart of Accounts: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()


def list_ledgers():
    """Returns a flat list of ledger accounts for the active company."""
    db = SessionLocal()
    try:
        company_id, _ = resolve_tenant_context(db)
        repo = LedgerRepository(db)
        ledgers = repo.list_by_company(company_id, is_active=True)
        return jsonify([
            {
                "id": l.id,
                "company_id": l.company_id,
                "group_id": l.group_id,
                "group_name": l.group.name if l.group else None,
                "name": l.name,
                "code": l.code,
                "opening_balance": float(l.opening_balance),
                "current_balance": float(l.current_balance),
                "is_bank_account": (l.group.name in ("Bank Accounts", "Bank OD A/c") if l.group else False) or ("Bank" in l.name),
                "is_active": l.is_active
            }
            for l in ledgers
        ]), 200
    except Exception as e:
        logger.error(f"Error listing ledgers: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()


def list_parties():
    """Returns all active parties for the active company."""
    db = SessionLocal()
    try:
        company_id, _ = resolve_tenant_context(db)
        repo = LedgerRepository(db)
        party_type = request.args.get("party_type")
        parties = repo.list_parties(company_id, party_type=party_type)
        return jsonify([
            {
                "id": p.id,
                "company_id": p.company_id,
                "ledger_id": p.ledger_id,
                "party_name": p.ledger.name if p.ledger else f"Party #{p.id}",
                "party_type": p.party_type,
                "gstin": p.gstin,
                "pan": p.pan,
                "credit_limit": float(p.credit_limit),
                "is_active": p.is_active
            }
            for p in parties
        ]), 200
    except Exception as e:
        logger.error(f"Error listing parties: {e}")
        return jsonify({"detail": str(e)}), 500
    finally:
        db.close()
