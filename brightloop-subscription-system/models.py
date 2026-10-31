from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="customer", index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "email": self.email,
                "role": self.role, "created_at": self.created_at.isoformat()}


class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, index=True)
    product_type = db.Column(db.String(80), nullable=False, default="Software")
    sales_price = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    cost_price = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    notes = db.Column(db.Text, default="")
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    variants = db.relationship("ProductVariant", backref="product", cascade="all, delete-orphan", lazy=True)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "product_type": self.product_type,
                "sales_price": float(self.sales_price), "cost_price": float(self.cost_price),
                "notes": self.notes or "", "active": self.active,
                "variants": [v.to_dict() for v in self.variants]}


class ProductVariant(db.Model):
    __tablename__ = "product_variants"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    price_adjustment = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    active = db.Column(db.Boolean, nullable=False, default=True)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "price_adjustment": float(self.price_adjustment), "active": self.active}


class TaxRule(db.Model):
    __tablename__ = "tax_rules"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    rate = db.Column(db.Numeric(7, 3), nullable=False, default=Decimal("0.000"))
    description = db.Column(db.String(255), default="")
    active = db.Column(db.Boolean, nullable=False, default=True)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "rate": float(self.rate),
                "description": self.description or "", "active": self.active}


class Plan(db.Model):
    __tablename__ = "plans"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    tax_rule_id = db.Column(db.Integer, db.ForeignKey("tax_rules.id"), nullable=True)
    price = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    frequency = db.Column(db.String(20), nullable=False, default="monthly")
    min_quantity = db.Column(db.Integer, nullable=False, default=1)
    available_from = db.Column(db.Date, nullable=True)
    available_until = db.Column(db.Date, nullable=True)
    auto_close = db.Column(db.Boolean, nullable=False, default=True)
    allow_early_close = db.Column(db.Boolean, nullable=False, default=True)
    allow_pause = db.Column(db.Boolean, nullable=False, default=True)
    allow_renew = db.Column(db.Boolean, nullable=False, default=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    product = db.relationship("Product")
    tax_rule = db.relationship("TaxRule")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "product_id": self.product_id,
                "product_name": self.product.name if self.product else "",
                "tax_rule_id": self.tax_rule_id, "tax_name": self.tax_rule.name if self.tax_rule else "No tax",
                "price": float(self.price), "frequency": self.frequency,
                "min_quantity": self.min_quantity,
                "available_from": self.available_from.isoformat() if self.available_from else None,
                "available_until": self.available_until.isoformat() if self.available_until else None,
                "auto_close": self.auto_close, "allow_early_close": self.allow_early_close,
                "allow_pause": self.allow_pause, "allow_renew": self.allow_renew, "active": self.active}


class QuoteTemplate(db.Model):
    __tablename__ = "quote_templates"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey("plans.id"), nullable=False)
    validity_days = db.Column(db.Integer, nullable=False, default=30)
    active = db.Column(db.Boolean, nullable=False, default=True)
    plan = db.relationship("Plan")
    lines = db.relationship("QuoteTemplateLine", backref="template", cascade="all, delete-orphan", lazy=True)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "plan_id": self.plan_id,
                "plan_name": self.plan.name if self.plan else "", "validity_days": self.validity_days,
                "active": self.active,
                "lines": [line.to_dict() for line in self.lines]}


