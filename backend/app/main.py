from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers import assets, auth, clips, graphics, jobs, media, projects, templates, transcript

app = FastAPI(title="ClippingVideos")
app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(projects.router)
app.include_router(clips.router)
app.include_router(transcript.router)
app.include_router(templates.router)
app.include_router(assets.router)
app.include_router(graphics.router)
app.include_router(media.router)


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"ok": True}
