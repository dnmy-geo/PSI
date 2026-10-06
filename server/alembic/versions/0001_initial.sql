-- PSI baseline schema. Execute once inside a transaction.
-- All quantities are in an item's base unit unless a unit snapshot is present.

CREATE TABLE organizations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE departments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    parent_id uuid REFERENCES departments(id),
    code text NOT NULL,
    name text NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    UNIQUE (organization_id, code),
    UNIQUE (id, organization_id),
    CHECK (parent_id IS DISTINCT FROM id)
);

CREATE TABLE roles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    code text NOT NULL,
    name text NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    UNIQUE (organization_id, code),
    UNIQUE (id, organization_id)
);

CREATE TABLE users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    department_id uuid,
    username text NOT NULL,
    display_name text NOT NULL,
    password_hash text NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, username),
    UNIQUE (id, organization_id),
    FOREIGN KEY (department_id, organization_id) REFERENCES departments(id, organization_id)
);

CREATE TABLE user_roles (
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id uuid NOT NULL REFERENCES roles(id),
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE menus (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id uuid REFERENCES menus(id),
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    path text,
    sort_order integer NOT NULL DEFAULT 0,
    is_active boolean NOT NULL DEFAULT true,
    CHECK (parent_id IS DISTINCT FROM id)
);

CREATE TABLE role_permissions (
    role_id uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    menu_id uuid NOT NULL REFERENCES menus(id),
    action_code text NOT NULL,
    PRIMARY KEY (role_id, menu_id, action_code)
);

CREATE TABLE auth_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    CHECK (expires_at > created_at)
);

CREATE TABLE approval_configs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    document_type text NOT NULL,
    is_enabled boolean NOT NULL DEFAULT true,
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, document_type)
);

CREATE TABLE approval_config_steps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    config_id uuid NOT NULL REFERENCES approval_configs(id) ON DELETE CASCADE,
    step_no integer NOT NULL CHECK (step_no > 0),
    approver_role_id uuid REFERENCES roles(id),
    approver_user_id uuid REFERENCES users(id),
    UNIQUE (config_id, step_no),
    CHECK (num_nonnulls(approver_role_id, approver_user_id) = 1)
);

CREATE TABLE approval_instances (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    config_id uuid NOT NULL REFERENCES approval_configs(id),
    config_version integer NOT NULL,
    document_type text NOT NULL,
    document_id uuid NOT NULL,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','cancelled')),
    current_step_no integer NOT NULL DEFAULT 1 CHECK (current_step_no > 0),
    submitted_by uuid NOT NULL REFERENCES users(id),
    submitted_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);

CREATE UNIQUE INDEX uq_approval_one_pending ON approval_instances(document_type, document_id) WHERE status = 'pending';

CREATE TABLE approval_tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    instance_id uuid NOT NULL REFERENCES approval_instances(id),
    step_no integer NOT NULL CHECK (step_no > 0),
    approver_role_id uuid REFERENCES roles(id),
    approver_user_id uuid REFERENCES users(id),
    acted_by uuid REFERENCES users(id),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','skipped')),
    opinion text,
    created_at timestamptz NOT NULL DEFAULT now(),
    acted_at timestamptz,
    CHECK (num_nonnulls(approver_role_id, approver_user_id) = 1)
);

CREATE TABLE audit_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid REFERENCES organizations(id),
    actor_id uuid REFERENCES users(id),
    action_code text NOT NULL,
    document_type text,
    document_id uuid,
    reason text,
    change_summary jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE units (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    code text NOT NULL,
    name text NOT NULL,
    precision_scale smallint NOT NULL DEFAULT 0 CHECK (precision_scale BETWEEN 0 AND 6),
    is_active boolean NOT NULL DEFAULT true,
    UNIQUE (organization_id, code),
    UNIQUE (id, organization_id)
);

CREATE TABLE item_categories (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    parent_id uuid REFERENCES item_categories(id),
    code text NOT NULL,
    name text NOT NULL,
    UNIQUE (organization_id, code),
    UNIQUE (id, organization_id),
    CHECK (parent_id IS DISTINCT FROM id)
);

