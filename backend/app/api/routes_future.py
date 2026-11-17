"""Stubs for future phase endpoints.

These endpoints return 501 with a clear message indicating which phase they
belong to and why they are not yet implemented. The product never pretends
to have completed a phase it has not.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException


def _not_implemented(phase: int, description: str) -> dict:
    raise HTTPException(
        status_code=501,
        detail={
            "status": "not_implemented",
            "phase": phase,
            "description": description,
            "message": (
                f"This endpoint belongs to Phase {phase}. "
                f"{description}. It is not implemented in the current build."
            ),
        },
    )


router_evolve = APIRouter(prefix="/api/evolve", tags=["evolve"])


@router_evolve.post("/skills")
async def evolve_skills():
    return _not_implemented(4, "Skill evolution from failure trajectories")


router_skills = APIRouter(prefix="/api/skills", tags=["skills"])


@router_skills.post("/evaluate")
async def evaluate_skill():
    return _not_implemented(5, "Independent skill evaluation")


@router_skills.post("/promote")
async def promote_skill():
    return _not_implemented(5, "Skill version promotion with gate")
