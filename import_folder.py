import os
import requests
import sys

# The URL where your API is running
API_URL = "http://127.0.0.1:8000/upload"

def import_invoices(folder_path):
    stats = {"processed": 0, "duplicate": 0, "failed": 0}
    
    # Get all PDF files
    files = [f for f in os.listdir(folder_path) if f.lower().endswith('.pdf')]
    print(f"Found {len(files)} files. Starting upload...")

    for filename in files:
        file_path = os.path.join(folder_path, filename)
        
        try:
            with open(file_path, 'rb') as f:
                response = requests.post(API_URL, files={'file': f})
            
            if response.status_code == 200:
                print(f"[OK] {filename}")
                stats["processed"] += 1
            elif response.status_code == 409:
                print(f"[DUPLICATE] {filename}")
                stats["duplicate"] += 1
            else:
                print(f"[FAILED] {filename} - {response.text}")
                stats["failed"] += 1
        except Exception as e:
            print(f"[ERROR] Could not upload {filename}: {e}")
            stats["failed"] += 1

    print("\n--- Import Summary ---")
    print(f"Processed: {stats['processed']}")
    print(f"Duplicates: {stats['duplicate']}")
    print(f"Failed: {stats['failed']}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python import_folder.py <folder_path>")
    else:
        import_invoices(sys.argv[1])