CREATE TABLE items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    category_id uuid,
    code text NOT NULL,
    name text NOT NULL,
    item_type text NOT NULL CHECK (item_type IN ('raw_material','semi_finished','finished')),
    base_unit_id uuid NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, code),
    UNIQUE (id, organization_id),
    FOREIGN KEY (category_id, organization_id) REFERENCES item_categories(id, organization_id),
    FOREIGN KEY (base_unit_id, organization_id) REFERENCES units(id, organization_id)
);

CREATE TABLE item_unit_conversions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id uuid NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    unit_id uuid NOT NULL REFERENCES units(id),
    factor_to_base numeric(20,6) NOT NULL CHECK (factor_to_base > 0),
    UNIQUE (item_id, unit_id)
);

CREATE TABLE bom_headers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    parent_item_id uuid NOT NULL,
    version integer NOT NULL DEFAULT 1 CHECK (version > 0),
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, parent_item_id, version),
    FOREIGN KEY (parent_item_id, organization_id) REFERENCES items(id, organization_id)
);

CREATE UNIQUE INDEX uq_bom_one_active ON bom_headers(organization_id, parent_item_id) WHERE is_active;

CREATE TABLE bom_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    bom_id uuid NOT NULL REFERENCES bom_headers(id) ON DELETE CASCADE,
    child_item_id uuid NOT NULL REFERENCES items(id),
    quantity_base numeric(20,6) NOT NULL CHECK (quantity_base > 0),
    sort_order integer NOT NULL DEFAULT 0,
    UNIQUE (bom_id, child_item_id)
);

CREATE TABLE parties (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    code text NOT NULL,
    name text NOT NULL,
    contact_name text,
    contact_phone text,
    is_active boolean NOT NULL DEFAULT true,
    UNIQUE (organization_id, code),
    UNIQUE (id, organization_id)
);

CREATE TABLE party_types (
    party_id uuid NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
    party_type text NOT NULL CHECK (party_type IN ('customer','supplier','processor')),
    PRIMARY KEY (party_id, party_type)
);

CREATE TABLE warehouses (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    code text NOT NULL,
    name text NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, code),
    UNIQUE (id, organization_id)
);

CREATE TABLE stock_balances (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    warehouse_id uuid NOT NULL,
    item_id uuid NOT NULL,
    quantity_base numeric(20,6) NOT NULL DEFAULT 0 CHECK (quantity_base >= 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, warehouse_id, item_id),
    FOREIGN KEY (warehouse_id, organization_id) REFERENCES warehouses(id, organization_id),
    FOREIGN KEY (item_id, organization_id) REFERENCES items(id, organization_id)
);

CREATE TABLE stock_movements (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    warehouse_id uuid NOT NULL,
    item_id uuid NOT NULL,
    quantity_delta_base numeric(20,6) NOT NULL CHECK (quantity_delta_base <> 0),
    source_type text NOT NULL,
    source_id uuid NOT NULL,
    source_line_id uuid NOT NULL,
    movement_kind text NOT NULL,
    reversal_of_id uuid REFERENCES stock_movements(id),
    posted_by uuid REFERENCES users(id),
    posted_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, source_type, source_line_id, warehouse_id, movement_kind),
    FOREIGN KEY (warehouse_id, organization_id) REFERENCES warehouses(id, organization_id),
    FOREIGN KEY (item_id, organization_id) REFERENCES items(id, organization_id)
);

CREATE INDEX ix_stock_movements_lookup ON stock_movements(organization_id, warehouse_id, item_id, posted_at);

CREATE TABLE stock_transfers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    document_no text NOT NULL,
    document_date date NOT NULL,
    source_warehouse_id uuid NOT NULL,
    target_warehouse_id uuid NOT NULL,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','posted','reversed')),
    remark text,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    posted_at timestamptz,
    UNIQUE (organization_id, document_no),
    CHECK (source_warehouse_id <> target_warehouse_id),
    FOREIGN KEY (source_warehouse_id, organization_id) REFERENCES warehouses(id, organization_id),
    FOREIGN KEY (target_warehouse_id, organization_id) REFERENCES warehouses(id, organization_id)
);