class QuoteTemplateLine(db.Model):
    __tablename__ = "quote_template_lines"
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey("quote_templates.id", ondelete="CASCADE"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    tax_rule_id = db.Column(db.Integer, db.ForeignKey("tax_rules.id"), nullable=True)
    product = db.relationship("Product")
    tax_rule = db.relationship("TaxRule")

    def to_dict(self):
        return {"id": self.id, "product_id": self.product_id,
                "product_name": self.product.name if self.product else "",
                "quantity": self.quantity, "tax_rule_id": self.tax_rule_id}


class DiscountRule(db.Model):
    __tablename__ = "discount_rules"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    discount_type = db.Column(db.String(20), nullable=False)  # fixed | percentage
    value = db.Column(db.Numeric(12, 2), nullable=False)
    scope = db.Column(db.String(20), nullable=False, default="subscription")  # subscription | product
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=True)
    min_purchase = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    min_quantity = db.Column(db.Integer, nullable=False, default=1)
    starts_at = db.Column(db.Date, nullable=True)
    ends_at = db.Column(db.Date, nullable=True)
    usage_limit = db.Column(db.Integer, nullable=True)
    used_count = db.Column(db.Integer, nullable=False, default=0)
    active = db.Column(db.Boolean, nullable=False, default=True)
    product = db.relationship("Product")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "discount_type": self.discount_type,
                "value": float(self.value), "scope": self.scope, "product_id": self.product_id,
                "product_name": self.product.name if self.product else None,
                "min_purchase": float(self.min_purchase), "min_quantity": self.min_quantity,
                "starts_at": self.starts_at.isoformat() if self.starts_at else None,
                "ends_at": self.ends_at.isoformat() if self.ends_at else None,
                "usage_limit": self.usage_limit, "used_count": self.used_count, "active": self.active}


