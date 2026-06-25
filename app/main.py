from fastapi import FastAPI

app = FastAPI(title="Invoice Registry")

@app.get("/health")
def health():
    return {"status": "ok"}