CREATE TABLE stock_transfer_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    transfer_id uuid NOT NULL REFERENCES stock_transfers(id) ON DELETE CASCADE,
    item_id uuid NOT NULL REFERENCES items(id),
    quantity numeric(20,6) NOT NULL CHECK (quantity > 0),
    unit_id uuid NOT NULL REFERENCES units(id),
    conversion_factor numeric(20,6) NOT NULL CHECK (conversion_factor > 0),
    quantity_base numeric(20,6) NOT NULL CHECK (quantity_base > 0)
);

CREATE TABLE stocktakes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    document_no text NOT NULL,
    warehouse_id uuid NOT NULL,
    cutoff_at timestamptz,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','counting','pending_approval','approved','rejected','cancelled')),
    document_date date NOT NULL,
    remark text,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, document_no),
    FOREIGN KEY (warehouse_id, organization_id) REFERENCES warehouses(id, organization_id)
);

CREATE UNIQUE INDEX uq_stocktake_one_counting ON stocktakes(warehouse_id) WHERE status = 'counting';

CREATE TABLE stocktake_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    stocktake_id uuid NOT NULL REFERENCES stocktakes(id) ON DELETE CASCADE,
    item_id uuid NOT NULL REFERENCES items(id),
    book_quantity_base numeric(20,6) NOT NULL CHECK (book_quantity_base >= 0),
    counted_quantity_base numeric(20,6) CHECK (counted_quantity_base >= 0),
    UNIQUE (stocktake_id, item_id)
);

CREATE TABLE stock_adjustments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    document_no text NOT NULL,
    document_date date NOT NULL,
    warehouse_id uuid NOT NULL,
    stocktake_id uuid UNIQUE REFERENCES stocktakes(id),
    reason text NOT NULL,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','posted','reversed')),
    remark text,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    posted_at timestamptz,
    UNIQUE (organization_id, document_no),
    FOREIGN KEY (warehouse_id, organization_id) REFERENCES warehouses(id, organization_id)
);

CREATE TABLE stock_adjustment_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    adjustment_id uuid NOT NULL REFERENCES stock_adjustments(id) ON DELETE CASCADE,
    item_id uuid NOT NULL REFERENCES items(id),
    quantity_delta_base numeric(20,6) NOT NULL CHECK (quantity_delta_base <> 0)
);

CREATE TABLE opening_stock_docs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    document_no text NOT NULL,
    effective_date date NOT NULL,
    import_batch_no text,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','posted','reversed')),
    remark text,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    posted_at timestamptz,
    UNIQUE (organization_id, document_no)
);

CREATE TABLE opening_stock_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    opening_doc_id uuid NOT NULL REFERENCES opening_stock_docs(id) ON DELETE CASCADE,
    warehouse_id uuid NOT NULL REFERENCES warehouses(id),
    item_id uuid NOT NULL REFERENCES items(id),
    quantity numeric(20,6) NOT NULL CHECK (quantity > 0),
    unit_id uuid NOT NULL REFERENCES units(id),
    conversion_factor numeric(20,6) NOT NULL CHECK (conversion_factor > 0),
    quantity_base numeric(20,6) NOT NULL CHECK (quantity_base > 0),
    UNIQUE (opening_doc_id, warehouse_id, item_id)
);

CREATE TABLE sales_orders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    document_no text NOT NULL,
    customer_id uuid NOT NULL,
    document_date date NOT NULL,
    delivery_date date,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','pending_approval','approved','rejected','closed')),
    close_remark text,
    remark text,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, document_no),
    CHECK (status <> 'closed' OR nullif(trim(close_remark),'') IS NOT NULL),
    FOREIGN KEY (customer_id, organization_id) REFERENCES parties(id, organization_id)
);

