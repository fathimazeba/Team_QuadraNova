-- ============================================================================
-- Brightloop Subscription Management System - Complete Frozen Schema
-- Incorporates all validated gap-analysis enhancements:
-- 1. Quotation validity, template reference & sales rep tracking
-- 2. Add-on line toggling (is_active) and pause/close lifecycle timestamps
-- 3. Invoices duplicate billing period protection UNIQUE(subscription_id, period_start, period_end)
-- 4. Invoices balance_due <= total_amount constraint & discount_rule link
-- 5. User creation audit trail (created_by_user_id)
-- 6. High-performance reporting indexes for <2s query latency
-- ============================================================================

-- 1. Identity & Multi-User Customer Architecture
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('ADMIN', 'STAFF', 'CUSTOMER')),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_by_user_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    contact_name TEXT,
    phone TEXT,
    billing_address TEXT,
    vat_tax_number TEXT,
    currency TEXT NOT NULL DEFAULT 'USD' CHECK(length(currency) = 3 AND currency = upper(currency)),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS customer_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    role_within_customer TEXT NOT NULL DEFAULT 'OWNER' CHECK(role_within_customer IN ('OWNER', 'BILLING', 'MEMBER')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(customer_id, user_id)
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_hash TEXT UNIQUE NOT NULL,
    csrf_token TEXT NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_hash TEXT UNIQUE NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    used INTEGER NOT NULL DEFAULT 0 CHECK(used IN (0, 1)),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 2. Product Catalog & Attribute Variants
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('SOFTWARE', 'ADD_ON', 'SERVICE')),
    sales_price_minor_units INTEGER NOT NULL DEFAULT 0 CHECK(sales_price_minor_units >= 0),
    cost_price_minor_units INTEGER NOT NULL DEFAULT 0 CHECK(cost_price_minor_units >= 0),
    notes TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS product_attributes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    UNIQUE(product_id, name)
);

CREATE TABLE IF NOT EXISTS product_attribute_values (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attribute_id INTEGER NOT NULL,
    value_name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (attribute_id) REFERENCES product_attributes(id) ON DELETE CASCADE,
    UNIQUE(attribute_id, value_name)
);

CREATE TABLE IF NOT EXISTS product_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    sku TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    price_extra_minor_units INTEGER NOT NULL DEFAULT 0 CHECK(price_extra_minor_units >= 0),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS variant_attribute_map (
    variant_id INTEGER NOT NULL,
    attribute_value_id INTEGER NOT NULL,
    PRIMARY KEY (variant_id, attribute_value_id),
    FOREIGN KEY (variant_id) REFERENCES product_variants(id) ON DELETE CASCADE,
    FOREIGN KEY (attribute_value_id) REFERENCES product_attribute_values(id) ON DELETE CASCADE
);

-- 3. Subscription Plans & Policies
CREATE TABLE IF NOT EXISTS subscription_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    billing_frequency TEXT NOT NULL CHECK(billing_frequency IN ('DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY')),
    base_cost_minor_units INTEGER NOT NULL DEFAULT 0 CHECK(base_cost_minor_units >= 0),
    minimum_quantity INTEGER NOT NULL DEFAULT 1 CHECK(minimum_quantity > 0),
    available_from DATE NOT NULL,
    available_until DATE,
    currency TEXT NOT NULL DEFAULT 'USD' CHECK(length(currency) = 3 AND currency = upper(currency)),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS plan_policies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER UNIQUE NOT NULL,
    auto_close_on_expiry INTEGER NOT NULL DEFAULT 1 CHECK(auto_close_on_expiry IN (0, 1)),
    allow_early_close INTEGER NOT NULL DEFAULT 1 CHECK(allow_early_close IN (0, 1)),
    allow_pause INTEGER NOT NULL DEFAULT 0 CHECK(allow_pause IN (0, 1)),
    allow_renewal INTEGER NOT NULL DEFAULT 1 CHECK(allow_renewal IN (0, 1)),
    FOREIGN KEY (plan_id) REFERENCES subscription_plans(id) ON DELETE CASCADE
);

