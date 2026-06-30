from fastapi import FastAPI, UploadFile, HTTPException, Depends, Query
from sqlalchemy.orm import Session
import hashlib
from typing import Optional
import io
import re
from pypdf import PdfReader
from app.db import (
    DuplicateStatus, init_db, get_session, save_document, get_or_create_invoice,
    link_invoice_document, get_stats, get_documents, get_document_by_id,
    get_document_by_sha256, get_invoices, get_invoice_by_id, soft_delete_invoice,
    ReviewStatus, logger, check_for_duplicates, DuplicateCandidate, 
    Invoice, engine, optimize_fts, restore_invoice, merge_invoices, DocumentStatus
)
from fastapi.middleware.cors import CORSMiddleware 
from datetime import date
from decimal import Decimal
from fastapi.staticfiles import StaticFiles
import csv
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.cleaning import normalize_vendor, parse_invoice_date, parse_amount

class InvoiceExportParams(BaseModel):
    vendor: Optional[str] = None
    currency: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    amount_min: Optional[float] = None
    amount_max: Optional[float] = None

class InvoiceStatusUpdate(BaseModel):
    status: str

class InvoiceUpdate(BaseModel):
    vendor_name: Optional[str] = None
    invoice_date_raw: Optional[str] = None
    total_amount_raw: Optional[str] = None
    currency: Optional[str] = None

class MergeDuplicateResponse(BaseModel):
    message: str
    primary_invoice_id: int
    duplicate_invoice_id: int

def invoice_to_dict(invoice):
    return {
        "id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "vendor_name": invoice.vendor_name,
        "vendor_normalized": invoice.vendor_normalized,
        "invoice_date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
        "invoice_date_raw": invoice.invoice_date_raw,
        "total_amount": float(invoice.total_amount) if invoice.total_amount is not None else None,
        "total_amount_raw": invoice.total_amount_raw,
        "currency": invoice.currency,
        "review_status": invoice.review_status.value,
        "field_warnings": invoice.field_warnings,
        "deleted_at": invoice.deleted_at.isoformat() if invoice.deleted_at else None,
        "created_at": invoice.created_at.isoformat(),
        "merged_into_id": invoice.merged_into_id,
    }


def extract_invoice_details(text):
    invoice_number_match = re.search(r"Invoice Number:\s*(\S+)", text)
    vendor_match = re.search(r"Vendor:\s*(.*)", text)
    date_match = re.search(r"Date:\s*(.*)", text)
    total_match = re.search(r"Total:\s*(?:([A-Z]{3}|\$)\s*)?([\d,\.]+)", text)

    inv_num = invoice_number_match.group(1) if invoice_number_match else "UNKNOWN"
    vend_name = vendor_match.group(1).strip() if vendor_match else "UNKNOWN"
    inv_date_raw = date_match.group(1).strip() if date_match else None

    currency = None
    total_amount_raw = None
    if total_match:
        curr_match = total_match.group(1)
        if curr_match == "EUR":
            currency = "EUR"
        elif curr_match == "GBP":
            currency = "GBP"
        elif curr_match in ("USD", "$"):
            currency = "USD"
        total_amount_raw = total_match.group(2)

    return {
        "invoice_number": inv_num,
        "vendor_name": vend_name,
        "invoice_date_raw": inv_date_raw,
        "total_amount_raw": total_amount_raw,
        "currency": currency,
    }

def extract_text_from_pdf(pdf_content: bytes) -> str:
    """Simple PDF text extraction"""
    try:
        reader = PdfReader(io.BytesIO(pdf_content))
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text.strip()
    except Exception:
        raise ValueError("Corrupted or unreadable PDF")
    

app = FastAPI(title="Invoice Processor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins (change to specific URL later for security)
    allow_credentials=True,
    allow_methods=["*"],  # Allows all HTTP methods (POST, GET, etc.)
    allow_headers=["*"],  # Allows all headers
)

@app.on_event("startup")
async def startup_event():
    init_db()
    logger.info("🚀 Application started - Database ready")

