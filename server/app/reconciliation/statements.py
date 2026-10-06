"""Monthly PSI account summaries, separate from statutory accounting."""

from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.pagination import paginate
from app.core.security import CurrentUser, get_current_user, has_permission
from app.reconciliation.records import AccountType

router = APIRouter(prefix="/api/reconciliation", tags=["reconciliation"])
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
SOURCE_FILTERS = {
    "customer": "('sales_shipment', 'sales_shipment_reversal')",
    "supplier": "('purchase_receipt', 'purchase_receipt_reversal', "
                "'purchase_return', 'purchase_return_reversal')",
    "processor": "('outsourcing_receipt', 'outsourcing_receipt_reversal')",
}


class BusinessLineRead(BaseModel):
    id: UUID
    source_type: str
    source_id: UUID
    source_line_id: UUID
    amount_delta: Decimal
    posted_at: datetime


class CashLineRead(BaseModel):
    id: UUID
    document_no: str
    document_date: date
    amount: Decimal
    source_type: str | None
    source_id: UUID | None


class StatementRead(BaseModel):
    month: str
    account_type: AccountType
    party_id: UUID
    party_code: str
    party_name: str
    opening_balance: Decimal
    business_amount: Decimal
    cash_amount: Decimal
    closing_balance: Decimal
    business_lines: list[BusinessLineRead]
    cash_lines: list[CashLineRead]


class MonthSummaryRead(BaseModel):
    month: str
    account_type: AccountType
    party_id: UUID
    party_code: str
    party_name: str
    opening_balance: Decimal
    business_amount: Decimal
    cash_amount: Decimal
    closing_balance: Decimal


def _month_bounds(month: str) -> tuple[date, date]:
    try:
        if len(month) != 7 or month[4] != "-":
            raise ValueError
        year, month_no = int(month[:4]), int(month[5:])
        start = date(year, month_no, 1)
        end = date(year + 1, 1, 1) if month_no == 12 else date(year, month_no + 1, 1)
        return start, end
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="月份格式必须是 YYYY-MM") from exc


def _authorized(db: Session, user: CurrentUser, account_type: AccountType) -> None:
    menu = {"customer": "reconciliation.customers",
            "supplier": "reconciliation.suppliers",
            "processor": "reconciliation.processors"}[account_type]
    if not has_permission(db, user, menu, "view"):
        raise HTTPException(status_code=403, detail="没有权限")


def _party(db: Session, org: UUID, account_type: AccountType,
           party_id: UUID) -> dict:
    row = db.execute(text("""
        SELECT p.id, p.code, p.name FROM parties p
        JOIN party_types t ON t.party_id = p.id
        WHERE p.organization_id = :org AND p.id = :party
          AND t.party_type = :account
    """), {"org": org, "party": party_id,
           "account": account_type}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="往来单位不存在")
    return dict(row)


def _business(db: Session, org: UUID, party_id: UUID,
              account_type: AccountType, start: date | None,
              end: date, *, details: bool) -> tuple[Decimal, list[dict]]:
    start_dt = datetime.combine(start, time.min, LOCAL_TZ) if start else None
    end_dt = datetime.combine(end, time.min, LOCAL_TZ)
    rows = [dict(row) for row in db.execute(text(f"""
        SELECT id, source_type, source_id, source_line_id,
               amount_delta, posted_at
        FROM business_amount_entries
        WHERE organization_id = :org AND party_id = :party
          AND direction = :direction AND source_type IN {SOURCE_FILTERS[account_type]}
          AND (CAST(:start_at AS timestamptz) IS NULL OR posted_at >= :start_at)
          AND posted_at < :end_at
        ORDER BY posted_at, id
    """), {"org": org, "party": party_id,
           "direction": "receivable" if account_type == "customer" else "payable",
           "start_at": start_dt, "end_at": end_dt}).mappings()]
    return sum((row["amount_delta"] for row in rows), Decimal("0")), rows if details else []


def _cash(db: Session, org: UUID, party_id: UUID,
          account_type: AccountType, start: date | None,
          end: date, *, details: bool) -> tuple[Decimal, list[dict]]:
    rows = [dict(row) for row in db.execute(text("""
        SELECT id, document_no, document_date, amount, source_type, source_id
        FROM cash_records WHERE organization_id = :org AND party_id = :party
          AND account_type = :account
          AND (CAST(:start_date AS date) IS NULL OR document_date >= :start_date)
          AND document_date < :end_date
        ORDER BY document_date, id
    """), {"org": org, "party": party_id, "account": account_type,
           "start_date": start, "end_date": end}).mappings()]
    return sum((row["amount"] for row in rows), Decimal("0")), rows if details else []


def _statement(db: Session, org: UUID, account_type: AccountType,
               party: dict, month: str, start: date, end: date,
               *, details: bool) -> dict:
    seed = db.execute(text("""
        SELECT effective_date, amount FROM party_opening_balances
        WHERE organization_id = :org AND party_id = :party
          AND account_type = :account AND effective_date < :end_date
        ORDER BY effective_date DESC, id DESC LIMIT 1
    """), {"org": org, "party": party["id"], "account": account_type,
           "end_date": end}).mappings().first()
    seed_date = seed["effective_date"] if seed else None
    seed_amount = seed["amount"] if seed else Decimal("0")
    if seed_date is not None and seed_date >= start:
        opening = seed_amount
        period_start = seed_date
    else:
        prior_business, _ = _business(db, org, party["id"], account_type,
                                      seed_date, start, details=False)
        prior_cash, _ = _cash(db, org, party["id"], account_type,
                              seed_date, start, details=False)
        opening = seed_amount + prior_business - prior_cash
        period_start = start
    business, business_lines = _business(db, org, party["id"], account_type,
                                         period_start, end, details=details)
    cash, cash_lines = _cash(db, org, party["id"], account_type,
                             period_start, end, details=details)
    return {
        "month": month, "account_type": account_type, "party_id": party["id"],
        "party_code": party["code"], "party_name": party["name"],
        "opening_balance": opening, "business_amount": business,
        "cash_amount": cash, "closing_balance": opening + business - cash,
        "business_lines": business_lines, "cash_lines": cash_lines,
    }


@router.get("/month-end", response_model=list[MonthSummaryRead])
def month_end(response: Response, month: str, account_type: AccountType,
              limit: int = Query(default=100, ge=1, le=500),
              offset: int = Query(default=0, ge=0),
              user: CurrentUser = Depends(get_current_user),
              db: Session = Depends(get_db)) -> list[dict]:
    _authorized(db, user, account_type)
    start, end = _month_bounds(month)
    query = """
        SELECT p.id, p.code, p.name FROM parties p
        JOIN party_types t ON t.party_id = p.id
        WHERE p.organization_id = :org AND t.party_type = :account
        ORDER BY p.code
    """
    parties = paginate(db, query, {"org": user.organization_id, "account": account_type},
                       limit=limit, offset=offset, response=response)
    return [_statement(db, user.organization_id, account_type,
                       party, month, start, end, details=False)
            for party in parties]


@router.get("/{account_type}/parties/{party_id}/statement", response_model=StatementRead)
def party_statement(account_type: AccountType, party_id: UUID, month: str,
                    user: CurrentUser = Depends(get_current_user),
                    db: Session = Depends(get_db)) -> dict:
    _authorized(db, user, account_type)
    start, end = _month_bounds(month)
    party = _party(db, user.organization_id, account_type, party_id)
    return _statement(db, user.organization_id, account_type,
                      party, month, start, end, details=True)
