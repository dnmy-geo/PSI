from fastapi import FastAPI
from sqlalchemy import text

from app.auth.router import router as auth_router
from app.approval.router import router as approval_router
from app.core.db import get_engine
from app.inventory.router import router as inventory_router
from app.inventory.stocktake import router as stocktake_router
from app.inventory.adjustment import router as adjustment_router
from app.masterdata.catalog.router import router as catalog_router
from app.masterdata.categories.router import router as categories_router
from app.masterdata.bom.router import router as bom_router
from app.masterdata.parties.router import router as parties_router
from app.masterdata.warehouses.router import router as warehouse_router
from app.system.router import router as system_router
from app.system.audit import router as audit_router
from app.system.menus import router as menu_router
from app.system.carryover import router as carryover_router
from app.sales.router import router as sales_router
from app.sales.fulfillment_router import router as sales_fulfillment_router
from app.purchase.router import router as purchase_router
from app.purchase.fulfillment_router import router as purchase_fulfillment_router
from app.outsourcing.router import router as outsourcing_router
from app.outsourcing.fulfillment_router import router as outsourcing_fulfillment_router
from app.reconciliation.records import router as reconciliation_records_router
from app.reconciliation.statements import router as reconciliation_statements_router
from app.reports.router import router as reports_router
from app.workbench.router import router as workbench_router
from app.production.router import router as production_router
from app.production.operations_router import router as production_operations_router

app = FastAPI(title="PSI 进销存 API", version="0.1.0")
app.include_router(auth_router)
app.include_router(approval_router)
app.include_router(catalog_router)
app.include_router(categories_router)
app.include_router(bom_router)
app.include_router(parties_router)
app.include_router(warehouse_router)
app.include_router(inventory_router)
app.include_router(stocktake_router)
app.include_router(adjustment_router)
app.include_router(system_router)
app.include_router(audit_router)
app.include_router(menu_router)
app.include_router(carryover_router)
app.include_router(sales_router)
app.include_router(sales_fulfillment_router)
app.include_router(purchase_router)
app.include_router(purchase_fulfillment_router)
app.include_router(outsourcing_router)
app.include_router(outsourcing_fulfillment_router)
app.include_router(reconciliation_records_router)
app.include_router(reconciliation_statements_router)
app.include_router(reports_router)
app.include_router(workbench_router)
app.include_router(production_router)
app.include_router(production_operations_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    with get_engine().connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    return {"status": "ok", "database_revision": revision}