CREATE TABLE sales_order_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sales_order_id uuid NOT NULL REFERENCES sales_orders(id) ON DELETE CASCADE,
    item_id uuid NOT NULL REFERENCES items(id),
    quantity numeric(20,6) NOT NULL CHECK (quantity > 0),
    unit_id uuid NOT NULL REFERENCES units(id),
    conversion_factor numeric(20,6) NOT NULL CHECK (conversion_factor > 0),
    quantity_base numeric(20,6) NOT NULL CHECK (quantity_base > 0),
    unit_price numeric(18,6) NOT NULL CHECK (unit_price >= 0),
    amount numeric(18,2) NOT NULL CHECK (amount >= 0)
);

CREATE TABLE sales_shipments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    document_no text NOT NULL,
    sales_order_id uuid NOT NULL REFERENCES sales_orders(id),
    warehouse_id uuid NOT NULL,
    document_date date NOT NULL,
    shipment_type text NOT NULL CHECK (shipment_type IN ('normal','replacement')),
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','posted','reversed')),
    remark text,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    posted_at timestamptz,
    UNIQUE (organization_id, document_no),
    FOREIGN KEY (warehouse_id, organization_id) REFERENCES warehouses(id, organization_id)
);

CREATE TABLE sales_shipment_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    shipment_id uuid NOT NULL REFERENCES sales_shipments(id) ON DELETE CASCADE,
    sales_order_line_id uuid NOT NULL REFERENCES sales_order_lines(id),
    item_id uuid NOT NULL REFERENCES items(id),
    quantity numeric(20,6) NOT NULL CHECK (quantity > 0),
    unit_id uuid NOT NULL REFERENCES units(id),
    conversion_factor numeric(20,6) NOT NULL CHECK (conversion_factor > 0),
    quantity_base numeric(20,6) NOT NULL CHECK (quantity_base > 0),
    replacement_return_line_id uuid,
    CHECK (replacement_return_line_id IS NULL OR quantity_base > 0)
);

CREATE TABLE sales_returns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    document_no text NOT NULL,
    original_shipment_id uuid NOT NULL REFERENCES sales_shipments(id),
    target_warehouse_id uuid NOT NULL,
    document_date date NOT NULL,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','posted','reversed')),
    remark text,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    posted_at timestamptz,
    UNIQUE (organization_id, document_no),
    FOREIGN KEY (target_warehouse_id, organization_id) REFERENCES warehouses(id, organization_id)
);

CREATE TABLE sales_return_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    sales_return_id uuid NOT NULL REFERENCES sales_returns(id) ON DELETE CASCADE,
    sales_shipment_line_id uuid NOT NULL REFERENCES sales_shipment_lines(id),
    item_id uuid NOT NULL REFERENCES items(id),
    quantity numeric(20,6) NOT NULL CHECK (quantity > 0),
    unit_id uuid NOT NULL REFERENCES units(id),
    conversion_factor numeric(20,6) NOT NULL CHECK (conversion_factor > 0),
    quantity_base numeric(20,6) NOT NULL CHECK (quantity_base > 0)
);

ALTER TABLE sales_shipment_lines ADD CONSTRAINT fk_shipment_replacement_return
    FOREIGN KEY (replacement_return_line_id) REFERENCES sales_return_lines(id);

CREATE TABLE purchase_orders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    document_no text NOT NULL,
    supplier_id uuid NOT NULL,
    document_date date NOT NULL,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','open','closed')),
    close_remark text,
    remark text,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, document_no),
    CHECK (status <> 'closed' OR nullif(trim(close_remark),'') IS NOT NULL),
    FOREIGN KEY (supplier_id, organization_id) REFERENCES parties(id, organization_id)
);

CREATE TABLE purchase_order_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    purchase_order_id uuid NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    item_id uuid NOT NULL REFERENCES items(id),
    quantity numeric(20,6) NOT NULL CHECK (quantity > 0),
    unit_id uuid NOT NULL REFERENCES units(id),
    conversion_factor numeric(20,6) NOT NULL CHECK (conversion_factor > 0),
    quantity_base numeric(20,6) NOT NULL CHECK (quantity_base > 0),
    unit_price numeric(18,6) NOT NULL CHECK (unit_price >= 0),
    amount numeric(18,2) NOT NULL CHECK (amount >= 0)
);

