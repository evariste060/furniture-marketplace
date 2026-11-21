"""Invoice schemas (module 16). Invoices are downloaded as PDFs; this is the JSON answer of the
administrator's recovery action only."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class InvoiceIssueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_id: uuid.UUID
    invoice_number: str = Field(description="INV-YYYY-NNNNNN (§7 Q19)")
    issued_at: datetime
    total: int = Field(description="Whole RWF, VAT-inclusive")
    vat_amount: int = Field(description="The 18% VAT contained in the total (ADR-007)")
    issued: bool = Field(description="True when this request issued it; false when it existed")
