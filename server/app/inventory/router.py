from datetime import date, datetime
from io import BytesIO
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import CurrentUser, require_csrf, require_permission
from app.inventory import repository, service
from app.inventory import opening_stock
from app.inventory.schemas import OpeningStockRead, StockBalanceRead, StockMovementRead, TransferCreate, TransferRead, ReverseReason

router = APIRouter(prefix="/api/inventory", tags=["inventory"])
TransferStatus = Literal["draft", "posted", "reversed"]
OpeningStatus = Literal["draft", "posted", "reversed"]


@router.get("/balances", response_model=list[StockBalanceRead])
def list_balances(
    warehouse_id: UUID | None = None,
    user: CurrentUser = Depends(require_permission("inventory.query", "view")),
    db: Session = Depends(get_db),
) -> list[dict]:
    return repository.list_balances(db, user.organization_id, warehouse_id)


@router.get("/movements", response_model=list[StockMovementRead])
def list_movements(
    response: Response,
    warehouse_id: UUID | None = None, item_id: UUID | None = None,
    posted_from: datetime | None = None, posted_to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_permission("inventory.movements", "view")), db: Session = Depends(get_db),
) -> list[dict]:
    if posted_from is not None and posted_from.tzinfo is None:
        raise HTTPException(status_code=422, detail="过账开始时间必须包含时区")
    if posted_to is not None and posted_to.tzinfo is None:
        raise HTTPException(status_code=422, detail="过账结束时间必须包含时区")
    if posted_from is not None and posted_to is not None and posted_to <= posted_from:
        raise HTTPException(status_code=422, detail="过账结束时间必须晚于开始时间")
    return repository.list_movements(
        db, user.organization_id, warehouse_id=warehouse_id, item_id=item_id,
        posted_from=posted_from, posted_to=posted_to, limit=limit, offset=offset,
        response=response,
    )


@router.get("/transfers", response_model=list[TransferRead])
def list_transfers(
    response: Response,
    status: TransferStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_permission("inventory.transfers", "view")),
    db: Session = Depends(get_db),
) -> list[dict]:
    return repository.list_transfers(db, user.organization_id, status=status,
                                     limit=limit, offset=offset, response=response)


@router.get("/transfers/{transfer_id}", response_model=TransferRead)
def get_transfer(
    transfer_id: UUID,
    user: CurrentUser = Depends(require_permission("inventory.transfers", "view")),
    db: Session = Depends(get_db),
) -> dict:
    result = repository.get_transfer(db, user.organization_id, transfer_id)
    if result is None:
        raise HTTPException(status_code=404, detail="调拨单不存在")
    return result


@router.post("/transfers", response_model=TransferRead, status_code=201, dependencies=[Depends(require_csrf)])
def create_transfer(
    payload: TransferCreate,
    user: CurrentUser = Depends(require_permission("inventory.transfers", "create")),
    db: Session = Depends(get_db),
) -> dict:
    return service.create_transfer(db, user.organization_id, user.id, payload)


@router.post("/transfers/{transfer_id}/post", response_model=TransferRead, dependencies=[Depends(require_csrf)])
def post_transfer(
    transfer_id: UUID,
    user: CurrentUser = Depends(require_permission("inventory.transfers", "post")),
    db: Session = Depends(get_db),
) -> dict:
    return service.post_transfer(db, user.organization_id, user.id, transfer_id)


@router.post("/transfers/{transfer_id}/reverse", response_model=TransferRead,
             dependencies=[Depends(require_csrf)])
def reverse_transfer(transfer_id: UUID, payload: ReverseReason,
                     user: CurrentUser = Depends(require_permission("inventory.transfers", "reverse")),
                     db: Session = Depends(get_db)) -> dict:
    return service.reverse_transfer(db, user.organization_id, user.id,
                                    transfer_id, payload.reason)


@router.get("/opening-stock/template")
def opening_stock_template(user: CurrentUser = Depends(require_permission("system.initialization", "view"))) -> StreamingResponse:
    return StreamingResponse(
        BytesIO(opening_stock.template_bytes()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="opening-stock-template.xlsx"'},
    )


@router.post(
    "/opening-stock/import", response_model=OpeningStockRead, status_code=201,
    dependencies=[Depends(require_csrf)],
)
def import_opening_stock(
    effective_date: date = Form(...),
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_permission("system.initialization", "create")),
    db: Session = Depends(get_db),
) -> dict:
    content = file.file.read(opening_stock.MAX_FILE_BYTES + 1)
    return opening_stock.import_document(
        db, organization_id=user.organization_id, actor_id=user.id,
        effective_date=effective_date, filename=file.filename or "", content=content,
    )


@router.post("/opening-stock/preview", dependencies=[Depends(require_csrf)])
def preview_opening_stock(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_permission("system.initialization", "view")),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = opening_stock.prepare_lines(db, user.organization_id, file.filename or "",
                                       file.file.read(opening_stock.MAX_FILE_BYTES + 1))
    return [{key: row[key] for key in ("row_no", "warehouse_code", "item_code",
                                      "unit_code", "quantity", "factor", "quantity_base")}
            for row in rows]


@router.get("/opening-stock", response_model=list[OpeningStockRead])
def list_opening_stock(
    response: Response,
    status: OpeningStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_permission("system.initialization", "view")),
    db: Session = Depends(get_db),
) -> list[dict]:
    return opening_stock.list_documents(db, user.organization_id, status=status,
                                        limit=limit, offset=offset, response=response)


@router.get("/opening-stock/{document_id}", response_model=OpeningStockRead)
def get_opening_stock(
    document_id: UUID, user: CurrentUser = Depends(require_permission("system.initialization", "view")), db: Session = Depends(get_db)
) -> dict:
    return opening_stock.get_document(db, user.organization_id, document_id)


@router.post(
    "/opening-stock/{document_id}/post", response_model=OpeningStockRead,
    dependencies=[Depends(require_csrf)],
)
def post_opening_stock(
    document_id: UUID, user: CurrentUser = Depends(require_permission("system.initialization", "post")), db: Session = Depends(get_db)
) -> dict:
    return opening_stock.post_document(db, user.organization_id, user.id, document_id)


@router.post("/opening-stock/{document_id}/reverse", response_model=OpeningStockRead,
             dependencies=[Depends(require_csrf)])
def reverse_opening_stock(document_id: UUID, payload: ReverseReason,
                          user: CurrentUser = Depends(require_permission("system.initialization", "reverse")),
                          db: Session = Depends(get_db)) -> dict:
    return opening_stock.reverse_document(db, user.organization_id, user.id,
                                          document_id, payload.reason)
