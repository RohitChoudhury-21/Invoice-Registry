import re
from decimal import Decimal, InvalidOperation
from dateutil.parser import parse as parse_date
import hashlib

def normalize_vendor(value: str) -> str:
    text = value.upper().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    words = text.split()
    endings = {"INC", "LLC", "LTD", "CORP", "CO"}
    while words and words[-1] in endings:
        words.pop()
    return " ".join(words)

def parse_invoice_date(value: str):
    return parse_date(value, fuzzy=True).date()

def parse_amount(value: str):
    text = value.strip()
    currency = None

    if "$" in text:
        currency = "USD"
    elif "€" in text:
        currency = "EUR"
    elif "£" in text:
        currency = "GBP"

    cleaned = re.sub(r"[^\d,.-]", "", text)

    if "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    elif "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")

    return Decimal(cleaned), currency


def generate_content_hash(
    vendor_normalized: str,
    invoice_number: str,
    invoice_date,
    total_amount,
) -> str:
    """
    Generate a stable hash from the important invoice fields.
    This catches re-saved copies even when the PDF bytes differ.
    """

    content = "|".join([
        (vendor_normalized or "").strip().upper(),
        (invoice_number or "").strip().upper(),
        str(invoice_date or ""),
        str(total_amount or ""),
    ])

    return hashlib.sha256(content.encode("utf-8")).hexdigest()