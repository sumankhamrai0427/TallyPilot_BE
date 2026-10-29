from datetime import date
from decimal import Decimal
from typing import Dict, Any


class VoucherBuilderService:
    @staticmethod
    def build_tally_voucher_xml(
        company_name: str,
        voucher_type: str,
        voucher_date: date,
        reference_number: str,
        narration: str,
        amount: Decimal,
        primary_ledger: str,
        contra_ledger: str
    ) -> str:
        """
        Builds standard compliant Tally XML for voucher importation.
        Date format: YYYYMMDD
        """
        tally_date = voucher_date.strftime("%Y%m%d")
        v_type = voucher_type.capitalize()
        clean_narration = (narration or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        clean_primary = primary_ledger.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        clean_contra = contra_ledger.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        clean_company = company_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        clean_ref = (reference_number or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        if v_type == "Payment":
            primary_is_deemed_positive = "Yes"
            primary_amt = f"-{amount:.2f}"
            contra_is_deemed_positive = "No"
            contra_amt = f"{amount:.2f}"
        elif v_type == "Receipt":
            primary_is_deemed_positive = "No"
            primary_amt = f"{amount:.2f}"
            contra_is_deemed_positive = "Yes"
            contra_amt = f"-{amount:.2f}"
        elif v_type == "Contra":
            primary_is_deemed_positive = "Yes"
            primary_amt = f"-{amount:.2f}"
            contra_is_deemed_positive = "No"
            contra_amt = f"{amount:.2f}"
        else:
            primary_is_deemed_positive = "Yes"
            primary_amt = f"-{amount:.2f}"
            contra_is_deemed_positive = "No"
            contra_amt = f"{amount:.2f}"

        xml_payload = f"""<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>Vouchers</REPORTNAME>
        <STATICVARIABLES>
          <SVCURRENTCOMPANY>{clean_company}</SVCURRENTCOMPANY>
        </STATICVARIABLES>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="{v_type}" ACTION="Create" OBJVIEW="Accounting Voucher View">
            <DATE>{tally_date}</DATE>
            <EFFECTIVEDATE>{tally_date}</EFFECTIVEDATE>
            <VOUCHERTYPENAME>{v_type}</VOUCHERTYPENAME>
            <REFERENCE>{clean_ref}</REFERENCE>
            <NARRATION>{clean_narration}</NARRATION>
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{clean_primary}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>{primary_is_deemed_positive}</ISDEEMEDPOSITIVE>
              <AMOUNT>{primary_amt}</AMOUNT>
            </ALLLEDGERENTRIES.LIST>
            <ALLLEDGERENTRIES.LIST>
              <LEDGERNAME>{clean_contra}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>{contra_is_deemed_positive}</ISDEEMEDPOSITIVE>
              <AMOUNT>{contra_amt}</AMOUNT>
            </ALLLEDGERENTRIES.LIST>
          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>"""
        return xml_payload.strip()

    @staticmethod
    def build_export_ledgers_xml(company_name: str) -> str:
        clean_company = company_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f"""<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Export Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <EXPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>List of Accounts</REPORTNAME>
        <STATICVARIABLES>
          <SVCURRENTCOMPANY>{clean_company}</SVCURRENTCOMPANY>
          <ACCOUNTTYPE>All Ledgers</ACCOUNTTYPE>
        </STATICVARIABLES>
      </REQUESTDESC>
    </EXPORTDATA>
  </BODY>
</ENVELOPE>""".strip()

