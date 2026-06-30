import requests
import random
import time
from datetime import datetime, timedelta
import io
from reportlab.pdfgen import canvas

API_URL = "http://127.0.0.1:8000/upload"
COUNT = 10000

def generate_fake_pdf(invoice_num, vendor, amount, date_str):
    buffer = io.BytesIO()

    pdf = canvas.Canvas(buffer)

    pdf.drawString(100, 800, "INVOICE")
    pdf.drawString(100, 780, f"Invoice Number: {invoice_num}")
    pdf.drawString(100, 760, f"Vendor: {vendor}")
    pdf.drawString(100, 740, f"Date: {date_str}")
    pdf.drawString(100, 720, f"Total: ${amount:.2f}")

    pdf.drawString(100, 700, f"Line Item 1: Service ${amount*0.6:.2f}")
    pdf.drawString(100, 680, f"Line Item 2: Tax ${amount*0.4:.2f}")

    pdf.save()

    buffer.seek(0)
    return buffer.read()

def generate_and_post():
    print(f"Generating and uploading {COUNT} fake invoices...")
    
    vendors = [
        "Acme Corp", "Tech Solutions Ltd", "Global Industries", 
        "NextGen Systems", "Cloud Services Inc", "Data Analytics Co",
        "Software House", "Digital Transformations", "Quantum Networks",
        "FutureTech Solutions"
    ]
    
    start_date = datetime(2020, 1, 1)
    
    for i in range(COUNT):
        vendor = random.choice(vendors)
        amount = round(random.uniform(100, 5000), 2)
        days_offset = random.randint(0, 2000)
        date = start_date + timedelta(days=days_offset)
        date_str = date.strftime("%Y-%m-%d")
        invoice_num = f"INV-{random.randint(1000, 9999)}"
        
        pdf_bytes = generate_fake_pdf(invoice_num, vendor, amount, date_str)
        
        files = {"file": (f"fake_{i}.pdf", pdf_bytes, "application/pdf",)}

        try:
            response = requests.post(API_URL, files=files, timeout=10)

            if i < 10:   # print the first 10 responses
                print(i, response.status_code, response.text)

        except Exception as e:
            print(i, e)
        time.sleep(0.05)

    print("Generation complete!")

if __name__ == "__main__":
    generate_and_post()