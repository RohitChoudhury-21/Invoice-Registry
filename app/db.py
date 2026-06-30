import enum
import hashlib
import logging
from re import search
from rapidfuzz import fuzz
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List
from sqlalchemy import or_
from sqlalchemy import (String, Integer, DateTime, Date, Numeric, Enum as SAEnum, ForeignKey, create_engine, select, Index, func, 
text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session, relationship
from app.cleaning import normalize_vendor, parse_invoice_date, parse_amount, generate_content_hash


# ====================== Logging ======================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

class Base(DeclarativeBase):
    pass

class DocumentStatus(enum.Enum):
    PROCESSED = "processed"
    FAILED = "failed"

class ReviewStatus(enum.Enum):
    UNREVIEWED = "unreviewed"
    VERIFIED = "verified"
    MERGED = "merged"
    APPROVED = "approved"
    REJECTED = "rejected"

class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)   
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True, index=True)    
    status: Mapped[DocumentStatus] = mapped_column(SAEnum(DocumentStatus), nullable=False)
    failure_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    doc_type: Mapped[str] = mapped_column(String, nullable=False, default="pdf")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    duplicate_blocked_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    invoices: Mapped[List["Invoice"]] = relationship(
        "Invoice", secondary="invoice_documents", back_populates="documents"
    )

class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_number: Mapped[str] = mapped_column(String, nullable=False)
    vendor_name: Mapped[str] = mapped_column(String, nullable=False)
    vendor_normalized: Mapped[str] = mapped_column(String, nullable=False)
    invoice_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    invoice_date_raw: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    total_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    total_amount_raw: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True, index=True)
    field_warnings: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    review_status: Mapped[ReviewStatus] = mapped_column(SAEnum(ReviewStatus), nullable=False, default=ReviewStatus.UNREVIEWED)

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    merged_into_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("invoices.id"),
        nullable=True
    )

    merged_into: Mapped[Optional["Invoice"]] = relationship(
        "Invoice",
        remote_side="Invoice.id"
    )

    documents: Mapped[List["Document"]] = relationship(
        "Document",
        secondary="invoice_documents",
        back_populates="invoices"
    )

    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    line_items_verified: Mapped[Optional[bool]] = mapped_column(nullable=True, default=None)
    __table_args__ = (
        Index(
            "ix_invoices_vendor_invoice_number",
            "vendor_normalized",
            "invoice_number"
        ),
    )

class DuplicateStatus(enum.Enum):
    PENDING = "pending"
    MERGED = "merged"
    NOT_DUPLICATE = "not_duplicate"

class DuplicateCandidate(Base):
    __tablename__ = "duplicate_candidates"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice1_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    invoice2_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    score: Mapped[float] = mapped_column()
    match_type: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[DuplicateStatus] = mapped_column(SAEnum(DuplicateStatus), nullable=False,default=DuplicateStatus.PENDING)

class InvoiceDocument(Base):
    __tablename__ = "invoice_documents"

    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), primary_key=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

engine = create_engine("sqlite:///data/registry.db", echo=False, connect_args={"check_same_thread": False, "timeout": 15})

def init_db():
    Base.metadata.create_all(engine)
    init_fts_table(engine)
    setup_fts_triggers(engine)
    
    with engine.connect() as conn:
        result = conn.execute(text("SELECT count(*) FROM invoice_search")).scalar()
        if result == 0:
            logger.info("Syncing existing invoices into FTS5 index...")
            conn.execute(text("""
                INSERT INTO invoice_search(id, vendor_name, invoice_number)
                SELECT id, vendor_name, invoice_number FROM invoices;
            """))
            conn.commit()
            logger.info("✅ FTS5 index synced successfully")

    logger.info("✅ Database initialization complete")

def get_session():
    return Session(engine)

def save_document(
    session: Session,
    filename: str,
    size_bytes: Optional[int] = None,
    sha256: Optional[str] = None,
    status: DocumentStatus = DocumentStatus.PROCESSED,
    failure_reason: Optional[str] = None,
    doc_type: str = "pdf"
) -> Document:
    doc = Document(
        filename=filename,
        size_bytes=size_bytes,
        sha256=sha256,
        status=status,
        failure_reason=failure_reason,
        doc_type=doc_type
    )
    session.add(doc)
    session.commit()
    logger.info(f"Document saved | ID: {doc.id} | {filename} | {status.value}")
    return doc

