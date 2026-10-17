from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers import auth, jobs, projects

app = FastAPI(title="ClippingVideos")
app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(projects.router)


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"ok": True}
