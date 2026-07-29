from fastapi import FastAPI

app = FastAPI(title="Pharma Document Change Analyzer")


@app.get("/health")
def health():
    return {"status": "ok"}