def check_for_duplicates(session: Session, new_invoice: Invoice):
    """Detect re-issued invoices and fuzzy duplicate candidates."""
    conditions = []
    if new_invoice.invoice_date is not None:
        conditions.append(Invoice.invoice_date == new_invoice.invoice_date)
    if new_invoice.total_amount is not None:
        conditions.append(Invoice.total_amount == new_invoice.total_amount)
    if not conditions:
        return
    candidates = (
        session.execute(
            select(Invoice).where(
                or_(*conditions),
                Invoice.id != new_invoice.id,
                Invoice.deleted_at.is_(None)
            )
        )
        .scalars()
        .all()
    )
    for candidate in candidates:
        existing = session.query(DuplicateCandidate).filter(
            (
                (DuplicateCandidate.invoice1_id == new_invoice.id) &
                (DuplicateCandidate.invoice2_id == candidate.id)
            )
            |
            (
                (DuplicateCandidate.invoice1_id == candidate.id) &
                (DuplicateCandidate.invoice2_id == new_invoice.id)
            )
        ).first()
        if existing:
            continue  
        vendor_score = fuzz.ratio(
            candidate.vendor_normalized or "",
            new_invoice.vendor_normalized or "",
        )

        invoice_score = fuzz.ratio(
            candidate.invoice_number or "",
            new_invoice.invoice_number or "",
        )
        if (
            candidate.invoice_number == new_invoice.invoice_number
            and candidate.vendor_normalized == new_invoice.vendor_normalized
            and candidate.invoice_date == new_invoice.invoice_date
            and candidate.total_amount == new_invoice.total_amount
        ):
            session.add(
                DuplicateCandidate(
                    invoice1_id=new_invoice.id,
                    invoice2_id=candidate.id,
                    score=100,
                    match_type="reissue",
                )
            )
        elif vendor_score >= 90 and invoice_score >= 85:
            session.add(
                DuplicateCandidate(
                    invoice1_id=new_invoice.id,
                    invoice2_id=candidate.id,
                    score=(vendor_score + invoice_score) / 2,
                    match_type="fuzzy_match",
                )
            )
    session.commit()

def restore_invoice(session: Session, invoice_id: int):
    # Fetch the invoice, even if it is currently marked as deleted
    invoice = session.query(Invoice).filter(Invoice.id == invoice_id).first()
    
    if invoice and invoice.deleted_at is not None:
        invoice.deleted_at = None  # Clear the deletion timestamp
        session.commit()
        session.refresh(invoice)
        return True
    return False

def merge_invoices(
    session: Session,
    primary_invoice_id: int,
    duplicate_invoice_id: int,
):
    primary = get_invoice_by_id(
        session,
        primary_invoice_id,
        include_deleted=True,
    )

    duplicate = get_invoice_by_id(
        session,
        duplicate_invoice_id,
        include_deleted=True,
    )

    if not primary:
        raise ValueError("Primary invoice not found")

    if not duplicate:
        raise ValueError("Duplicate invoice not found")

    if primary.id == duplicate.id:
        raise ValueError("Cannot merge an invoice into itself")
    
    print(
        primary.id,
        duplicate.id,
        duplicate.merged_into_id
    )   
    
    if duplicate.merged_into_id is not None:
        raise ValueError("Invoice is already merged")
    
    if primary.merged_into_id is not None:
        raise ValueError(
            "Cannot merge into an invoice that is already merged"
    )
    for document in duplicate.documents:
        if document not in primary.documents:
            primary.documents.append(document)

    duplicate.merged_into_id = primary.id

    candidates = session.query(DuplicateCandidate).filter(
        (
            (DuplicateCandidate.invoice1_id == primary.id) &
            (DuplicateCandidate.invoice2_id == duplicate.id)
        )
        |
        (
            (DuplicateCandidate.invoice1_id == duplicate.id) &
            (DuplicateCandidate.invoice2_id == primary.id)
        )
    ).all()

    for candidate in candidates:
        candidate.status = "merged"

    session.commit()
    session.refresh(duplicate)

    return duplicate

def get_invoice_by_natural_key(
    session: Session,
    vendor_normalized: str,
    invoice_number: str
) -> Optional[Invoice]:
    return session.execute(
        select(Invoice).where(
            Invoice.vendor_normalized == vendor_normalized,
            Invoice.invoice_number == invoice_number,
        )
    ).scalar_one_or_none()