CREATE TABLE purchase_receipts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    document_no text NOT NULL,
    purchase_order_id uuid NOT NULL REFERENCES purchase_orders(id),
    warehouse_id uuid NOT NULL,
    document_date date NOT NULL,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','posted','reversed')),
    remark text,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    posted_at timestamptz,
    UNIQUE (organization_id, document_no),
    FOREIGN KEY (warehouse_id, organization_id) REFERENCES warehouses(id, organization_id)
);

CREATE TABLE purchase_receipt_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    receipt_id uuid NOT NULL REFERENCES purchase_receipts(id) ON DELETE CASCADE,
    purchase_order_line_id uuid NOT NULL REFERENCES purchase_order_lines(id),
    item_id uuid NOT NULL REFERENCES items(id),
    quantity numeric(20,6) NOT NULL CHECK (quantity > 0),
    unit_id uuid NOT NULL REFERENCES units(id),
    conversion_factor numeric(20,6) NOT NULL CHECK (conversion_factor > 0),
    quantity_base numeric(20,6) NOT NULL CHECK (quantity_base > 0),
    unit_price numeric(18,6) NOT NULL CHECK (unit_price >= 0),
    amount numeric(18,2) NOT NULL CHECK (amount >= 0)
);

CREATE TABLE purchase_returns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    document_no text NOT NULL,
    original_receipt_id uuid NOT NULL REFERENCES purchase_receipts(id),
    warehouse_id uuid NOT NULL,
    document_date date NOT NULL,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','posted','reversed')),
    remark text,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    posted_at timestamptz,
    UNIQUE (organization_id, document_no),
    FOREIGN KEY (warehouse_id, organization_id) REFERENCES warehouses(id, organization_id)
);

CREATE TABLE purchase_return_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    purchase_return_id uuid NOT NULL REFERENCES purchase_returns(id) ON DELETE CASCADE,
    purchase_receipt_line_id uuid NOT NULL REFERENCES purchase_receipt_lines(id),
    item_id uuid NOT NULL REFERENCES items(id),
    quantity numeric(20,6) NOT NULL CHECK (quantity > 0),
    unit_id uuid NOT NULL REFERENCES units(id),
    conversion_factor numeric(20,6) NOT NULL CHECK (conversion_factor > 0),
    quantity_base numeric(20,6) NOT NULL CHECK (quantity_base > 0),
    amount numeric(18,2) NOT NULL CHECK (amount >= 0)
);

CREATE TABLE production_plans (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    document_no text NOT NULL,
    document_date date NOT NULL,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','open','closed')),
    remark text,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, document_no)
);

CREATE TABLE production_plan_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    production_plan_id uuid NOT NULL REFERENCES production_plans(id) ON DELETE CASCADE,
    item_id uuid NOT NULL REFERENCES items(id),
    planned_quantity_base bigint NOT NULL CHECK (planned_quantity_base > 0)
);

CREATE TABLE production_orders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    document_no text NOT NULL,
    production_plan_id uuid NOT NULL REFERENCES production_plans(id),
    document_date date NOT NULL,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','open','completed','cancelled')),
    remark text,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, document_no)
);

CREATE TABLE production_order_outputs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    production_order_id uuid NOT NULL REFERENCES production_orders(id) ON DELETE CASCADE,
    production_plan_line_id uuid NOT NULL REFERENCES production_plan_lines(id),
    item_id uuid NOT NULL REFERENCES items(id),
    planned_quantity_base bigint NOT NULL CHECK (planned_quantity_base > 0)
);

CREATE TABLE production_issues (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    document_no text NOT NULL,
    production_order_id uuid NOT NULL REFERENCES production_orders(id),
    source_warehouse_id uuid NOT NULL REFERENCES warehouses(id),
    target_warehouse_id uuid NOT NULL REFERENCES warehouses(id),
    document_date date NOT NULL,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','posted','reversed')),
    remark text,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    posted_at timestamptz,
    UNIQUE (organization_id, document_no),
    CHECK (source_warehouse_id <> target_warehouse_id)
);

