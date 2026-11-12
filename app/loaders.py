from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Clip, Comment, Match, MatchScoresheet, PeriodMark, ShareLink, TrainingSet, Video


def get_match(match_id: int, db: Session = Depends(get_db)) -> Match:
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(404, "Nie ma takiego meczu")
    return match


def get_video(video_id: int, db: Session = Depends(get_db)) -> Video:
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(404, "Nie ma takiego nagrania")
    return video


def get_clip(clip_id: int, db: Session = Depends(get_db)) -> Clip:
    clip = db.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(404, "Nie ma takiego klipu")
    return clip


def get_mark(mark_id: int, db: Session = Depends(get_db)) -> PeriodMark:
    mark = db.get(PeriodMark, mark_id)
    if mark is None:
        raise HTTPException(404, "Nie ma takiego znacznika")
    return mark


def get_comment(comment_id: int, db: Session = Depends(get_db)) -> Comment:
    comment = db.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(404, "Nie ma takiego komentarza")
    return comment


def get_share_link(link_id: int, db: Session = Depends(get_db)) -> ShareLink:
    link = db.get(ShareLink, link_id)
    if link is None:
        raise HTTPException(404, "Nie ma takiego linku")
    return link


def get_training_set(set_id: int, db: Session = Depends(get_db)) -> TrainingSet:
    training_set = db.get(TrainingSet, set_id)
    if training_set is None:
        raise HTTPException(404, "Nie ma takiego zestawu")
    return training_set


def get_scoresheet(match_id: int, scoresheet_id: int, db: Session = Depends(get_db)) -> MatchScoresheet:
    """A file addressed under another match's URL does not exist."""
    scoresheet = db.get(MatchScoresheet, scoresheet_id)
    if scoresheet is None or scoresheet.match_id != match_id:
        raise HTTPException(404, "Nie ma takiego pliku protokołu")
    return scoresheet
