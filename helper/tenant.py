"""Multi-tenant context resolution helper.
Extracts company_id and active financial_year_id from headers/query, or falls back to defaults.
"""
from typing import Tuple, Optional
from flask import request
from sqlalchemy.orm import Session
from database.repositories import CompanyRepository
from model.models import Company, FinancialYear


def resolve_tenant_context(db: Session) -> Tuple[int, Optional[int]]:
    """Resolves (company_id, fy_id) from request headers/args, or database defaults.
    
    Header format:
      X-Company-Id: 1
      X-Financial-Year-Id: 1
    """
    comp_repo = CompanyRepository(db)
    
    # 1. Resolve company_id
    raw_comp_id = request.headers.get("X-Company-Id") or request.args.get("company_id")
    company_id: int
    if raw_comp_id:
        try:
            company_id = int(raw_comp_id)
        except ValueError:
            company_id = 1
    else:
        default_company = comp_repo.get_default()
        company_id = default_company.id if default_company else 1

    # 2. Resolve fy_id
    raw_fy_id = request.headers.get("X-Financial-Year-Id") or request.args.get("fy_id")
    fy_id: Optional[int] = None
    if raw_fy_id:
        try:
            fy_id = int(raw_fy_id)
        except ValueError:
            pass

    if not fy_id:
        current_fy = comp_repo.get_current_fy(company_id)
        if current_fy:
            fy_id = current_fy.id

    return company_id, fy_id