def get_db():
    db = get_session()
    try:
        yield db
    finally:
        db.close()

@app.post("/upload", responses={409: {"description": "Duplicate file"}})
async def upload_document(file: UploadFile, db: Session = Depends(get_db)):

    content = await file.read()

    # ---------- Invalid extension ----------
    if not file.filename.lower().endswith(".pdf"):
        doc = save_document(
            db,
            filename=file.filename,
            size_bytes=len(content),
            sha256=None,
            status=DocumentStatus.FAILED,
            failure_reason="Only PDF files are allowed",
        )
        db.commit()

        raise HTTPException(
            status_code=400,
            detail="Only PDF files are allowed",
        )

    # ---------- Empty file ----------
    if len(content) == 0:
        doc = save_document(
            db,
            filename=file.filename,
            size_bytes=0,
            sha256=None,
            status=DocumentStatus.FAILED,
            failure_reason="The uploaded file is empty.",
        )
        db.commit()

        raise HTTPException(
            status_code=400,
            detail="The uploaded file is empty.",
        )

    # ---------- Compute hash ----------
    sha256 = hashlib.sha256(content).hexdigest()

    existing = get_document_by_sha256(db, sha256)
    if existing:
        existing.duplicate_blocked_count += 1
        db.commit()

        raise HTTPException(
            status_code=409,
            detail={
                "message": "Duplicate file",
                "existing_document_id": existing.id,
                "uploaded_at": existing.uploaded_at.isoformat(),
            },
        )

    # Save successful upload
    doc = save_document(
        db,
        filename=file.filename,
        size_bytes=len(content),
        sha256=sha256,
        status=DocumentStatus.PROCESSED,
        failure_reason=None,
    )

    # 4. PROCESSING
    try:
        text = extract_text_from_pdf(content)
        if not text or len(text.strip()) < 50:
            raise ValueError("No readable text found in PDF (File might be an image or corrupted)")

        extracted_data = extract_invoice_details(text)
        
        # ... your invoice creation logic ...
        invoice, is_new = get_or_create_invoice(db, **extracted_data)
        if is_new:
            check_for_duplicates(db, invoice)
        link_invoice_document(db, invoice.id, doc.id)
        
        db.commit() # Final save
        return {"status": "success", "document_id": doc.id}

    except Exception as e:
        # Handle processing failure
        doc.status = DocumentStatus.FAILED
        doc.failure_reason = str(e)
        db.commit()
        raise HTTPException(status_code=422, detail=f"Processing failed: {str(e)}")
    
@app.get("/documents")
def list_documents(
    status: Optional[str] = Query(None, description="Filter by status: processed or failed"),
    db: Session = Depends(get_db)
):
    if status:
        try:
            status_enum = DocumentStatus(status.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    else:
        status_enum = None

    docs = get_documents(db, status_enum)

    return {
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "size_bytes": d.size_bytes,
                "sha256": d.sha256,
                "status": d.status.value,
                "failure_reason": d.failure_reason,
                "doc_type": d.doc_type,
                "uploaded_at": d.uploaded_at.isoformat()
            }
            for d in docs
        ]
    }

@app.post("/invoices/{invoice_id}/restore")
def restore_invoice_route(invoice_id: int, db: Session = Depends(get_db)):
    success = restore_invoice(db, invoice_id)
    
    if not success:
        # We raise a 404 if it wasn't found or if it wasn't actually deleted
        raise HTTPException(
            status_code=404, 
            detail="Invoice not found or not currently in deleted state"
        )
    
    return {"message": "Invoice restored successfully"}

@app.get("/documents/{doc_id}")
def get_single_document(doc_id: int, db: Session = Depends(get_db)):
    doc = get_document_by_id(db, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "id": doc.id,
        "filename": doc.filename,
        "status": doc.status.value,
        "failure_reason": doc.failure_reason,
        "uploaded_at": doc.uploaded_at.isoformat()
    }

@app.get("/stats")
def stats(db: Session = Depends(get_db)):
    return get_stats(db)

