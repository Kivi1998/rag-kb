from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import model as nli_model


@asynccontextmanager
async def lifespan(_: FastAPI):
    nli_model.ensure_loaded()
    yield


app = FastAPI(title="RAG NLI Gateway", version="1.0.0", lifespan=lifespan)


class NliRequest(BaseModel):
    premise: str
    hypothesis: str


class NliResponse(BaseModel):
    label: str
    entailment_prob: float
    neutral_prob: float
    contradiction_prob: float


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "UP" if nli_model.is_loaded() else "LOADING"}


@app.post("/nli", response_model=NliResponse)
def nli(request: NliRequest) -> NliResponse:
    if not request.premise.strip() or not request.hypothesis.strip():
        raise HTTPException(status_code=422, detail="premise 和 hypothesis 均不能为空")
    result = nli_model.predict(request.premise, request.hypothesis)
    return NliResponse(**result)
