import logging

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.models import BugReportCreate, BugReportResult
from app.services.linear import LinearError, create_bug_report

logger = logging.getLogger("clipcast")
router = APIRouter(prefix="/api/bug-reports", tags=["bug-reports"])


def _build_description(report: BugReportCreate) -> str:
    parts = [report.description.strip()] if report.description.strip() else []
    if report.page_url:
        parts.append(f"\n\n---\n**Page:** {report.page_url}")
    return "\n".join(parts) or "_No description provided._"


@router.get("/enabled")
def bug_reports_enabled() -> dict:
    return {"enabled": bool(settings.linear_api_key and settings.linear_team_id)}


@router.post("", response_model=BugReportResult)
def submit_bug_report(report: BugReportCreate):
    try:
        issue = create_bug_report(report.title.strip(), _build_description(report))
    except LinearError as exc:
        logger.warning("Bug report not filed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return BugReportResult(identifier=issue["identifier"], url=issue["url"])