def verify_line_items(text: str, total_amount: Optional[Decimal]) -> tuple[bool, Optional[str]]:
    """
    Check if line items in the invoice text sum to the stated total.
    Returns (is_verified, warning_message).
    """
    if not total_amount or total_amount == 0:
        return None, None  # Can't verify without a total
    
    import re
    # Look for patterns like "$ 123.45" or "USD 456.78" or just "789.01"
    amounts = re.findall(r'[\$€£]?\s*(\d+[.,]\d{2})', text)
    
    if not amounts:
        return None, None  # No line items found
    
    try:
        # Convert found amounts to Decimal, handling both . and , as decimal separator
        line_items = []
        for amt in amounts:
            # Normalize: replace comma with period if needed
            normalized = amt.replace(',', '.')
            line_items.append(Decimal(normalized))
        
        line_sum = sum(line_items)
        
        # Check if sum is within 0.01 (one cent) of the stated total
        if abs(line_sum - total_amount) <= Decimal('0.01'):
            return True, None
        else:
            return False, f"Line items sum to {line_sum}, but total is {total_amount}"
    
    except Exception as e:
        return None, f"Could not verify line items: {str(e)}"

def get_or_create_invoice(
    session: Session,
    invoice_number: str,
    vendor_name: str,
    total_amount_raw: Optional[str] = None,
    currency: Optional[str] = None,
    invoice_date_raw: Optional[str] = None
) -> tuple[Invoice, bool]:
    warnings = []
    vendor_normalized = normalize_vendor(vendor_name)

    try:
        invoice_date = parse_invoice_date(invoice_date_raw)
    except Exception:
        invoice_date = None
        warnings.append(f"Could not parse invoice date: {invoice_date_raw}")

    try:
        total_amount, detected_currency = parse_amount(total_amount_raw)
        if not currency:
            currency = detected_currency
    except Exception:
        total_amount = None
        warnings.append(f"Could not parse total amount: {total_amount_raw}")
    
    content_hash = generate_content_hash(
        vendor_normalized,
        invoice_number,
        invoice_date,
        total_amount
    )

    existing_by_hash = session.execute(
        select(Invoice).where(Invoice.content_hash == content_hash)
    ).scalar_one_or_none()

    if existing_by_hash:
        logger.info(
            f"Content duplicate caught | Invoice ID: {existing_by_hash.id}"
        )
        return existing_by_hash, False

    existing = get_invoice_by_natural_key(session, vendor_normalized, invoice_number)
    if existing:
        logger.info(
            f"Duplicate invoice caught | ID: {existing.id} | {invoice_number}"
        )
        return existing, False

    invoice = Invoice(
        invoice_number=invoice_number,
        vendor_name=vendor_name,
        vendor_normalized=vendor_normalized,
        invoice_date=invoice_date,
        invoice_date_raw=invoice_date_raw,
        total_amount=total_amount,
        total_amount_raw=total_amount_raw,
        currency=currency,
        content_hash=content_hash,
        field_warnings="; ".join(warnings) if warnings else None,
    )

    invoice.line_items_verified = None

    session.add(invoice)
    invoice.content_hash = content_hash
    session.commit()

    check_for_duplicates(session, invoice)

    logger.info(
        f"Invoice created | ID: {invoice.id} | {invoice_number}"
    )

    return invoice, True
def get_stats(session: Session) -> dict:
    documents = session.scalar(select(func.count(Document.id))) or 0
    unique_invoices = session.scalar(select(func.count(Invoice.id))) or 0
    invoice_links = session.scalar(select(func.count()).select_from(InvoiceDocument)) or 0
    duplicate_files_blocked = session.scalar(
        select(func.coalesce(func.sum(Document.duplicate_blocked_count), 0))
    ) or 0

    duplicate_invoices_caught = max(invoice_links - unique_invoices, 0)

    return {
        "documents": documents,
        "unique_invoices": unique_invoices,
        "duplicate_files_blocked": duplicate_files_blocked,
        "duplicate_invoices_caught": duplicate_invoices_caught,
    }
  
def link_invoice_document(session: Session, invoice_id: int, document_id: int):
    existing = session.execute(
        select(InvoiceDocument).where(
            InvoiceDocument.invoice_id == invoice_id,
            InvoiceDocument.document_id == document_id,
        )
    ).scalar_one_or_none()

    if existing:
        return existing

    link = InvoiceDocument(invoice_id=invoice_id, document_id=document_id)
    session.add(link)
    session.commit()
    return link