-- 4. Quotation Templates & Subscriptions
CREATE TABLE IF NOT EXISTS quotation_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    plan_id INTEGER NOT NULL,
    validity_days INTEGER NOT NULL DEFAULT 30 CHECK(validity_days > 0),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (plan_id) REFERENCES subscription_plans(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS quotation_template_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    variant_id INTEGER,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity > 0),
    unit_price_minor_units INTEGER NOT NULL CHECK(unit_price_minor_units >= 0),
    FOREIGN KEY (template_id) REFERENCES quotation_templates(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT,
    FOREIGN KEY (variant_id) REFERENCES product_variants(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_number TEXT UNIQUE NOT NULL,
    customer_id INTEGER NOT NULL,
    plan_id INTEGER NOT NULL,
    template_id INTEGER,
    status TEXT NOT NULL CHECK(status IN ('DRAFT', 'QUOTATION', 'CONFIRMED', 'ACTIVE', 'PAUSED', 'CLOSED')),
    start_date DATE NOT NULL,
    expiry_date DATE,
    quote_valid_until DATE,
    next_billing_date DATE,
    payment_terms TEXT NOT NULL DEFAULT 'NET_30',
    currency TEXT NOT NULL DEFAULT 'USD' CHECK(length(currency) = 3 AND currency = upper(currency)),
    auto_renew INTEGER NOT NULL DEFAULT 1 CHECK(auto_renew IN (0, 1)),
    created_by_user_id INTEGER,
    paused_at TIMESTAMP,
    closed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT,
    FOREIGN KEY (plan_id) REFERENCES subscription_plans(id) ON DELETE RESTRICT,
    FOREIGN KEY (template_id) REFERENCES quotation_templates(id) ON DELETE SET NULL,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS subscription_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    variant_id INTEGER,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity > 0),
    unit_price_minor_units INTEGER NOT NULL CHECK(unit_price_minor_units >= 0),
    tax_rate_basis_points INTEGER NOT NULL DEFAULT 0 CHECK(tax_rate_basis_points >= 0 AND tax_rate_basis_points <= 100000),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    FOREIGN KEY (subscription_id) REFERENCES subscriptions(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT,
    FOREIGN KEY (variant_id) REFERENCES product_variants(id) ON DELETE RESTRICT
);

-- 5. Invoicing & Tax Rules
CREATE TABLE IF NOT EXISTS tax_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    rate_basis_points INTEGER NOT NULL CHECK(rate_basis_points >= 0 AND rate_basis_points <= 100000),
    country_code TEXT NOT NULL,
    state_code TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT UNIQUE NOT NULL,
    subscription_id INTEGER NOT NULL,
    customer_id INTEGER NOT NULL,
    discount_rule_id INTEGER,
    status TEXT NOT NULL CHECK(status IN ('DRAFT', 'CONFIRMED', 'PAID', 'CANCELLED')),
    issue_date DATE NOT NULL,
    due_date DATE NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD' CHECK(length(currency) = 3 AND currency = upper(currency)),
    subtotal_minor_units INTEGER NOT NULL DEFAULT 0 CHECK(subtotal_minor_units >= 0),
    tax_amount_minor_units INTEGER NOT NULL DEFAULT 0 CHECK(tax_amount_minor_units >= 0),
    discount_amount_minor_units INTEGER NOT NULL DEFAULT 0 CHECK(discount_amount_minor_units >= 0),
    total_amount_minor_units INTEGER NOT NULL DEFAULT 0 CHECK(total_amount_minor_units >= 0),
    balance_due_minor_units INTEGER NOT NULL DEFAULT 0 CHECK(balance_due_minor_units >= 0 AND balance_due_minor_units <= total_amount_minor_units),
    billing_period_start DATE NOT NULL,
    billing_period_end DATE NOT NULL,
    idempotency_key TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (subscription_id) REFERENCES subscriptions(id) ON DELETE RESTRICT,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT,
    FOREIGN KEY (discount_rule_id) REFERENCES discount_rules(id) ON DELETE SET NULL,
    UNIQUE(subscription_id, billing_period_start, billing_period_end)
);

CREATE TABLE IF NOT EXISTS invoice_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    variant_id INTEGER,
    description TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity > 0),
    unit_price_minor_units INTEGER NOT NULL CHECK(unit_price_minor_units >= 0),
    discount_amount_minor_units INTEGER NOT NULL DEFAULT 0 CHECK(discount_amount_minor_units >= 0),
    tax_rate_basis_points INTEGER NOT NULL DEFAULT 0 CHECK(tax_rate_basis_points >= 0 AND tax_rate_basis_points <= 100000),
    tax_amount_minor_units INTEGER NOT NULL DEFAULT 0 CHECK(tax_amount_minor_units >= 0),
    line_total_minor_units INTEGER NOT NULL CHECK(line_total_minor_units >= 0),
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT,
    FOREIGN KEY (variant_id) REFERENCES product_variants(id) ON DELETE RESTRICT
);

