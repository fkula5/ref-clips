"""JSON endpoints for the Vue frontend; reuse existing sessions and match services."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import (
    accounts, auth, clip_list, config, feedback, groups, leagues, match_list, permissions, retention,
    scoresheets, security, self_assessments, services, share, sheets, training_sets,
)
from app.db import get_db
from app.loaders import get_clip, get_match
from app.models import CLIP_STATUSES, PERIODS, RATING_VERDICTS, VIDEO_STATUSES, Clip, Match, User
from app.pagination import parse_page
from app.routers.auth import THROTTLE_MESSAGE
from app.routers.describe import cut_problem, editor_data
from app.storage import storage
from app.textutil import format_clock
from app.timeutil import local
from app.web import mark_seen

public_router = APIRouter(prefix="/api/frontend", dependencies=auth.PUBLIC)
router = APIRouter(prefix="/api/frontend", dependencies=auth.PROTECTED)


def user_data(user: User) -> dict:
    return {"id": user.id, "name": user.name, "email": user.email,
            "roles": sorted(user.roles), "can_create_match": permissions.can_create_match(user),
            "can_access_admin": permissions.can_access_admin(user),
            "can_see_self_assessments": permissions.can_see_self_assessments(user)}


def match_data(match: Match, state: services.MatchState) -> dict:
    return {
        "id": match.id, "date": match.date.isoformat(), "teams": match.teams, "level": match.level,
        "officials": [{"function": o.function, "name": o.display_name, "user_id": o.user_id}
                      for o in match.officials],
        "state": {"code": state.code, "label": state.label, "detail": state.detail},
    }


def clip_summary(clip: Clip) -> dict:
    return {
        "id": clip.id, "time": format_clock(clip.time_sec),
        "category": clip.category_label, "description": clip.description,
        "described": clip.is_described, "status": CLIP_STATUSES.get(clip.status, clip.status),
        "status_key": clip.status,
    }


def options(choices) -> list[dict[str, str]]:
    return [{"value": str(value), "label": label} for value, label in choices]


@router.get("/clips")
def clips_index(request: Request, response: Response, db: Session = Depends(get_db),
                user: User = auth.require(permissions.can_view)):
    response.headers["Cache-Control"] = "no-store"
    filters = clip_list.parse_filters(request.query_params)
    clips, pager = clip_list.select_clip_page(db, filters)
    stats = clip_list.clip_stats(db, clips)
    return {
        "items": [{
            **clip_summary(clip), "match": {"id": clip.match_id, "title": clip.match.title},
            "official": clip.official_label, "period": services.period_label(clip.video.marks, clip.time_sec),
            "comments": stats[clip.id].comments,
            "ratings": sum(count for _, count in stats[clip.id].ratings),
            "shareable": share.offerable(user, clip), "exportable": share.has_file(clip),
        } for clip in clips],
        "page": pager.page, "pages": pager.pages, "total": pager.total,
        "share_days": config.SHARE_DAYS, "share_limit": config.SHARE_MAX_CLIPS,
        "can_export": config.ENABLE_V2_FEATURES,
        "options": {
            "match_id": options((match.id, match.title) for match in
                                db.scalars(select(Match).order_by(Match.date.desc(), Match.id.desc()))),
            "person": options([*services.people(db), (clip_list.TEAM, "Cały zespół")]),
            "category_id": options((c.id, c.name) for c in services.all_categories(db)),
            "period": options([*((period, period) for period in PERIODS), (clip_list.NO_PERIOD, "Nieustalona")]),
            "described": options([(clip_list.DESCRIBED_YES, "Opisane"), (clip_list.DESCRIBED_NO, "Nieopisane")]),
            "rating": options(clip_list.RATING_CHOICES),
            "group": options((group.id, group.name) for group in groups.all_groups(db)),
        },
    }


@router.get("/clips/{clip_id}")
def clip_detail(request: Request, response: Response, db: Session = Depends(get_db),
                clip: Clip = Depends(get_clip), user: User = auth.require(permissions.can_view)):
    response.headers["Cache-Control"] = "no-store"
    mark_seen(request, db, clip_id=clip.id)
    comments, older = feedback.comments_of(db, clip_id=clip.id)
    navigation = clip_list.parse_filters(request.query_params)
    previous, following = services.neighbours(clip_list.select_clips(db, navigation, match_id=clip.match_id), clip)
    video = clip.video
    playable = clip.status == "cut" and clip.clip_path and storage.exists(clip.clip_path)
    full_recording = (not video.purged_at and video.status == "ready" and video.proxy_path
                      and storage.exists(video.proxy_path))
    problem = cut_problem(clip)
    sharing = None
    if permissions.can_share_clip(user, clip):
        sharing = {
            "can_create": bool(playable),
            "days": config.SHARE_DAYS,
            "links": [{
                "id": link.id, "expiry": local(link.expires_at), "views": link.view_count,
                "can_revoke": permissions.can_revoke_share(user, link),
            } for link in share.active_links(db, clip.id)],
        }
    editor = editor_data(db, clip) if permissions.can_describe_clip(user, clip) else None
    start, end = services.clip_range(clip)
    return {
        **clip_summary(clip),
        "match": {"id": clip.match_id, "title": clip.match.title},
        "previous": {"id": previous.id, "time": format_clock(previous.time_sec)} if previous else None,
        "next": {"id": following.id, "time": format_clock(following.time_sec)} if following else None,
        "period": services.period_label(video.marks, clip.time_sec),
        "official": clip.official_label,
        "editor": editor,
        "sharing": sharing,
        "set_choices": [{
            "id": choice.id, "name": choice.name, "has_clip": choice.has_clip,
        } for choice in training_sets.choices_for(db, clip)] if playable and permissions.can_edit_set(user) else None,
        "cut_error": problem["message"] if problem else None,
        "can_recut": bool(problem and problem["can_recut"] and permissions.can_manage_clips(user, clip.match)),
        "can_delete": permissions.can_delete_clip(user, clip),
        "pending": clip.status in ("new", "queued"),
        "adjust": {"start": start, "end": end, "time": clip.time_sec, "video_id": video.id, "fps": video.fps or 25}
        if full_recording and permissions.can_manage_clips(user, clip.match) else None,
        "can_rate": permissions.can_rate(user),
        "verdicts": [{"value": key, "label": label} for key, label in RATING_VERDICTS.items()],
        "unavailable": clip.status == "cut" and not playable,
        "stream_url": f"/clips/{clip.id}/file?v={clip.clip_version}" if playable else None,
        "recording_url": f"/videos/{video.id}?t={clip.time_sec}" if full_recording else None,
        "ratings": [{
            "id": rating.id, "author": rating.coach.name, "date": local(rating.created_at),
            "verdict": RATING_VERDICTS[rating.verdict], "verdict_key": rating.verdict, "text": rating.comment,
            "mine": rating.coach_id == user.id,
            "can_edit": permissions.can_edit_rating(user, rating),
            "can_delete": permissions.can_delete_rating(user, rating),
        } for rating in feedback.ratings_of(db, clip)],
        "comments": [{
            "id": comment.id, "author": comment.author.name, "date": local(comment.created_at),
            "text": comment.body,
            "can_edit": permissions.can_edit_comment(user, comment),
            "can_delete": permissions.can_delete_comment(user, comment),
        } for comment in comments],
        "older_before": older,
    }

@public_router.get("/csrf")
def csrf():
    token = security.new_token()
    response = JSONResponse({"csrf_token": token}, headers={"Cache-Control": "no-store"})
    auth.set_anon_csrf_cookie(response, token)
    return response


@public_router.post("/login")
def login(request: Request, db: Session = Depends(get_db),
          email: str = Form(""), password: str = Form("")):
    try:
        user = accounts.authenticate(db, email, password, auth.client_ip(request))
    except accounts.LoginThrottled:
        raise HTTPException(429, THROTTLE_MESSAGE)
    except accounts.InvalidCredentials:
        raise HTTPException(401, "Nieprawidłowy e-mail lub hasło.")
    accounts.end_session(db, request.cookies.get(config.SESSION_COOKIE))
    token = accounts.create_session(db, user)
    session = accounts.get_session(db, token)
    response = JSONResponse({"user": user_data(user), "csrf_token": session.csrf_token},
                            headers={"Cache-Control": "no-store"})
    auth.set_session_cookie(response, token)
    return response


@router.get("/session")
def session(request: Request, response: Response, user: User = Depends(auth.current_user)):
    response.headers["Cache-Control"] = "no-store"
    return {"user": user_data(user), "csrf_token": request.state.session.csrf_token}


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    accounts.end_session(db, request.cookies.get(config.SESSION_COOKIE))
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    auth.clear_session_cookie(response)
    return response


@router.get("/matches")
def matches(request: Request, response: Response, db: Session = Depends(get_db),
            user: User = auth.require(permissions.can_view)):
    response.headers["Cache-Control"] = "no-store"
    filters = match_list.parse_filters(request.query_params)
    result = match_list.list_matches(db, filters, user.id)
    return {
        "items": [{**match_data(row.match, row.state),
                   "clips": row.clips, "undescribed": row.undescribed}
                  for row in result.rows],
        "total": result.total, "page": result.page, "pages": result.pages,
        "levels": leagues.filter_levels(db), "errors": filters.errors,
        "people": options(services.people(db)),
        "groups": options((group.id, group.name) for group in groups.all_groups(db)),
    }


@router.get("/matches/{match_id}")
def match_detail(request: Request, response: Response, page: str = "",
                 db: Session = Depends(get_db), match: Match = Depends(get_match),
                 user: User = auth.require(permissions.can_view)):
    response.headers["Cache-Control"] = "no-store"
    mark_seen(request, db, match_id=match.id)
    clips, pager = clip_list.select_clip_page(db, clip_list.ClipFilters(page=parse_page(page)), match_id=match.id)
    state = services.match_state(match.videos, services.transcode_queue(db))
    return {
        **match_data(match, state),
        "expiry": retention.expiry_note(match.videos),
        "can_edit": permissions.can_edit_match(user, match),
        "can_delete": permissions.can_delete_match(user, match),
        "can_upload": permissions.can_upload_to_match(user, match),
        "can_describe": permissions.can_manage_clips(user, match),
        "pending": (any(v.status in ("uploading", "queued", "processing") for v in match.videos)
                    or any(clip.status in ("new", "queued") for clip in clips)),
        "documents": {
            "can_start_sheet": permissions.can_create_sheet(user) and not any(s.coach_id == user.id for s in match.sheets),
            "can_start_assessment": permissions.can_fill_self_assessment(user, match) and not self_assessments.own_in(match, user),
            "sheets": [{"id": s.id, "author": s.coach.name, "published": s.is_published,
                        "can_edit": permissions.can_edit_sheet(user, s)} for s in sheets.visible_to(user, match)],
            "assessments": [{"id": s.id, "author": s.author.name, "published": s.is_submitted,
                             "can_edit": permissions.can_edit_self_assessment(user, s)}
                            for s in self_assessments.visible_to(user, match)],
            "protocol": {
                "can_manage": permissions.can_manage_scoresheet(user, match),
                "accept": scoresheets.ACCEPT, "max_files": config.SCORESHEET_MAX_FILES,
                "max_bytes": config.SCORESHEET_MAX_BYTES,
                "files": [{"id": file.id, "name": file.original_filename, "size": file.size_bytes,
                           "inline": scoresheets.KINDS[file.content_type].inline if file.content_type in scoresheets.KINDS else False}
                          for file in match.scoresheets],
            },
        },
        "upload": {
            "chunk_bytes": config.UPLOAD_CHUNK_BYTES, "max_bytes": config.UPLOAD_MAX_BYTES,
            "periods": PERIODS, "can_add_notes": permissions.can_manage_clips(user, match),
            "notes_max_chars": config.NOTES_MAX_CHARS,
        } if permissions.can_upload_to_match(user, match) else None,
        "videos": [{
            "id": video.id, "name": video.display_name,
            "status": VIDEO_STATUSES.get(video.status, video.status),
            "can_play": video.status == "ready" and not video.purged_at and bool(video.proxy_path),
            "purged": video.purged_at is not None,
            "can_edit": permissions.can_upload_to_match(user, match),
            "can_retry": video.status == "error" and bool(video.original_path)
                         and permissions.can_upload_to_match(user, match),
            "can_delete": permissions.can_delete_video(user, video),
            "problem": video.error,
        } for video in match.videos],
        "clips": {
            "items": [clip_summary(clip) for clip in clips],
            "page": pager.page, "pages": pager.pages, "total": pager.total,
        },
    }
