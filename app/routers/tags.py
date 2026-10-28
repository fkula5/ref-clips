"""Edytowalny słownik tagów (nazwy i aliasy używane przez parser notatek)."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Tag, decision_tags
from app.web import render

router = APIRouter()


@router.get("/tags")
def tags_page(request: Request, db: Session = Depends(get_db)):
    usage = dict(db.execute(
        select(decision_tags.c.tag_id, func.count()).group_by(decision_tags.c.tag_id)).all())
    tags = db.scalars(select(Tag).order_by(Tag.sort, Tag.name)).all()
    return render(request, "tags.html", tags=tags, usage=usage)


@router.post("/tags")
def create_tag(db: Session = Depends(get_db), name: str = Form(), aliases: str = Form("")):
    name = name.strip()
    if not name or db.scalar(select(Tag).where(func.lower(Tag.name) == name.lower())):
        raise HTTPException(422, "Pusta lub już istniejąca nazwa tagu")
    db.add(Tag(name=name, aliases=aliases.strip(), sort=1000))
    db.commit()
    return RedirectResponse("/tags", status_code=303)


@router.post("/tags/{tag_id}")
def update_tag(tag_id: int, db: Session = Depends(get_db), name: str = Form(),
               aliases: str = Form("")):
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(404)
    clash = db.scalar(select(Tag).where(func.lower(Tag.name) == name.strip().lower(), Tag.id != tag_id))
    if not name.strip() or clash:
        raise HTTPException(422, "Pusta lub już istniejąca nazwa tagu")
    tag.name, tag.aliases = name.strip(), aliases.strip()
    db.commit()
    return RedirectResponse("/tags", status_code=303)


@router.post("/tags/{tag_id}/delete")
def delete_tag(tag_id: int, db: Session = Depends(get_db)):
    tag = db.get(Tag, tag_id)
    if tag is not None:
        db.delete(tag)
        db.commit()
    return RedirectResponse("/tags", status_code=303)
