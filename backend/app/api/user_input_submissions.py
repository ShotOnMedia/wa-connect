from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.campaign_models import Campaign
from app.core.database import get_db
from app.core.security import require_user
from app.flow_models import Flow, FlowNode
from app.models import User
from app.user_input_models import UserInputAnswer, UserInputSubmission

router = APIRouter(prefix="/user-input-submissions", tags=["user-input-submissions"])


def _require_manager(user: User) -> None:
    if user.role.value not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="Only admins and managers can inspect submissions")


def _answer_out(answer: UserInputAnswer) -> dict:
    return {
        "id": answer.id,
        "question_node_id": answer.question_node_id,
        "campaign_question_id": answer.campaign_question_id,
        "answer_key": answer.answer_key,
        "question_text": answer.question_text,
        "value": answer.value_text,
        "created_at": answer.created_at,
    }


def _submission_out(db: Session, row: UserInputSubmission, include_answers: bool = False) -> dict:
    flow = db.get(Flow, row.flow_id)
    campaign_node = db.get(FlowNode, row.campaign_node_id)
    reusable_campaign = db.get(Campaign, row.campaign_id) if row.campaign_id else None
    result = {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "flow_id": row.flow_id,
        "flow_name": flow.name if flow else None,
        "campaign_node_id": row.campaign_node_id,
        "campaign_id": row.campaign_id,
        "campaign_name": reusable_campaign.name if reusable_campaign else (campaign_node.title if campaign_node else None),
        "channel": row.channel,
        "conversation_id": row.conversation_id,
        "contact_id": row.contact_id,
        "status": row.status,
        "webhook_url": row.webhook_url,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
    }
    if include_answers:
        answers = db.scalars(select(UserInputAnswer).where(UserInputAnswer.submission_id == row.id).order_by(UserInputAnswer.id)).all()
        result["answers"] = [_answer_out(a) for a in answers]
        result["answer_values"] = {a.answer_key: a.value_text for a in answers}
        result["question_answers"] = [{"key":a.answer_key,"question":a.question_text,"answer":a.value_text} for a in answers]
    return result


@router.get("")
def list_submissions(
    flow_id: int | None = Query(default=None),
    channel: str | None = Query(default=None, pattern="^(whatsapp|telegram)$"),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    _require_manager(user)
    stmt = select(UserInputSubmission).order_by(UserInputSubmission.started_at.desc(), UserInputSubmission.id.desc())
    if flow_id is not None:
        stmt = stmt.where(UserInputSubmission.flow_id == flow_id)
    if channel:
        stmt = stmt.where(UserInputSubmission.channel == channel)
    if status:
        stmt = stmt.where(UserInputSubmission.status == status)
    rows = db.scalars(stmt.limit(limit)).all()
    return [_submission_out(db, row) for row in rows]


@router.get("/{submission_id}")
def get_submission(
    submission_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    _require_manager(user)
    row = db.get(UserInputSubmission, submission_id)
    if not row:
        raise HTTPException(status_code=404, detail="Submission not found")
    return _submission_out(db, row, include_answers=True)
