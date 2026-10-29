import xml.etree.ElementTree as ET
import uuid
from typing import Dict, Any, List, Tuple, Optional
import httpx
from utils.config import config
from helper.voucher_builder import VoucherBuilderService


class TallyClientService:
    def __init__(self):
        self.endpoint_url = config.TALLY_URL
        self.company = config.TALLY_COMPANY_NAME
        self.timeout = config.TALLY_TIMEOUT
        self.mock_mode = config.TALLY_SIMULATION_MODE

    def test_connection(self) -> Dict[str, Any]:
        """Test HTTP connection to Tally Prime."""
        if self.mock_mode:
            return {
                "success": True,
                "status": "connected_mock",
                "message": f"Connected to Tally Prime Simulation (Mock Mode Active) for company '{self.company}'",
                "endpoint": self.endpoint_url,
                "company": self.company,
                "is_mock": True
            }

        try:
            ping_xml = "<ENVELOPE><HEADER><TALLYREQUEST>Export Data</TALLYREQUEST></HEADER><BODY><EXPORTDATA><REQUESTDESC><STATICVARIABLES><SVCURRENTCOMPANY>" + self.company + "</SVCURRENTCOMPANY></STATICVARIABLES><REPORTNAME>List of Companies</REPORTNAME></REQUESTDESC></EXPORTDATA></BODY></ENVELOPE>"
            with httpx.Client(timeout=float(self.timeout)) as client:
                resp = client.post(
                    self.endpoint_url,
                    content=ping_xml,
                    headers={"Content-Type": "text/xml;charset=utf-8"}
                )
                if resp.status_code == 200:
                    return {
                        "success": True,
                        "status": "connected",
                        "message": f"Successfully connected to Tally Prime at {self.endpoint_url}",
                        "endpoint": self.endpoint_url,
                        "company": self.company,
                        "is_mock": False
                    }
                else:
                    return {
                        "success": False,
                        "status": "http_error",
                        "message": f"Tally Prime returned HTTP status {resp.status_code}",
                        "endpoint": self.endpoint_url,
                        "is_mock": False
                    }
        except Exception as e:
            return {
                "success": False,
                "status": "unreachable",
                "message": f"Cannot reach Tally Prime at {self.endpoint_url}: {str(e)}",
                "endpoint": self.endpoint_url,
                "is_mock": False
            }

    def sync_ledgers_from_tally(self) -> Tuple[List[Dict[str, str]], bool]:
        """
        Fetches all ledger masters from Tally Prime.
        Returns (list_of_ledgers, is_mock).
        """
        if self.mock_mode:
            mock_ledgers = [
                {"name": "HDFC Bank", "parent_group": "Bank Accounts"},
                {"name": "State Bank of India", "parent_group": "Bank Accounts"},
                {"name": "ABC Suppliers Ltd", "parent_group": "Sundry Creditors"},
                {"name": "Apex Technologies", "parent_group": "Sundry Creditors"},
                {"name": "Global Logistics Corp", "parent_group": "Sundry Creditors"},
                {"name": "Zentec Solutions Pvt Ltd", "parent_group": "Sundry Creditors"},
                {"name": "Acme Retail Customers", "parent_group": "Sundry Debtors"},
                {"name": "National Enterprises", "parent_group": "Sundry Debtors"},
                {"name": "Electricity Expenses", "parent_group": "Indirect Expenses"},
                {"name": "Office Rent", "parent_group": "Indirect Expenses"},
                {"name": "Telephone & Internet Charges", "parent_group": "Indirect Expenses"},
                {"name": "Printing & Stationery", "parent_group": "Indirect Expenses"},
                {"name": "Bank Charges", "parent_group": "Indirect Expenses"},
                {"name": "Professional Fees", "parent_group": "Indirect Expenses"},
                {"name": "Sales Account", "parent_group": "Sales Accounts"},
                {"name": "Purchase Account", "parent_group": "Purchase Accounts"}
            ]
            return mock_ledgers, True

        export_xml = VoucherBuilderService.build_export_ledgers_xml(self.company)
        try:
            with httpx.Client(timeout=float(self.timeout)) as client:
                resp = client.post(
                    self.endpoint_url,
                    content=export_xml,
                    headers={"Content-Type": "text/xml;charset=utf-8"}
                )
                if resp.status_code == 200:
                    ledgers = self._parse_ledgers_xml(resp.text)
                    return ledgers, False
        except Exception:
            pass

        return [], False

    def _parse_ledgers_xml(self, xml_text: str) -> List[Dict[str, str]]:
        ledgers = []
        try:
            root = ET.fromstring(xml_text)
            for ledger_node in root.findall(".//LEDGER"):
                name = ledger_node.get("NAME") or ""
                parent = ""
                parent_node = ledger_node.find("PARENT")
                if parent_node is not None and parent_node.text:
                    parent = parent_node.text.strip()
                if name:
                    ledgers.append({"name": name.strip(), "parent_group": parent or "Primary"})
        except Exception:
            pass
        return ledgers

    def submit_voucher(self, xml_payload: str) -> Dict[str, Any]:
        """
        Submits an accounting voucher XML payload to Tally Prime.
        """
        if self.mock_mode:
            mock_guid = f"SIM-{uuid.uuid4().hex[:12].upper()}"
            mock_response_xml = f"""<RESPONSE>
  <CREATED>1</CREATED>
  <ALTERED>0</ALTERED>
  <DELETED>0</DELETED>
  <LASTVCHID>{mock_guid}</LASTVCHID>
  <ERRORS>0</ERRORS>
</RESPONSE>"""
            return {
                "success": True,
                "is_mock": True,
                "http_status": 200,
                "guid": mock_guid,
                "raw_response": mock_response_xml,
                "message": "Voucher posted successfully in Simulation Mode"
            }

        try:
            with httpx.Client(timeout=float(self.timeout)) as client:
                resp = client.post(
                    self.endpoint_url,
                    content=xml_payload,
                    headers={"Content-Type": "text/xml;charset=utf-8"}
                )
                raw_text = resp.text
                parsed_res = self._parse_voucher_response(raw_text)
                parsed_res["http_status"] = resp.status_code
                parsed_res["raw_response"] = raw_text
                parsed_res["is_mock"] = False
                return parsed_res

        except httpx.TimeoutException:
            return {
                "success": False,
                "is_timeout": True,
                "is_mock": False,
                "message": "Connection timed out while waiting for Tally Prime response. Transaction flagged for reconciliation."
            }
        except Exception as e:
            return {
                "success": False,
                "is_timeout": False,
                "is_mock": False,
                "message": f"Failed to submit voucher to Tally Prime: {str(e)}"
            }

    def _parse_voucher_response(self, xml_text: str) -> Dict[str, Any]:
        try:
            root = ET.fromstring(xml_text)
            created_node = root.find(".//CREATED")
            errors_node = root.find(".//ERRORS")
            guid_node = root.find(".//LASTVCHID") or root.find(".//VCHKEY")
            lineerror_nodes = root.findall(".//LINEERROR")

            created_count = int(created_node.text) if created_node is not None and created_node.text else 0
            errors_count = int(errors_node.text) if errors_node is not None and errors_node.text else 0
            guid = guid_node.text if guid_node is not None and guid_node.text else None

            if lineerror_nodes:
                err_msgs = [node.text for node in lineerror_nodes if node.text]
                return {
                    "success": False,
                    "message": "Tally returned line errors: " + " | ".join(err_msgs),
                    "guid": None
                }

            if created_count > 0 and errors_count == 0:
                return {
                    "success": True,
                    "message": "Voucher imported successfully into Tally Prime.",
                    "guid": guid or str(uuid.uuid4())
                }
            else:
                return {
                    "success": False,
                    "message": f"Tally reported {errors_count} error(s) during import.",
                    "guid": None
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"Unable to parse Tally XML response: {str(e)}",
                "guid": None
            }

