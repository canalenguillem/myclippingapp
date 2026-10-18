"""Ayudas para los gráficos del editor."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.auth.deps import current_user
from app.db.models import User
from app.services import graphics_interpret

router = APIRouter(prefix="/api/graphics", tags=["graphics"])


class InterpretIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=300)


@router.post("/interpret")
def interpret(body: InterpretIn, user: User = Depends(current_user)):
    """Traduce una frase libre a entrada, efecto y estilo. Nada de lo que devuelve sale de la lista de piezas conocidas."""
    return graphics_interpret.interpret(body.text)