class Subscription(db.Model):
    __tablename__ = "subscriptions"
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("plans.id"), nullable=False, index=True)
    template_id = db.Column(db.Integer, db.ForeignKey("quote_templates.id"), nullable=True)
    discount_id = db.Column(db.Integer, db.ForeignKey("discount_rules.id"), nullable=True)
    quote_valid_until = db.Column(db.Date, nullable=True)
    start_date = db.Column(db.Date, nullable=False)
    expiry_date = db.Column(db.Date, nullable=True)
    payment_terms = db.Column(db.String(100), nullable=False, default="Net 15")
    status = db.Column(db.String(20), nullable=False, default="Draft", index=True)
    next_billing_date = db.Column(db.Date, nullable=True, index=True)
    paused_until = db.Column(db.Date, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    customer = db.relationship("User")
    plan = db.relationship("Plan")
    discount = db.relationship("DiscountRule")
    lines = db.relationship("SubscriptionLine", backref="subscription", cascade="all, delete-orphan", lazy=True)

    def to_dict(self, include_lines=True):
        result = {"id": self.id, "number": self.number, "customer_id": self.customer_id,
                 "customer_name": self.customer.name if self.customer else "",
                 "customer_email": self.customer.email if self.customer else "",
                 "plan_id": self.plan_id, "plan_name": self.plan.name if self.plan else "",
                 "template_id": self.template_id, "discount_id": self.discount_id,
                 "discount_name": self.discount.name if self.discount else None,
                 "quote_valid_until": self.quote_valid_until.isoformat() if self.quote_valid_until else None,
                 "start_date": self.start_date.isoformat() if self.start_date else None,
                 "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
                 "payment_terms": self.payment_terms, "status": self.status,
                 "next_billing_date": self.next_billing_date.isoformat() if self.next_billing_date else None,
                 "paused_until": self.paused_until.isoformat() if self.paused_until else None,
                 "created_at": self.created_at.isoformat()}
        if include_lines:
            result["lines"] = [line.to_dict() for line in self.lines]
        return result


class SubscriptionLine(db.Model):
    __tablename__ = "subscription_lines"
    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("product_variants.id"), nullable=True)
    description = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)
    tax_rule_id = db.Column(db.Integer, db.ForeignKey("tax_rules.id"), nullable=True)
    product = db.relationship("Product")
    variant = db.relationship("ProductVariant")
    tax_rule = db.relationship("TaxRule")

    def to_dict(self):
        unit_price = Decimal(str(self.unit_price))
        subtotal = (unit_price * self.quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        tax_rate = Decimal(str(self.tax_rule.rate)) if self.tax_rule and self.tax_rule.active else Decimal("0.000")
        tax_amount = (subtotal * tax_rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return {"id": self.id, "product_id": self.product_id, "product_name": self.product.name if self.product else self.description,
                "variant_id": self.variant_id, "variant_name": self.variant.name if self.variant else None,
                "description": self.description, "quantity": self.quantity,
                "unit_price": float(unit_price), "tax_rule_id": self.tax_rule_id,
                "tax_name": self.tax_rule.name if self.tax_rule else "No tax", "tax_rate": float(tax_rate),
                "line_subtotal": float(subtotal), "tax_amount": float(tax_amount),
                "line_total": float(subtotal + tax_amount)}


class Invoice(db.Model):
    __tablename__ = "invoices"
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey("subscriptions.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    billing_period_start = db.Column(db.Date, nullable=False)
    billing_period_end = db.Column(db.Date, nullable=False)
    issue_date = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="Draft", index=True)
    subtotal = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    tax_total = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    discount_total = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    total = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    subscription = db.relationship("Subscription")
    customer = db.relationship("User")
    lines = db.relationship("InvoiceLine", backref="invoice", cascade="all, delete-orphan", lazy=True)
    payments = db.relationship("Payment", backref="invoice", cascade="all, delete-orphan", lazy=True)
    __table_args__ = (db.UniqueConstraint("subscription_id", "billing_period_start", name="uq_invoice_subscription_period"),)

    @property
    def amount_paid(self):
        return sum((Decimal(str(p.amount)) for p in self.payments), Decimal("0.00"))

    @property
    def outstanding(self):
        return max(Decimal("0.00"), Decimal(str(self.total)) - self.amount_paid)

    @property
    def is_overdue(self):
        return self.status not in ("Paid", "Cancelled") and self.due_date < date.today() and self.outstanding > 0

    def to_dict(self, include_lines=False):
        result = {"id": self.id, "invoice_number": self.invoice_number,
                 "subscription_id": self.subscription_id,
                 "subscription_number": self.subscription.number if self.subscription else "",
                 "customer_id": self.customer_id, "customer_name": self.customer.name if self.customer else "",
                 "customer_email": self.customer.email if self.customer else "",
                 "billing_period_start": self.billing_period_start.isoformat(),
                 "billing_period_end": self.billing_period_end.isoformat(),
                 "issue_date": self.issue_date.isoformat(), "due_date": self.due_date.isoformat(),
                 "status": self.status, "subtotal": float(self.subtotal), "tax_total": float(self.tax_total),
                 "discount_total": float(self.discount_total), "total": float(self.total),
                 "amount_paid": float(self.amount_paid), "outstanding": float(self.outstanding),
                 "overdue": self.is_overdue, "notes": self.notes or ""}
        if include_lines:
            result["lines"] = [line.to_dict() for line in self.lines]
            result["payments"] = [p.to_dict() for p in self.payments]
        return result


class InvoiceLine(db.Model):
    __tablename__ = "invoice_lines"
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=True)
    description = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)
    tax_rate = db.Column(db.Numeric(7, 3), nullable=False, default=Decimal("0.000"))
    discount_amount = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0.00"))
    line_subtotal = db.Column(db.Numeric(12, 2), nullable=False)
    tax_amount = db.Column(db.Numeric(12, 2), nullable=False)
    line_total = db.Column(db.Numeric(12, 2), nullable=False)
    product = db.relationship("Product")

    def to_dict(self):
        return {"id": self.id, "product_id": self.product_id,
                "description": self.description, "quantity": self.quantity,
                "unit_price": float(self.unit_price), "tax_rate": float(self.tax_rate),
                "discount_amount": float(self.discount_amount),
                "line_subtotal": float(self.line_subtotal), "tax_amount": float(self.tax_amount),
                "line_total": float(self.line_total)}


class Payment(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False, index=True)
    method = db.Column(db.String(40), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    paid_at = db.Column(db.Date, nullable=False, default=date.today)
    note = db.Column(db.String(255), default="")
    reference = db.Column(db.String(120), default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {"id": self.id, "invoice_id": self.invoice_id,
                "invoice_number": self.invoice.invoice_number if self.invoice else "",
                "customer_name": self.invoice.customer.name if self.invoice and self.invoice.customer else "",
                "method": self.method, "amount": float(self.amount), "paid_at": self.paid_at.isoformat(),
                "note": self.note or "", "reference": self.reference or ""}
