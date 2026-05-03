import json
import logging

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


@router.get("", response_model=list[ClippingReportDetail])
def list_reports(
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    reports = session.exec(
        select(ClippingReport).order_by(ClippingReport.queued_at.desc()).limit(limit)
    ).all()

    results = []
    for report in reports:
        episode = session.get(PodcastEpisode, report.episode_id)
        if not episode:
            continue
        podcast = session.get(PodcastShow, episode.podcast_id)

        tr = None
        if report.transcription_report_json:
            tr = json.loads(report.transcription_report_json)

        ar = None
        if report.analysis_report_json:
            ar = json.loads(report.analysis_report_json)

        tr_duration = None
        if tr and tr.get("started_at") and tr.get("completed_at"):
            from datetime import datetime

            start = datetime.fromisoformat(tr["started_at"])
            end = datetime.fromisoformat(tr["completed_at"])
            tr_duration = (end - start).total_seconds()

        ar_duration = None
        if ar and ar.get("started_at") and ar.get("completed_at"):
            from datetime import datetime

            start = datetime.fromisoformat(ar["started_at"])
            end = datetime.fromisoformat(ar["completed_at"])
            ar_duration = (end - start).total_seconds()

        tr_model = None
        if report.transcription_model_id:
            m = session.get(AIModel, report.transcription_model_id)
            tr_model = str(m) if m else None

        ar_model = None
        if report.analysis_model_id:
            m = session.get(AIModel, report.analysis_model_id)
            ar_model = str(m) if m else None

        results.append(
            ClippingReportDetail(
                id=report.id,
                episode_id=report.episode_id,
                episode_title=episode.title,
                podcast_title=podcast.title if podcast else "Unknown",
                status=report.status.value,
                queued_at=report.queued_at,
                downloaded_at=report.downloaded_at,
                transcribed_at=report.transcribed_at,
                analysed_at=report.analysed_at,
                edited_at=report.edited_at,
                transcription_model=tr_model,
                analysis_model=ar_model,
                transcription_duration_s=tr_duration,
                transcription_input_tokens=tr.get("input_tokens") if tr else None,
                transcription_output_tokens=tr.get("output_tokens") if tr else None,
                transcription_cost=tr.get("cost_usd") if tr else None,
                transcription_segments=tr.get("segments_count") if tr else None,
                analysis_duration_s=ar_duration,
                analysis_input_tokens=ar.get("input_tokens") if ar else None,
                analysis_output_tokens=ar.get("output_tokens") if ar else None,
                analysis_cost=ar.get("cost_usd") if ar else None,
                adverts_found=ar.get("adverts_found") if ar else None,
                has_exceptions=report.exceptions_json != "[]",
            )
        )

    return results