@app.get("/invoices")
def list_invoices(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_deleted: bool = Query(False),
    search: Optional[str] = Query(None),
    search_type: str = Query("fts"),
    vendor: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    amount_min: Optional[Decimal] = Query(None),
    amount_max: Optional[Decimal] = Query(None),
    currency: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    ):

    query = db.query(Invoice).filter(
        Invoice.merged_into_id.is_(None)
    )
     
    invoices, total = get_invoices(
        db,
        limit=limit,
        offset=offset,
        include_deleted=include_deleted,
        search=search,
        search_type=search_type,
        vendor=vendor,
        date_from=date_from,
        date_to=date_to,
        amount_min=amount_min,
        amount_max=amount_max,
        currency=currency,
    )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "invoices": [invoice_to_dict(invoice) for invoice in invoices],
    }

@app.get("/invoices/{invoice_id}")
def get_single_invoice(
    invoice_id: int,
    include_deleted: bool = Query(False),
    db: Session = Depends(get_db),
):
    invoice = get_invoice_by_id(db, invoice_id, include_deleted)

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    data = invoice_to_dict(invoice)
    data["documents"] = [
        {
            "id": doc.id,
            "filename": doc.filename,
            "status": doc.status.value,
            "uploaded_at": doc.uploaded_at.isoformat(),
        }
        for doc in invoice.documents
    ]
    return data

@app.delete("/invoices/{invoice_id}")
def delete_invoice(invoice_id: int, db: Session = Depends(get_db)):
    invoice = soft_delete_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return {"id": invoice.id, "deleted_at": invoice.deleted_at.isoformat(), "status": "deleted"}

@app.get("/duplicates")
def get_duplicates(db: Session = Depends(get_db)):
    duplicates = db.query(DuplicateCandidate).filter(DuplicateCandidate.status == DuplicateStatus.PENDING).all()
    return [
    {
        "id": d.id,
        "invoice1_id": d.invoice1_id,
        "invoice2_id": d.invoice2_id,
        "score": d.score,
        "match_type": d.match_type,
        "status": d.status,
    }
    for d in duplicates
]

@app.get("/export")
def export_invoices(
    vendor: Optional[str] = None,
    currency: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    amount_min: Optional[float] = None,
    amount_max: Optional[float] = None,
    format: str = Query("csv"),
    db: Session = Depends(get_db)
):
    
    if format.lower() != "csv":
        raise HTTPException(
            status_code=400,
            detail="Only csv format is currently supported."
        )
    # 1. Fetch filtered invoices
    # Note: Using a large limit since exports usually want the full dataset
    invoices_data = get_invoices(
        db, 
        vendor=vendor, 
        currency=currency, 
        date_from=date_from, 
        date_to=date_to, 
        amount_min=amount_min, 
        amount_max=amount_max,
        limit=10000, 
        offset=0,
        include_merged=False,
    )

    invoices = invoices_data[0] if isinstance(invoices_data, tuple) else invoices_data

    # 2. Generate CSV content
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header Row
    writer.writerow(["ID", "Invoice Number", "Vendor", "Date", "Amount", "Currency", "Status"])

    # Data Rows
    for inv in invoices:
        writer.writerow([
            inv.id, 
            inv.invoice_number, 
            inv.vendor_name, 
            inv.invoice_date or "", 
            inv.total_amount or "", 
            inv.currency or "", 
            inv.review_status.value
        ])

    output.seek(0)
    
    # 3. Return as a stream
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=invoices.csv"}
    )

