import time
import requests
import json

BASE_URL = "http://127.0.0.1:8000"

def benchmark_search(search_term, search_type, iterations=5):
    """Benchmark a search query."""
    times = []
    
    for _ in range(iterations):
        start = time.time()
        response = requests.get(
            f"{BASE_URL}/invoices",
            params={
                "search": search_term,
                "search_type": search_type,
                "limit": 100
            }
        )
        end = time.time()
        
        if response.status_code == 200:
            times.append(end - start)
    
    avg_time = sum(times) / len(times)
    return avg_time

# Test searches
search_terms = [
    "Acme",
    "Tech Solutions",
    "INV-1234",
    "Global"
]

print("=" * 60)
print("FTS5 vs LIKE Benchmark (10,000 invoices)")
print("=" * 60)

for term in search_terms:
    print(f"\nSearch term: '{term}'")
    
    # FTS5
    fts_time = benchmark_search(term, "fts", iterations=5)
    print(f"  FTS5 (5 runs avg): {fts_time*1000:.2f}ms")
    
    # LIKE
    like_time = benchmark_search(term, "like", iterations=5)
    print(f"  LIKE (5 runs avg): {like_time*1000:.2f}ms")
    
    # Ratio
    ratio = like_time / fts_time if fts_time > 0 else 0
    print(f"  Speedup: {ratio:.1f}x faster with FTS5")

print("\n" + "=" * 60)
print("Benchmark complete!")
print("=" * 60)