def get_document_by_sha256(session: Session, sha256: str) -> Optional[Document]:
    return session.execute(
        select(Document).where(
            Document.sha256 == sha256)
    ).scalar_one_or_none()


def get_documents(session: Session, status: Optional[DocumentStatus] = None) -> List[Document]:
    query = select(Document)
    if status:
        query = query.where(Document.status == status)
    return session.execute(query).scalars().all()


def get_document_by_id(session: Session, doc_id: int) -> Optional[Document]:
    return session.execute(
        select(Document).where(Document.id == doc_id)
    ).scalar_one_or_none()

def get_invoices(
    session: Session,
    limit: int = 20,
    offset: int = 0,
    include_deleted: bool = False,
    search: Optional[str] = None,
    search_type: str = "fts",
    vendor: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    amount_min: Optional[Decimal] = None,
    amount_max: Optional[Decimal] = None,
    currency: Optional[str] = None,
    include_merged: bool = False,
):
    # 1. Base Queries
    query = select(Invoice)
    count_query = select(func.count(Invoice.id))

    filters = []
    if not include_deleted:
        filters.append(Invoice.deleted_at.is_(None))
    if not include_merged:
        filters.append(Invoice.merged_into_id.is_(None))
    if vendor:
        filters.append(Invoice.vendor_normalized == normalize_vendor(vendor))
    if date_from:
        filters.append(Invoice.invoice_date >= date_from)
    if date_to:
        filters.append(Invoice.invoice_date <= date_to)
    if amount_min is not None:
        filters.append(Invoice.total_amount >= amount_min)
    if amount_max is not None:
        filters.append(Invoice.total_amount <= amount_max)
    if currency:
        filters.append(Invoice.currency == currency.upper())
    
    for item in filters:
        query = query.where(item)
        count_query = count_query.where(item)
    
    if search:
        if search_type.lower() == "fts":
            ids = session.execute(
                text("""
                    SELECT id
                    FROM invoice_search
                    WHERE invoice_search MATCH :term
                """),
                {"term": search},
            ).scalars().all()

            if not ids:
                return [], 0

            query = query.where(Invoice.id.in_(ids))
            count_query = count_query.where(Invoice.id.in_(ids))

        else:

            pattern = f"%{search.strip()}%"

            like_filter = or_(
                Invoice.invoice_number.ilike(pattern),
                Invoice.vendor_name.ilike(pattern),
                Invoice.vendor_normalized.ilike(pattern),
            )

            query = query.where(like_filter)
            count_query = count_query.where(like_filter)
    total = session.scalar(count_query) or 0

    query = (
        query.order_by(Invoice.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    invoices = session.execute(query).scalars().all()

    return invoices, total

def get_invoice_by_id(
    session: Session,
    invoice_id: int,
    include_deleted: bool = False
) -> Optional[Invoice]:
    query = select(Invoice).where(Invoice.id == invoice_id)

    if not include_deleted:
        query = query.where(Invoice.deleted_at.is_(None))

    return session.execute(query).scalar_one_or_none()


def soft_delete_invoice(session: Session, invoice_id: int) -> Optional[Invoice]:
    invoice = get_invoice_by_id(session, invoice_id)

    if not invoice:
        return None

    invoice.deleted_at = datetime.utcnow()
    session.commit()
    return invoice

# Create the Virtual Table for FTS5
def init_fts_table(engine):
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS invoice_search 
            USING fts5(id UNINDEXED, vendor_name, invoice_number);
        """))
        conn.commit()

def setup_fts_triggers(engine):
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS after_invoice_insert AFTER INSERT ON invoices
            BEGIN
                INSERT INTO invoice_search(id, vendor_name, invoice_number)
                VALUES (new.id, new.vendor_name, new.invoice_number);
            END;
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS after_invoice_delete AFTER DELETE ON invoices
            BEGIN
                INSERT INTO invoice_search(invoice_search, id, vendor_name, invoice_number)
                VALUES('delete', old.id, old.vendor_name, old.invoice_number);
            END;
        """))
        conn.commit()

def optimize_fts(engine):
    with engine.connect() as conn:
        conn.execute(text("INSERT INTO invoice_search(invoice_search) VALUES('optimize');"))
        conn.commit()
    logger.info("✅ FTS5 index optimized")

if __name__ == "__main__":
    init_db()