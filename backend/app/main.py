from fastapi import FastAPI

app = FastAPI(title="Etiquette Purchase Decision API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
