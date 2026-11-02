"""Oceny szkoleniowców (klip) i komentarze (klip i mecz).

Każda trasa zapisu przechodzi przez CSRF (router jest dołączany z `PROTECTED`) i `auth.require(...)`
z regułą z `permissions`. Ocena i komentarz muszą należeć do klipu/meczu z adresu (inaczej 404).
Odpowiedzi: HTMX dostaje fragment strony (bez przeładowania), zwykły formularz — przekierowanie 303
albo całą stronę z błędem (422) i zachowaną treścią, więc wszystko działa także bez JavaScriptu.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import clip_list, feedback, permissions
from app.auth import require
from app.db import get_db
from app.feedback import FeedbackError
from app.loaders import get_clip, get_match
from app.models import Clip, Comment, Match, Rating, User
from app.routers import clips as clips_router
from app.routers import matches as matches_router
from app.web import is_htmx, render

router = APIRouter()


# --- oceny ----------------------------------------------------------------------
def get_clip_rating(rating_id: int, clip: Clip = Depends(get_clip), db: Session = Depends(get_db)) -> Rating:
    """Ocena z adresu, o ile należy do klipu z adresu (inaczej 404)."""
    rating = db.get(Rating, rating_id)
    if rating is None or rating.clip_id != clip.id:
        raise HTTPException(404, "Nie ma takiej oceny")
    return rating


def _ratings_view(request: Request, db: Session, clip: Clip, *, status_code: int = 200,
                  error: str | None = None, error_for=None, draft: dict | None = None):
    """Karta ocen (HTMX) albo cała strona klipu (zwykły formularz z błędem)."""
    if is_htmx(request):
        return render(request, "_ratings.html", status_code=status_code, c=clip,
                      ratings=feedback.ratings_of(db, clip), rating_error=error,
                      rating_error_for=error_for, rating_draft=draft)
    if error is None:
        return RedirectResponse(f"/clips/{clip.id}#oceny", status_code=303)
    return clips_router.render_clip(
        request, db, clip, clip_list.parse_filters(request.query_params), status_code=status_code,
        rating_error=error, rating_error_for=error_for, rating_draft=draft)


def _save_rating(request: Request, db: Session, clip: Clip, verdict: str, comment: str,
                 action: Callable[[], object], error_for):
    try:
        action()
    except FeedbackError as exc:
        db.rollback()
        return _ratings_view(request, db, clip, status_code=exc.status_code, error=str(exc),
                             error_for=error_for, draft={"verdict": verdict, "comment": comment})
    db.commit()
    return _ratings_view(request, db, clip)


@router.post("/clips/{clip_id}/rating")
def save_rating(request: Request, db: Session = Depends(get_db), clip: Clip = Depends(get_clip),
                user: User = require(permissions.can_rate),
                verdict: str = Form(""), comment: str = Form("")):
    """Własna ocena szkoleniowca: pierwszy zapis tworzy ocenę, kolejne ją aktualizują."""
    return _save_rating(request, db, clip, verdict, comment,
                        lambda: feedback.save_own_rating(db, clip, user.id, verdict, comment), "own")


@router.post("/clips/{clip_id}/ratings/{rating_id}/edit")
def edit_rating(request: Request, db: Session = Depends(get_db), clip: Clip = Depends(get_clip),
                rating: Rating = Depends(get_clip_rating),
                user: User = require(permissions.can_edit_rating, get_clip_rating),
                verdict: str = Form(""), comment: str = Form("")):
    """Zmiana oceny przez autora albo administratora; autorem oceny (`coach_id`) zostaje szkoleniowiec."""
    return _save_rating(request, db, clip, verdict, comment,
                        lambda: feedback.edit_rating(rating, verdict, comment), rating.id)


@router.post("/clips/{clip_id}/ratings/{rating_id}/delete")
def delete_rating(request: Request, db: Session = Depends(get_db), clip: Clip = Depends(get_clip),
                  rating: Rating = Depends(get_clip_rating),
                  user: User = require(permissions.can_delete_rating, get_clip_rating)):
    db.delete(rating)
    db.commit()
    return _ratings_view(request, db, clip)


# --- komentarze (te same trasy dla klipu i meczu) --------------------------------
@dataclass(frozen=True)
class CommentScope:
    prefix: str        # "/clips" albo "/matches"
    id_name: str       # nazwa parametru ścieżki
    column: str        # pole Comment wskazujące rodzica
    loader: Callable   # zależność ładująca klip/mecz (404, gdy brak)

    def base(self, parent: Clip | Match) -> str:
        return f"{self.prefix}/{parent.id}"

    def comments(self, db: Session, parent) -> list[Comment]:
        return feedback.comments_of(db, **{self.column: parent.id})

    def page(self, request: Request, db: Session, parent, **extra):
        """Cała strona rodzica (zwykły formularz z błędem)."""
        if self.column == "clip_id":
            return clips_router.render_clip(
                request, db, parent, clip_list.parse_filters(request.query_params), **extra)
        return matches_router.render_match(request, db, parent, **extra)


CLIP_SCOPE = CommentScope("/clips", "clip_id", "clip_id", get_clip)
MATCH_SCOPE = CommentScope("/matches", "match_id", "match_id", get_match)


def _item(request: Request, scope: CommentScope, parent, comment: Comment, *,
          editing: bool = False, error: str | None = None, draft: str | None = None,
          status_code: int = 200):
    return render(request, "_comment_item.html", status_code=status_code, cm=comment,
                  cbase=scope.base(parent), editing=editing, edit_error=error, edit_draft=draft)


def _htmx_form_error(request: Request, scope: CommentScope, parent, error: str, draft: str):
    """Błąd dodawania przez HTMX: podmieniamy sam formularz (z błędem i wpisaną treścią), a nie listę."""
    response = render(request, "_comment_form.html", status_code=422, cbase=scope.base(parent),
                      comment_error=error, comment_draft=draft)
    response.headers["HX-Retarget"] = "#comment-form"
    response.headers["HX-Reswap"] = "outerHTML"
    return response


def register_comment_routes(scope: CommentScope) -> None:
    prefix, id_name = scope.prefix, scope.id_name

    def get_scoped_comment(comment_id: int, parent=Depends(scope.loader),
                           db: Session = Depends(get_db)) -> Comment:
        comment = db.get(Comment, comment_id)
        if comment is None or getattr(comment, scope.column) != parent.id:
            raise HTTPException(404, "Nie ma takiego komentarza")
        return comment

    def anchor(parent, comment: Comment | None = None) -> RedirectResponse:
        target = f"comment-{comment.id}" if comment is not None else "komentarze"
        return RedirectResponse(f"{scope.base(parent)}#{target}", status_code=303)

    @router.post(f"{prefix}/{{{id_name}}}/comments")
    def add_comment(request: Request, db: Session = Depends(get_db), parent=Depends(scope.loader),
                    user: User = require(permissions.can_comment), body: str = Form("")):
        try:
            comment = feedback.create_comment(db, user.id, body, **{scope.column: parent.id})
        except FeedbackError as exc:
            db.rollback()
            if is_htmx(request):
                return _htmx_form_error(request, scope, parent, str(exc), body)
            return scope.page(request, db, parent, status_code=exc.status_code,
                              comment_error=str(exc), comment_draft=body)
        db.commit()
        if is_htmx(request):  # nowy komentarz na koniec listy + wyczyszczony formularz (oob)
            return render(request, "_comment_added.html", cm=comment, cbase=scope.base(parent),
                          editing=False, edit_error=None, edit_draft=None)
        return anchor(parent, comment)

    @router.get(f"{prefix}/{{{id_name}}}/comments/{{comment_id}}")
    def show_comment(request: Request, parent=Depends(scope.loader),
                     comment: Comment = Depends(get_scoped_comment),
                     user: User = require(permissions.can_view)):
        """Komentarz w widoku zwykłym (przycisk Anuluj przy edycji)."""
        if is_htmx(request):
            return _item(request, scope, parent, comment)
        return anchor(parent, comment)

    @router.get(f"{prefix}/{{{id_name}}}/comments/{{comment_id}}/edit")
    def edit_comment_form(request: Request, parent=Depends(scope.loader),
                          comment: Comment = Depends(get_scoped_comment),
                          user: User = require(permissions.can_edit_comment, get_scoped_comment)):
        if is_htmx(request):
            return _item(request, scope, parent, comment, editing=True, draft=comment.body)
        return render(request, "comment_edit.html", cm=comment, cbase=scope.base(parent),
                      parent_url=scope.base(parent), edit_error=None, edit_draft=comment.body)

    @router.post(f"{prefix}/{{{id_name}}}/comments/{{comment_id}}/edit")
    def edit_comment(request: Request, db: Session = Depends(get_db), parent=Depends(scope.loader),
                     comment: Comment = Depends(get_scoped_comment),
                     user: User = require(permissions.can_edit_comment, get_scoped_comment),
                     body: str = Form("")):
        try:
            feedback.edit_comment(comment, body)
        except FeedbackError as exc:
            db.rollback()
            if is_htmx(request):
                return _item(request, scope, parent, comment, editing=True, error=str(exc),
                             draft=body, status_code=exc.status_code)
            return render(request, "comment_edit.html", status_code=exc.status_code, cm=comment,
                          cbase=scope.base(parent), parent_url=scope.base(parent),
                          edit_error=str(exc), edit_draft=body)
        db.commit()
        if is_htmx(request):
            return _item(request, scope, parent, comment)
        return anchor(parent, comment)

    @router.post(f"{prefix}/{{{id_name}}}/comments/{{comment_id}}/delete")
    def delete_comment(request: Request, db: Session = Depends(get_db), parent=Depends(scope.loader),
                       comment: Comment = Depends(get_scoped_comment),
                       user: User = require(permissions.can_delete_comment, get_scoped_comment)):
        db.delete(comment)
        db.commit()
        if is_htmx(request):  # element znika (outerHTML -> pusta odpowiedź); komunikat „Brak komentarzy” przez oob
            return render(request, "_comment_removed.html",
                          empty=not scope.comments(db, parent))
        return anchor(parent)


register_comment_routes(CLIP_SCOPE)
register_comment_routes(MATCH_SCOPE)
