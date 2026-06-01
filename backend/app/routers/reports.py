import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    AIModel,
    ClippingReport,
    ClippingReportDetail,
    PodcastEpisode,
    PodcastShow,
)

logger = logging.getLogger("clipcast")
router = APIRouter(prefix="/api/reports", tags=["reports"])


def _report_duration(rep: dict | None) -> float | None:
    if not rep or not rep.get("started_at") or not rep.get("completed_at"):
        return None
    start = datetime.fromisoformat(rep["started_at"])
    end = datetime.fromisoformat(rep["completed_at"])
    return (end - start).total_seconds()


def report_to_detail(report: ClippingReport, session: Session) -> ClippingReportDetail | None:
    episode = session.get(PodcastEpisode, report.episode_id)
    if not episode:
        return None
    podcast = session.get(PodcastShow, episode.podcast_id)

    tr = json.loads(report.transcription_report_json) if report.transcription_report_json else None
    ar = json.loads(report.analysis_report_json) if report.analysis_report_json else None
    rr = json.loads(report.refinement_report_json) if report.refinement_report_json else None

    def _model_name(model_id: str | None) -> str | None:
        if not model_id:
            return None
        m = session.get(AIModel, model_id)
        return str(m) if m else None

    return ClippingReportDetail(
        id=report.id,
        episode_id=report.episode_id,
        episode_title=episode.title,
        podcast_title=podcast.title if podcast else "Unknown",
        status=report.status.value,
        queued_at=report.queued_at,
        downloaded_at=report.downloaded_at,
        transcribed_at=report.transcribed_at,
        analysed_at=report.analysed_at,
        refined_at=report.refined_at,
        edited_at=report.edited_at,
        transcription_model=_model_name(report.transcription_model_id),
        analysis_model=_model_name(report.analysis_model_id),
        refinement_model=_model_name(report.refinement_model_id),
        transcription_duration_s=_report_duration(tr),
        transcription_input_tokens=tr.get("input_tokens") if tr else None,
        transcription_output_tokens=tr.get("output_tokens") if tr else None,
        transcription_cost=tr.get("cost_usd") if tr else None,
        transcription_segments=tr.get("segments_count") if tr else None,
        analysis_duration_s=_report_duration(ar),
        analysis_input_tokens=ar.get("input_tokens") if ar else None,
        analysis_output_tokens=ar.get("output_tokens") if ar else None,
        analysis_cost=ar.get("cost_usd") if ar else None,
        ad_breaks_found=ar.get("ad_breaks_found") if ar else None,
        refinement_duration_s=_report_duration(rr),
        refinement_input_tokens=rr.get("input_tokens") if rr else None,
        refinement_output_tokens=rr.get("output_tokens") if rr else None,
        refinement_cost=rr.get("cost_usd") if rr else None,
        boundaries_refined=rr.get("boundaries_refined") if rr else None,
        boundaries_snapped=rr.get("boundaries_snapped") if rr else None,
        boundaries_kept=rr.get("boundaries_kept") if rr else None,
        has_exceptions=report.exceptions_json != "[]",
    )


@router.get("", response_model=list[ClippingReportDetail])
def list_reports(
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    reports = session.exec(
        select(ClippingReport).order_by(ClippingReport.queued_at.desc()).limit(limit)
    ).all()

    return [d for r in reports if (d := report_to_detail(r, session))]