CREATE TABLE production_issue_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    issue_id uuid NOT NULL REFERENCES production_issues(id) ON DELETE CASCADE,
    item_id uuid NOT NULL REFERENCES items(id),
    bom_quantity_base numeric(20,6) CHECK (bom_quantity_base >= 0),
    loss_quantity_base numeric(20,6) NOT NULL DEFAULT 0 CHECK (loss_quantity_base >= 0),
    quantity numeric(20,6) NOT NULL CHECK (quantity > 0),
    unit_id uuid NOT NULL REFERENCES units(id),
    conversion_factor numeric(20,6) NOT NULL CHECK (conversion_factor > 0),
    quantity_base numeric(20,6) NOT NULL CHECK (quantity_base > 0)
);

CREATE TABLE production_consumptions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    document_no text NOT NULL,
    production_order_id uuid NOT NULL REFERENCES production_orders(id),
    warehouse_id uuid NOT NULL REFERENCES warehouses(id),
    document_date date NOT NULL,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','posted','reversed')),
    remark text,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    posted_at timestamptz,
    UNIQUE (organization_id, document_no)
);

CREATE TABLE production_consumption_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    consumption_id uuid NOT NULL REFERENCES production_consumptions(id) ON DELETE CASCADE,
    item_id uuid NOT NULL REFERENCES items(id),
    quantity numeric(20,6) NOT NULL CHECK (quantity > 0),
    unit_id uuid NOT NULL REFERENCES units(id),
    conversion_factor numeric(20,6) NOT NULL CHECK (conversion_factor > 0),
    quantity_base numeric(20,6) NOT NULL CHECK (quantity_base > 0)
);

CREATE TABLE production_receipts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    document_no text NOT NULL,
    production_order_id uuid NOT NULL UNIQUE REFERENCES production_orders(id),
    document_date date NOT NULL,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','posted','reversed')),
    remark text,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    posted_at timestamptz,
    UNIQUE (organization_id, document_no)
);

CREATE TABLE production_receipt_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    receipt_id uuid NOT NULL REFERENCES production_receipts(id) ON DELETE CASCADE,
    production_order_output_id uuid NOT NULL REFERENCES production_order_outputs(id),
    item_id uuid NOT NULL REFERENCES items(id),
    target_warehouse_id uuid NOT NULL REFERENCES warehouses(id),
    quantity_base bigint NOT NULL CHECK (quantity_base > 0),
    UNIQUE (receipt_id, production_order_output_id, target_warehouse_id)
);

CREATE TABLE outsourcing_orders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    document_no text NOT NULL,
    processor_id uuid NOT NULL,
    document_date date NOT NULL,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','open','closed')),
    remark text,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, document_no),
    FOREIGN KEY (processor_id, organization_id) REFERENCES parties(id, organization_id)
);

CREATE TABLE outsourcing_material_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    outsourcing_order_id uuid NOT NULL REFERENCES outsourcing_orders(id) ON DELETE CASCADE,
    item_id uuid NOT NULL REFERENCES items(id),
    supply_party text NOT NULL CHECK (supply_party IN ('self','processor')),
    expected_quantity_base numeric(20,6) NOT NULL CHECK (expected_quantity_base > 0)
);

CREATE TABLE outsourcing_output_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    outsourcing_order_id uuid NOT NULL REFERENCES outsourcing_orders(id) ON DELETE CASCADE,
    item_id uuid NOT NULL REFERENCES items(id),
    expected_quantity_base numeric(20,6) NOT NULL CHECK (expected_quantity_base > 0),
    unit_price numeric(18,6) NOT NULL CHECK (unit_price >= 0)
);

CREATE TABLE outsourcing_issues (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    document_no text NOT NULL,
    outsourcing_order_id uuid NOT NULL REFERENCES outsourcing_orders(id),
    warehouse_id uuid NOT NULL REFERENCES warehouses(id),
    document_date date NOT NULL,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','posted','reversed')),
    remark text,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    posted_at timestamptz,
    UNIQUE (organization_id, document_no)
);

