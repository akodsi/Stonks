"""
Screener API routes — run preset/custom screens, manage saved screens.
"""
from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from api.sanitize import clean
from screener.engine import (
    PRESETS,
    run_screen,
    save_screen,
    load_screen,
    list_screens,
    delete_screen,
)

router = APIRouter(prefix="/screener", tags=["screener"])


class Criterion(BaseModel):
    field: str
    operator: str
    value: float


class CustomScreenRequest(BaseModel):
    criteria: List[Criterion]


class SaveScreenRequest(BaseModel):
    name: str
    criteria: List[Criterion]


@router.get("/presets")
def get_presets():
    """Return all preset screen definitions."""
    return clean(PRESETS)


@router.get("/run")
def run_preset(preset: str):
    """Run a preset screen by name."""
    preset = preset.lower()
    if preset not in PRESETS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown preset '{preset}'. Available: {', '.join(PRESETS.keys())}",
        )
    try:
        results = run_screen(PRESETS[preset])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"preset": preset, "criteria": PRESETS[preset], "count": len(results), "results": results}


@router.post("/run")
def run_custom(body: CustomScreenRequest):
    """Run a custom screen with user-defined criteria."""
    criteria = [c.dict() for c in body.criteria]
    if not criteria:
        raise HTTPException(status_code=400, detail="At least one criterion is required.")
    try:
        results = run_screen(criteria)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"criteria": criteria, "count": len(results), "results": results}


@router.get("/screens")
def get_saved_screens():
    """List all saved custom screens."""
    return clean(list_screens())


@router.post("/screens")
def create_saved_screen(body: SaveScreenRequest):
    """Save a custom screen."""
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Screen name is required.")
    criteria = [c.dict() for c in body.criteria]
    if not criteria:
        raise HTTPException(status_code=400, detail="At least one criterion is required.")
    save_screen(body.name.strip(), criteria)
    return {"saved": body.name.strip()}


@router.delete("/screens/{name}")
def remove_saved_screen(name: str):
    """Delete a saved custom screen."""
    if not delete_screen(name):
        raise HTTPException(status_code=404, detail=f"Screen '{name}' not found.")
    return {"deleted": name}
