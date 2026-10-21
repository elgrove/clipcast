"""Small, batched reads for episode lists and status polling."""

from sqlalchemy.orm import aliased, defer
from sqlmodel import Session, select

from app.models import ClippingReport


def latest_reports(session: Session, episode_ids: list[str]) -> dict[str, ClippingReport]:
    if not episode_ids:
        return {}
    newest = aliased(ClippingReport)
    newest_id = (
        select(newest.id)
        .where(newest.episode_id == ClippingReport.episode_id)
        .order_by(newest.queued_at.desc(), newest.id.desc())
        .limit(1)
        .correlate(ClippingReport)
        .scalar_subquery()
    )
    reports = session.exec(
        select(ClippingReport)
        .where(ClippingReport.episode_id.in_(episode_ids), ClippingReport.id == newest_id)
        .options(
            defer(ClippingReport.logs),
            defer(ClippingReport.transcription_report_json),
            defer(ClippingReport.analysis_report_json),
            defer(ClippingReport.refinement_report_json),
        )
    ).all()
    return {report.episode_id: report for report in reports}