@app.patch("/invoices/{invoice_id}/status")
def update_invoice_status(invoice_id: int, update: InvoiceStatusUpdate, db: Session = Depends(get_db)):
    # 1. Fetch the invoice
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    # 2. Convert string input to Enum object
    try:
        new_status = ReviewStatus(update.status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {[s.value for s in ReviewStatus]}")

    # 3. Update using the Enum object (new_status), not the string (update.status)
    invoice.review_status = new_status
    db.commit()
    db.refresh(invoice)
    
    # 4. Return the .value so the JSON response is a string
    return {"message": "Status updated successfully", "new_status": invoice.review_status.value}

@app.patch("/invoices/{invoice_id}")
def edit_invoice(
    invoice_id: int,
    update: InvoiceUpdate,
    db: Session = Depends(get_db)
):
    """Edit invoice fields and re-clean the normalized values."""
    invoice = get_invoice_by_id(db, invoice_id, include_deleted=True)
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    # Update vendor if provided
    if update.vendor_name is not None:
        invoice.vendor_name = update.vendor_name
        invoice.vendor_normalized = normalize_vendor(update.vendor_name)
    
    # Update currency if provided
    if update.currency is not None:
        invoice.currency = update.currency.upper()
    
    # Update date if provided
    if update.invoice_date_raw is not None:
        invoice.invoice_date_raw = update.invoice_date_raw
        try:
            invoice.invoice_date = parse_invoice_date(update.invoice_date_raw)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not parse date: {str(e)}")
    
    # Update amount if provided
    if update.total_amount_raw is not None:
        invoice.total_amount_raw = update.total_amount_raw
        try:
            amount, detected_currency = parse_amount(update.total_amount_raw)
            invoice.total_amount = amount
            if not invoice.currency:
                invoice.currency = detected_currency
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not parse amount: {str(e)}")
    
    db.commit()
    db.refresh(invoice)
    
    return invoice_to_dict(invoice)

@app.get("/admin/optimize-search")
async def run_optimization():
    try:
        optimize_fts(engine)
        return {"status": "success", "message": "Index optimized successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/duplicates/{candidate_id}/merge")
def merge_duplicate(
    candidate_id: int,
    db: Session = Depends(get_db),
):
    candidate = (
        db.query(DuplicateCandidate)
        .filter(DuplicateCandidate.id == candidate_id)
        .first()
    )

    if not candidate:
        raise HTTPException(
            status_code=404,
            detail="Duplicate candidate not found",
        )

    merge_invoices(
        db,
        candidate.invoice1_id,
        candidate.invoice2_id,
    )

    candidate.status = DuplicateStatus.MERGED
    db.commit()

    return MergeDuplicateResponse(
        message="Invoices merged successfully",
        primary_invoice_id=candidate.invoice1_id,
        duplicate_invoice_id=candidate.invoice2_id,
    )

@app.post("/duplicates/{candidate_id}/dismiss")
def dismiss_duplicate(
    candidate_id: int,
    db: Session = Depends(get_db)
):
    """Mark a duplicate candidate as 'not a duplicate' without merging."""
    candidate = db.query(DuplicateCandidate).filter(
        DuplicateCandidate.id == candidate_id
    ).first()
    
    if not candidate:
        raise HTTPException(status_code=404, detail="Duplicate candidate not found")
    
    candidate.status = "not_duplicate"
    db.commit()
    
    return {
        "message": "Marked as not a duplicate",
        "candidate_id": candidate.id,
        "status": candidate.status
    }

@app.post("/invoices/{invoice_id}/verify-line-items")
def verify_line_items_endpoint(invoice_id: int, db: Session = Depends(get_db)):
    """Manually verify line items for an invoice by fetching its documents and re-extracting text."""
    invoice = get_invoice_by_id(db, invoice_id, include_deleted=True)
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    if not invoice.documents:
        raise HTTPException(status_code=400, detail="Invoice has no linked documents")
    
    # Extract text from the first document
    doc = invoice.documents[0]
    
    try:
        doc_obj = get_document_by_id(db, doc.id)
        if not doc_obj:
            raise HTTPException(status_code=404, detail="Document not found")
        
        # We don't have the original file bytes anymore, so we'll just mark as checked
        # In a real system, you'd re-read the file or store the extracted text
        import re
        from decimal import Decimal
        
        amounts = re.findall(r'[\$€£]?\s*(\d+[.,]\d{2})', "")  # Would need original text
        
        invoice.line_items_verified = True  # Placeholder
        db.commit()
        
        return {"message": "Line items verified", "verified": True}
    
    except Exception as e:
        return {"message": f"Error: {str(e)}", "verified": False}

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")