-- 6. Discounts Engine & Concurrency-Protected Redemptions
CREATE TABLE IF NOT EXISTS discount_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    code TEXT UNIQUE NOT NULL,
    discount_type TEXT NOT NULL CHECK(discount_type IN ('FIXED_AMOUNT', 'PERCENTAGE')),
    value_minor_units_or_basis_points INTEGER NOT NULL CHECK(value_minor_units_or_basis_points > 0),
    scope TEXT NOT NULL CHECK(scope IN ('WHOLE_SUBSCRIPTION', 'SPECIFIC_PRODUCT')),
    target_product_id INTEGER,
    min_purchase_minor_units INTEGER NOT NULL DEFAULT 0 CHECK(min_purchase_minor_units >= 0),
    min_quantity INTEGER NOT NULL DEFAULT 0 CHECK(min_quantity >= 0),
    start_date DATE NOT NULL,
    end_date DATE,
    max_usage_count INTEGER CHECK(max_usage_count IS NULL OR max_usage_count > 0),
    current_usage_count INTEGER NOT NULL DEFAULT 0 CHECK(current_usage_count >= 0 AND (max_usage_count IS NULL OR current_usage_count <= max_usage_count)),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (target_product_id) REFERENCES products(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS subscription_discounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id INTEGER NOT NULL,
    discount_rule_id INTEGER NOT NULL,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (subscription_id) REFERENCES subscriptions(id) ON DELETE CASCADE,
    FOREIGN KEY (discount_rule_id) REFERENCES discount_rules(id) ON DELETE RESTRICT,
    UNIQUE(subscription_id, discount_rule_id)
);

CREATE TABLE IF NOT EXISTS discount_redemptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discount_rule_id INTEGER NOT NULL,
    subscription_id INTEGER NOT NULL,
    invoice_id INTEGER NOT NULL,
    amount_minor_units INTEGER NOT NULL CHECK(amount_minor_units > 0),
    redeemed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (discount_rule_id) REFERENCES discount_rules(id) ON DELETE RESTRICT,
    FOREIGN KEY (subscription_id) REFERENCES subscriptions(id) ON DELETE RESTRICT,
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
    UNIQUE(discount_rule_id, invoice_id)
);

-- 7. Payments & Accounts Receivable Reconciliation
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL,
    customer_id INTEGER NOT NULL,
    amount_minor_units INTEGER NOT NULL CHECK(amount_minor_units > 0),
    currency TEXT NOT NULL DEFAULT 'USD' CHECK(length(currency) = 3 AND currency = upper(currency)),
    payment_date DATE NOT NULL,
    payment_method TEXT NOT NULL CHECK(payment_method IN ('BANK_TRANSFER', 'CREDIT_CARD', 'GATEWAY', 'CHECK')),
    transaction_reference TEXT,
    notes TEXT,
    recorded_by_user_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE RESTRICT,
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE RESTRICT,
    FOREIGN KEY (recorded_by_user_id) REFERENCES users(id) ON DELETE RESTRICT
);

-- 8. Persistent Transactional Outbox with Worker Leases
CREATE TABLE IF NOT EXISTS outbox_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')) DEFAULT 'PENDING',
    scheduled_for TIMESTAMP NOT NULL,
    locked_by TEXT,
    locked_at TIMESTAMP,
    lease_expires_at TIMESTAMP,
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK(retry_count >= 0),
    max_retries INTEGER NOT NULL DEFAULT 5 CHECK(max_retries >= 0),
    last_error TEXT,
    idempotency_key TEXT UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 9. Strategic Indexes for Rapid Query Latency
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_customers_active ON customers(is_active);
CREATE INDEX IF NOT EXISTS idx_cust_members_user ON customer_members(user_id);
CREATE INDEX IF NOT EXISTS idx_cust_members_customer ON customer_members(customer_id);
CREATE INDEX IF NOT EXISTS idx_sessions_hash ON user_sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_subs_active_billing ON subscriptions(status, next_billing_date) WHERE status = 'ACTIVE';
CREATE INDEX IF NOT EXISTS idx_subs_billing_scan ON subscriptions(next_billing_date) WHERE status = 'ACTIVE';
CREATE INDEX IF NOT EXISTS idx_subs_customer ON subscriptions(customer_id);
CREATE INDEX IF NOT EXISTS idx_subs_plan ON subscriptions(plan_id, status);
CREATE INDEX IF NOT EXISTS idx_invoices_customer_status ON invoices(customer_id, status);
CREATE INDEX IF NOT EXISTS idx_invoices_due ON invoices(status, due_date) WHERE status = 'CONFIRMED';
CREATE INDEX IF NOT EXISTS idx_invoices_issue_date ON invoices(issue_date);
CREATE INDEX IF NOT EXISTS idx_invoices_due_date ON invoices(due_date);
CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);
CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date);
CREATE INDEX IF NOT EXISTS idx_discount_rules_code ON discount_rules(code);
CREATE INDEX IF NOT EXISTS idx_redemptions_invoice ON discount_redemptions(invoice_id);
CREATE INDEX IF NOT EXISTS idx_outbox_sched_status ON outbox_events(status, scheduled_for, lease_expires_at);