CREATE TABLE outsourcing_issue_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    issue_id uuid NOT NULL REFERENCES outsourcing_issues(id) ON DELETE CASCADE,
    outsourcing_material_line_id uuid NOT NULL REFERENCES outsourcing_material_lines(id),
    item_id uuid NOT NULL REFERENCES items(id),
    quantity numeric(20,6) NOT NULL CHECK (quantity > 0),
    unit_id uuid NOT NULL REFERENCES units(id),
    conversion_factor numeric(20,6) NOT NULL CHECK (conversion_factor > 0),
    quantity_base numeric(20,6) NOT NULL CHECK (quantity_base > 0)
);

CREATE TABLE outsourcing_receipts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    document_no text NOT NULL,
    outsourcing_order_id uuid NOT NULL REFERENCES outsourcing_orders(id),
    warehouse_id uuid NOT NULL REFERENCES warehouses(id),
    document_date date NOT NULL,
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','posted','reversed')),
    remark text,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    posted_at timestamptz,
    UNIQUE (organization_id, document_no)
);

CREATE TABLE outsourcing_receipt_lines (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    receipt_id uuid NOT NULL REFERENCES outsourcing_receipts(id) ON DELETE CASCADE,
    outsourcing_output_line_id uuid NOT NULL REFERENCES outsourcing_output_lines(id),
    item_id uuid NOT NULL REFERENCES items(id),
    quantity numeric(20,6) NOT NULL CHECK (quantity > 0),
    unit_id uuid NOT NULL REFERENCES units(id),
    conversion_factor numeric(20,6) NOT NULL CHECK (conversion_factor > 0),
    quantity_base numeric(20,6) NOT NULL CHECK (quantity_base > 0),
    unit_price numeric(18,6) NOT NULL CHECK (unit_price >= 0),
    amount numeric(18,2) NOT NULL CHECK (amount >= 0)
);

CREATE TABLE business_amount_entries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    party_id uuid NOT NULL,
    direction text NOT NULL CHECK (direction IN ('receivable','payable')),
    amount_delta numeric(18,2) NOT NULL CHECK (amount_delta <> 0),
    source_type text NOT NULL,
    source_id uuid NOT NULL,
    source_line_id uuid NOT NULL,
    reversal_of_id uuid REFERENCES business_amount_entries(id),
    posted_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, source_type, source_line_id, direction),
    FOREIGN KEY (party_id, organization_id) REFERENCES parties(id, organization_id)
);

CREATE TABLE cash_records (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    document_no text NOT NULL,
    party_id uuid NOT NULL,
    record_type text NOT NULL CHECK (record_type IN ('receipt','payment')),
    document_date date NOT NULL,
    amount numeric(18,2) NOT NULL CHECK (amount > 0),
    source_type text,
    source_id uuid,
    remark text,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, document_no),
    FOREIGN KEY (party_id, organization_id) REFERENCES parties(id, organization_id),
    CHECK ((source_type IS NULL) = (source_id IS NULL))
);

CREATE TABLE party_opening_balances (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    party_id uuid NOT NULL,
    direction text NOT NULL CHECK (direction IN ('receivable','payable')),
    effective_date date NOT NULL,
    amount numeric(18,2) NOT NULL CHECK (amount >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, party_id, direction, effective_date),
    FOREIGN KEY (party_id, organization_id) REFERENCES parties(id, organization_id)
);

CREATE INDEX ix_sales_order_customer_date ON sales_orders(organization_id, customer_id, document_date);
CREATE INDEX ix_purchase_order_supplier_date ON purchase_orders(organization_id, supplier_id, document_date);
CREATE INDEX ix_business_amount_party_date ON business_amount_entries(organization_id, party_id, posted_at);
CREATE INDEX ix_cash_record_party_date ON cash_records(organization_id, party_id, document_date);
CREATE INDEX ix_approval_tasks_pending ON approval_tasks(approver_user_id, status) WHERE status = 'pending';
CREATE INDEX ix_auth_sessions_user_active ON auth_sessions(user_id, expires_at) WHERE revoked_at IS NULL;
