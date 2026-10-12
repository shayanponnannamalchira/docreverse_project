"""Generate the Office-format sample files (docx / xlsx / pptx) into sample_docs/."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.office_fixtures import make_docx, make_pptx, make_xlsx  # noqa: E402

out = ROOT / "sample_docs"
out.mkdir(exist_ok=True)

make_docx(out / "SEC-220_Access_Request_Procedure.docx", [
    ("title", "Access Request Procedure"),
    ("p", "Owner: Security Manager"),
    ("h1", "Procedure"),
    ("p", "When an Employee needs access to a production system, the following steps apply."),
    ("ol", "Employee opens an Access Request in ServiceNow and names the system."),
    ("ol", "Line Manager approves the Access Request within 2 business days."),
    ("ol", "Security Team reviews the request and grants access in Okta."),
    ("ol", "IT Service Desk confirms access to the Employee by email."),
    ("comment", "Should the Security Manager also approve requests for finance systems?"),
])
make_xlsx(out / "pricing_model.xlsx", "Pricing",
          [["Item", "Units", "Unit Price", "Revenue"], ["Basic plan", 100, 20, 0], ["Pro plan", 40, 50, 0], ["Total", 0, 0, 0]],
          {"D2": "B2*C2", "D3": "B3*C3", "D4": "SUM(D2:D3)", "B4": "SUM(B2:B3)"})
make_pptx(out / "Quarterly_Ops_Review.pptx", [
    ("Operations Review", ["The Operations Team owns the Vendor Onboarding Process.", "Procurement Manager reports to the Chief Financial Officer."]),
    ("Risks", ["SAP is a single point of failure for vendor activation.", "Approval within 7 business days is too slow."]),
])
print("sample office files written to", out)
