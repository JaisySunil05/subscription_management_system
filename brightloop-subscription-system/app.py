import os
import re
import secrets
import smtplib
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from email.message import EmailMessage
from functools import wraps
from calendar import monthrange

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import Flask, jsonify, make_response, redirect, render_template, request, session, url_for
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy import func, or_, event, case
from sqlalchemy.engine import Engine
from sqlalchemy.orm import joinedload, selectinload
from werkzeug.security import generate_password_hash, check_password_hash

from models import (db, User, Product, ProductVariant, TaxRule, Plan, QuoteTemplate,
                    QuoteTemplateLine, DiscountRule, Subscription, SubscriptionLine,
                    Invoice, InvoiceLine, Payment)

load_dotenv()

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY", "dev-only-change-this-secret-key"),
    SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///brightloop.db"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "false").lower() == "true",
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)
db.init_app(app)


@event.listens_for(Engine, "connect")
def enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()
    except Exception:
        pass


# ----------------------------- common helpers -----------------------------

def api_error(message, status=400, details=None):
    payload = {"error": message}
    if details:
        payload["details"] = details
    return jsonify(payload), status


def json_body():
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def clean_text(value, max_len=255, required=False):
    value = str(value or "").strip()
    if required and not value:
        raise ValueError("This field is required.")
    if len(value) > max_len:
        raise ValueError(f"This field must be {max_len} characters or fewer.")
    return value


def parse_money(value, field="Amount", minimum=Decimal("0.00")):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < minimum:
            raise ValueError
        return number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be a valid number greater than or equal to {minimum}.")


def parse_int(value, field="Value", minimum=0, maximum=1000000):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a whole number.")
    if number < minimum or number > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}.")
    return number


def parse_date(value, field="Date", required=False):
    if not value:
        if required:
            raise ValueError(f"{field} is required.")
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ValueError(f"{field} must use YYYY-MM-DD format.")


def password_problem(password):
    if len(password) <= 8:
        return "Password must contain more than 8 characters."
    if not re.search(r"[A-Z]", password):
        return "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return "Password must contain at least one lowercase letter."
    if not re.search(r"[^A-Za-z0-9]", password):
        return "Password must contain at least one special character."
    return None


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    user = db.session.get(User, user_id)
    if not user or not user.is_active:
        session.clear()
        return None
    return user


def auth_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not get_current_user():
            return api_error("Please sign in to continue.", 401)
        return fn(*args, **kwargs)
    return wrapper


def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        @auth_required
        def wrapper(*args, **kwargs):
            user = get_current_user()
            if user.role not in roles:
                return api_error("You do not have permission to perform this action.", 403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def password_serializer():
    return URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="brightloop-password-reset")


def send_email(to_address, subject, body):
    """Send an email through the SMTP account configured in the environment."""
    server = os.getenv("MAIL_SERVER", "").strip()
    username = os.getenv("MAIL_USERNAME", "").strip()
    password = os.getenv("MAIL_PASSWORD", "").strip().replace(" ", "")
    sender = os.getenv("MAIL_DEFAULT_SENDER", "").strip() or username

    if not server:
        raise RuntimeError("Email delivery is not configured: MAIL_SERVER is empty.")

    # Gmail SMTP requires an authenticated account and a Google App Password
    # when using SMTP username/password authentication.
    if server.lower() == "smtp.gmail.com" and (not username or not password):
        raise RuntimeError("Gmail SMTP requires MAIL_USERNAME and a Google App Password in MAIL_PASSWORD.")

    if username and not password:
        raise RuntimeError("MAIL_PASSWORD is required when MAIL_USERNAME is configured.")

    try:
        port = int(os.getenv("MAIL_PORT", "587"))
    except ValueError as exc:
        raise RuntimeError("MAIL_PORT must be a valid port number.") from exc

    use_tls = os.getenv("MAIL_USE_TLS", "true").strip().lower() in ("1", "true", "yes", "on")
    if server.lower() == "smtp.gmail.com" and not use_tls:
        raise RuntimeError("Gmail SMTP must use TLS. Set MAIL_USE_TLS=true.")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = to_address
    message.set_content(body)

    # STARTTLS encrypts the connection before SMTP credentials are sent.
    with smtplib.SMTP(server, port, timeout=20) as smtp:
        smtp.ehlo()
        if use_tls:
            smtp.starttls()
            smtp.ehlo()
        if username:
            smtp.login(username, password)
        refused = smtp.send_message(message)
        if refused:
            raise RuntimeError("The SMTP server refused one or more email recipients.")

    app.logger.info("Email delivered through configured SMTP server.")
    return True


def next_period(day, frequency):
    if frequency == "daily":
        return day + timedelta(days=1)
    if frequency == "weekly":
        return day + timedelta(days=7)
    if frequency == "monthly":
        year = day.year + (day.month // 12)
        month = day.month % 12 + 1
        target_last_day = monthrange(year, month)[1]
        source_is_month_end = day.day == monthrange(day.year, day.month)[1]
        target_day = target_last_day if source_is_month_end else min(day.day, target_last_day)
        return date(year, month, target_day)
    if frequency == "yearly":
        try:
            return day.replace(year=day.year + 1)
        except ValueError:
            return day.replace(year=day.year + 1, day=28)
    raise ValueError("Unsupported billing frequency.")


def add_days_for_terms(issue_date, terms):
    match = re.fullmatch(r"\s*Net\s*(\d{1,3})\s*", terms or "")
    return issue_date + timedelta(days=int(match.group(1)) if match else 15)


def make_number(prefix, model):
    today = date.today().strftime("%Y%m%d")
    for _ in range(20):
        candidate = f"{prefix}-{today}-{secrets.token_hex(3).upper()}"
        exists = db.session.query(model.id).filter(
            getattr(model, "number" if model is Subscription else "invoice_number") == candidate
        ).first()
        if not exists:
            return candidate
    raise RuntimeError("Could not generate a unique reference number.")


def paginated_query(query):
    page = parse_int(request.args.get("page", 1), "Page", 1, 1000000)
    limit = min(parse_int(request.args.get("limit", 20), "Limit", 1, 100), 100)
    total = query.order_by(None).count()
    rows = query.offset((page - 1) * limit).limit(limit).all()
    return rows, {"page": page, "limit": limit, "total": total,
                  "pages": (total + limit - 1) // limit}


def active_discount(rule, on_date=None):
    on_date = on_date or date.today()
    return bool(rule and rule.active and
                (not rule.starts_at or rule.starts_at <= on_date) and
                (not rule.ends_at or rule.ends_at >= on_date) and
                (rule.usage_limit is None or rule.used_count < rule.usage_limit))


def calc_discount(rule, amount):
    amount = Decimal(str(amount))
    if rule.discount_type == "percentage":
        return min(amount, (amount * Decimal(str(rule.value)) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return min(amount, Decimal(str(rule.value)))


def create_subscription_from_payload(payload, customer, default_status="Draft", customer_portal=False):
    if customer_portal and any(payload.get(field) not in (None, "", [], {}) for field in
                               ("expiry_date", "template_id", "discount_id", "tax_rule_id", "extra_lines")):
        raise ValueError("Customer requests can choose only the plan, quantity, variant and start date. Billing settings are managed by Brightloop.")
    plan = db.session.get(Plan, parse_int(payload.get("plan_id"), "Plan", 1))
    if not plan or not plan.active or not plan.product or not plan.product.active:
        raise ValueError("Select an active plan with an active product.")
    today = date.today()
    start = parse_date(payload.get("start_date") or today.isoformat(), "Start date", True)
    if customer_portal and start < today:
        raise ValueError("A customer subscription cannot start in the past.")
    if plan.available_from and start < plan.available_from:
        raise ValueError("This plan is not available yet.")
    if plan.available_until and start > plan.available_until:
        raise ValueError("This plan is no longer available.")
    expiry = parse_date(payload.get("expiry_date"), "Expiry date")
    if expiry and expiry < start:
        raise ValueError("Expiry date cannot be earlier than the start date.")
    quantity = parse_int(payload.get("quantity", plan.min_quantity), "Quantity", plan.min_quantity, 100000)
    variant_id = payload.get("variant_id")
    variant = None
    if variant_id:
        variant = db.session.get(ProductVariant, parse_int(variant_id, "Variant", 1))
        if not variant or not variant.active or variant.product_id != plan.product_id:
            raise ValueError("The selected variant does not belong to this plan's active product options.")
    main_price = Decimal(str(plan.price)) + (Decimal(str(variant.price_adjustment)) if variant else Decimal("0.00"))
    tax_rule_id = payload.get("tax_rule_id") or plan.tax_rule_id
    tax = db.session.get(TaxRule, parse_int(tax_rule_id, "Tax rule", 1)) if tax_rule_id else None
    if tax_rule_id and (not tax or not tax.active):
        raise ValueError("Select a valid active tax rule.")
    terms = "Net 15" if customer_portal else (clean_text(payload.get("payment_terms", "Net 15"), 100) or "Net 15")
    template = None
    if not customer_portal and payload.get("template_id"):
        template = db.session.get(QuoteTemplate, parse_int(payload.get("template_id"), "Template", 1))
        if not template or not template.active or template.plan_id != plan.id:
            raise ValueError("The selected quotation template is not valid for this plan.")
    discount = None
    if not customer_portal and payload.get("discount_id"):
        discount = db.session.get(DiscountRule, parse_int(payload.get("discount_id"), "Discount", 1))
        if not active_discount(discount) or discount.scope != "subscription":
            raise ValueError("The selected subscription discount is not currently available.")

    sub = Subscription(number=make_number("SUB", Subscription), customer_id=customer.id,
                       plan_id=plan.id, template_id=template.id if template else None,
                       discount_id=discount.id if discount else None,
                       quote_valid_until=(date.today() + timedelta(days=template.validity_days)) if template else None,
                       start_date=start,
                       expiry_date=expiry, payment_terms=terms, status=default_status,
                       next_billing_date=start)
    db.session.add(sub)
    db.session.flush()
    main_description = plan.name + (f" — {variant.name}" if variant else "")
    db.session.add(SubscriptionLine(subscription_id=sub.id, product_id=plan.product_id,
                                    variant_id=variant.id if variant else None,
                                    description=main_description, quantity=quantity,
                                    unit_price=main_price, tax_rule_id=tax.id if tax else None))
    if template:
        for line in template.lines:
            product = line.product
            db.session.add(SubscriptionLine(subscription_id=sub.id, product_id=product.id,
                                            description=product.name, quantity=line.quantity,
                                            unit_price=product.sales_price,
                                            tax_rule_id=line.tax_rule_id))
    # Optional extra lines are accepted from trusted internal quote forms.
    extra_lines = payload.get("extra_lines", []) if not customer_portal else []
    if not isinstance(extra_lines, list) or len(extra_lines) > 30:
        raise ValueError("Additional product lines must be a list with no more than 30 entries.")
    for item in extra_lines:
        if not isinstance(item, dict):
            raise ValueError("Each additional product line must be an object.")
        product = db.session.get(Product, parse_int(item.get("product_id"), "Product", 1))
        if not product or not product.active:
            raise ValueError("An additional product is invalid or inactive.")
        qty = parse_int(item.get("quantity", 1), "Line quantity", 1, 100000)
        tax_id = item.get("tax_rule_id")
        tax_row = db.session.get(TaxRule, parse_int(tax_id, "Tax rule", 1)) if tax_id else None
        if tax_id and (not tax_row or not tax_row.active):
            raise ValueError("An additional line has an invalid tax rule.")
        db.session.add(SubscriptionLine(subscription_id=sub.id, product_id=product.id,
                                        description=product.name, quantity=qty,
                                        unit_price=product.sales_price, tax_rule_id=tax_row.id if tax_row else None))
    db.session.flush()
    return sub


def build_invoice(subscription, period_start, issue_date=None):
    issue_date = issue_date or date.today()
    if Invoice.query.filter_by(subscription_id=subscription.id, billing_period_start=period_start).first():
        return None
    period_end = next_period(period_start, subscription.plan.frequency) - timedelta(days=1)
    invoice = Invoice(invoice_number=make_number("INV", Invoice), subscription_id=subscription.id,
                      customer_id=subscription.customer_id, billing_period_start=period_start,
                      billing_period_end=period_end, issue_date=issue_date,
                      due_date=add_days_for_terms(issue_date, subscription.payment_terms),
                      status="Draft")
    db.session.add(invoice)
    db.session.flush()

    active_product_rules = DiscountRule.query.filter_by(active=True, scope="product").all()
    rows = []
    subtotal = Decimal("0.00")
    product_discount_total = Decimal("0.00")
    tax_total = Decimal("0.00")
    total_quantity = sum(line.quantity for line in subscription.lines)
    for line in subscription.lines:
        base = (Decimal(str(line.unit_price)) * line.quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        discount_amount = Decimal("0.00")
        for rule in active_product_rules:
            if rule.product_id != line.product_id or not active_discount(rule, issue_date):
                continue
            if base < Decimal(str(rule.min_purchase)) or line.quantity < rule.min_quantity:
                continue
            discount_amount = max(discount_amount, calc_discount(rule, base))
            rule.used_count += 1
            break
        net = max(Decimal("0.00"), base - discount_amount)
        rate = Decimal(str(line.tax_rule.rate)) if line.tax_rule and line.tax_rule.active else Decimal("0.00")
        tax_amount = (net * rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        line_total = net + tax_amount
        rows.append({"product_id": line.product_id, "description": line.description,
                     "quantity": line.quantity, "unit_price": line.unit_price,
                     "tax_rate": rate, "discount_amount": discount_amount,
                     "line_subtotal": net, "tax_amount": tax_amount, "line_total": line_total})
        subtotal += base
        product_discount_total += discount_amount
        tax_total += tax_amount

    subscription_discount = Decimal("0.00")
    rule = subscription.discount
    after_product_discount = subtotal - product_discount_total
    if active_discount(rule, issue_date) and rule.scope == "subscription":
        if after_product_discount >= Decimal(str(rule.min_purchase)) and total_quantity >= rule.min_quantity:
            subscription_discount = calc_discount(rule, after_product_discount)
            rule.used_count += 1

    # Allocate whole-subscription discount proportionally to lines, then recalculate tax.
    if subscription_discount > 0 and rows:
        basis_total = sum((row["line_subtotal"] for row in rows), Decimal("0.00"))
        allocated = Decimal("0.00")
        for idx, row in enumerate(rows):
            if idx == len(rows) - 1:
                share = subscription_discount - allocated
            else:
                share = (subscription_discount * row["line_subtotal"] / basis_total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if basis_total else Decimal("0.00")
                allocated += share
            row["discount_amount"] += share
            net = max(Decimal("0.00"), row["line_subtotal"] - share)
            row["line_subtotal"] = net
            row["tax_amount"] = (net * row["tax_rate"] / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            row["line_total"] = net + row["tax_amount"]
        tax_total = sum((row["tax_amount"] for row in rows), Decimal("0.00"))

    invoice.subtotal = subtotal
    invoice.discount_total = product_discount_total + subscription_discount
    invoice.tax_total = tax_total
    invoice.total = sum((row["line_total"] for row in rows), Decimal("0.00"))
    for row in rows:
        db.session.add(InvoiceLine(invoice_id=invoice.id, **row))
    return invoice


def update_invoice_payment_status(invoice):
    if invoice.status == "Cancelled":
        return
    if invoice.amount_paid >= Decimal(str(invoice.total)) and Decimal(str(invoice.total)) > 0:
        invoice.status = "Paid"
    elif invoice.amount_paid > 0 and invoice.status == "Draft":
        invoice.status = "Confirmed"
    elif invoice.status == "Paid":
        invoice.status = "Confirmed"


def run_billing_cycle():
    today = date.today()
    processed = 0
    closed = 0
    # A configured pause is temporary: restore the subscription when its resume date arrives.
    expired_pauses = Subscription.query.filter_by(status="Paused").filter(
        Subscription.paused_until <= today
    ).all()
    for paused in expired_pauses:
        paused.status = "Active"
        paused.paused_until = None
        if paused.next_billing_date and paused.next_billing_date < today:
            paused.next_billing_date = today
    subscriptions = Subscription.query.options(
        joinedload(Subscription.plan), joinedload(Subscription.discount),
        selectinload(Subscription.lines).joinedload(SubscriptionLine.tax_rule)
    ).filter_by(status="Active").filter(Subscription.next_billing_date <= today).all()
    for sub in subscriptions:
        if sub.expiry_date and sub.expiry_date < today and sub.plan.auto_close:
            sub.status = "Closed"
            sub.closed_at = datetime.utcnow()
            closed += 1
            continue
        if sub.paused_until and sub.paused_until > today:
            continue
        if sub.expiry_date and sub.expiry_date < today:
            continue
        billing_date = sub.next_billing_date or sub.start_date
        invoice = build_invoice(sub, billing_date, today)
        if invoice:
            sub.next_billing_date = next_period(billing_date, sub.plan.frequency)
            processed += 1
    db.session.commit()
    return {"created": processed, "auto_closed": closed}


@app.errorhandler(ValueError)
def handle_value_error(error):
    if request.path.startswith("/api/"):
        return api_error(str(error), 400)
    return str(error), 400


@app.errorhandler(404)
def handle_not_found(error):
    if request.path.startswith("/api/"):
        return api_error("The requested API endpoint was not found.", 404)
    return error


# ----------------------------- page and security -----------------------------

@app.before_request
def csrf_guard():
    if request.path.startswith("/api/") and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        token = session.get("csrf_token")
        supplied = request.headers.get("X-CSRF-Token", "")
        if not token or not secrets.compare_digest(token, supplied):
            return api_error("Your session token is missing or expired. Refresh the page and try again.", 403)


@app.get("/")
def index():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return render_template("index.html", csrf_token=session["csrf_token"])


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "service": "Brightloop Subscription Management", "date": date.today().isoformat()})


# -------------------------------- authentication -------------------------------

@app.post("/api/auth/register")
def register():
    data = json_body()
    try:
        name = clean_text(data.get("name"), 120, True)
        email = clean_text(data.get("email"), 255, True).lower()
        password = str(data.get("password") or "")
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise ValueError("Enter a valid email address.")
        problem = password_problem(password)
        if problem:
            raise ValueError(problem)
        if User.query.filter(func.lower(User.email) == email).first():
            raise ValueError("An account with this email already exists.")
        user = User(name=name, email=email, password_hash=generate_password_hash(password), role="customer")
        db.session.add(user)
        db.session.commit()
        session.clear()
        session["user_id"] = user.id
        session["csrf_token"] = secrets.token_urlsafe(32)
        return jsonify({"message": "Account created successfully.", "user": user.to_dict(), "csrf_token": session["csrf_token"]}), 201
    except ValueError as exc:
        db.session.rollback()
        return api_error(str(exc))


@app.post("/api/auth/login")
def login():
    data = json_body()
    email = str(data.get("email") or "").strip().lower()
    password = str(data.get("password") or "")
    user = User.query.filter(func.lower(User.email) == email).first()
    if not user or not user.is_active or not check_password_hash(user.password_hash, password):
        return api_error("Invalid email or password.", 401)
    session.clear()
    session["user_id"] = user.id
    session["csrf_token"] = secrets.token_urlsafe(32)
    return jsonify({"message": "Signed in successfully.", "user": user.to_dict(), "csrf_token": session["csrf_token"]})


@app.get("/api/auth/me")
@auth_required
def me():
    return jsonify({"user": get_current_user().to_dict(), "csrf_token": session.get("csrf_token")})


@app.post("/api/auth/logout")
@auth_required
def logout():
    session.clear()
    session["csrf_token"] = secrets.token_urlsafe(32)
    return jsonify({"message": "Signed out.", "csrf_token": session["csrf_token"]})


@app.post("/api/auth/forgot-password")
def forgot_password():
    data = json_body()
    email = str(data.get("email") or "").strip().lower()
    user = User.query.filter(func.lower(User.email) == email).first()
    # Same response whether the address exists or not, to avoid account enumeration.
    if user:
        token = password_serializer().dumps({"uid": user.id, "email": user.email})
        base_url = os.getenv("APP_BASE_URL", "").strip().rstrip("/") or request.url_root.rstrip("/")
        reset_url = f"{base_url}/?reset={token}"
        message_body = (
            f"Hello {user.name},\n\n"
            "We received a request to reset your Brightloop password.\n\n"
            f"Reset your password using this link (valid for 60 minutes):\n{reset_url}\n\n"
            "If you did not request a password reset, you can ignore this email. "
            "Your password will not change unless the link is used.\n\n"
            "Brightloop Support"
        )
        try:
            send_email(user.email, "Reset your Brightloop password", message_body)
        except Exception:
            # Do not expose whether an account exists, or put reset tokens in logs.
            app.logger.exception("Password reset email delivery failed. Check SMTP configuration.")
    return jsonify({"message": "If an account exists for that email, password reset instructions have been sent."})


@app.post("/api/auth/reset-password")
def reset_password():
    data = json_body()
    token = str(data.get("token") or "")
    password = str(data.get("password") or "")
    problem = password_problem(password)
    if problem:
        return api_error(problem)
    try:
        payload = password_serializer().loads(token, max_age=3600)
    except SignatureExpired:
        return api_error("This password reset link has expired. Request a new one.", 400)
    except BadSignature:
        return api_error("This password reset link is invalid.", 400)
    user = db.session.get(User, payload.get("uid"))
    if not user or user.email != payload.get("email"):
        return api_error("This password reset link is invalid.", 400)
    user.password_hash = generate_password_hash(password)
    db.session.commit()
    return jsonify({"message": "Password updated. You can now sign in with your new password."})


# -------------------------------- dashboard ------------------------------------

@app.get("/api/dashboard")
@auth_required
def dashboard():
    user = get_current_user()
    start = parse_date(request.args.get("start"), "Start date")
    end = parse_date(request.args.get("end"), "End date")

    sub_scope = Subscription.query
    invoice_scope = Invoice.query
    payment_scope = Payment.query.join(Invoice)
    if user.role == "customer":
        sub_scope = sub_scope.filter(Subscription.customer_id == user.id)
        invoice_scope = invoice_scope.filter(Invoice.customer_id == user.id)
        payment_scope = payment_scope.filter(Invoice.customer_id == user.id)

    active_count = sub_scope.filter(Subscription.status == "Active").count()
    payment_sums = db.session.query(
        Payment.invoice_id.label("invoice_id"),
        func.sum(Payment.amount).label("paid")
    ).group_by(Payment.invoice_id).subquery()
    invoice_balances = db.session.query(
        Invoice.id, Invoice.total, Invoice.status, Invoice.due_date,
        func.coalesce(payment_sums.c.paid, 0).label("paid")
    ).outerjoin(payment_sums, payment_sums.c.invoice_id == Invoice.id)
    if user.role == "customer":
        invoice_balances = invoice_balances.filter(Invoice.customer_id == user.id)
    invoice_balances = invoice_balances.filter(Invoice.status != "Cancelled")
    outstanding_expr = case(
        ((Invoice.total - func.coalesce(payment_sums.c.paid, 0)) > 0,
         Invoice.total - func.coalesce(payment_sums.c.paid, 0)),
        else_=0
    )
    outstanding = db.session.query(func.coalesce(func.sum(outstanding_expr), 0)).select_from(Invoice).outerjoin(
        payment_sums, payment_sums.c.invoice_id == Invoice.id
    ).filter(Invoice.status != "Cancelled")
    if user.role == "customer":
        outstanding = outstanding.filter(Invoice.customer_id == user.id)
    outstanding = outstanding.scalar() or 0
    overdue_count = invoice_balances.filter(
        Invoice.status.notin_(["Paid", "Cancelled"]), Invoice.due_date < date.today(),
        func.coalesce(payment_sums.c.paid, 0) < Invoice.total
    ).count()

    payment_query = payment_scope
    if start:
        payment_query = payment_query.filter(Payment.paid_at >= start)
    if end:
        payment_query = payment_query.filter(Payment.paid_at <= end)
    revenue = payment_query.with_entities(func.coalesce(func.sum(Payment.amount), 0)).scalar() or 0

    # Normalize recurring line value to a monthly equivalent using a grouped SQL query.
    recurring_query = db.session.query(
        Plan.frequency, func.coalesce(func.sum(SubscriptionLine.unit_price * SubscriptionLine.quantity), 0)
    ).join(Subscription, Subscription.id == SubscriptionLine.subscription_id).join(
        Plan, Plan.id == Subscription.plan_id
    ).filter(Subscription.status == "Active")
    if user.role == "customer":
        recurring_query = recurring_query.filter(Subscription.customer_id == user.id)
    mrr = Decimal("0.00")
    factors = {"daily": Decimal("365") / Decimal("12"), "weekly": Decimal("52") / Decimal("12"),
               "monthly": Decimal("1"), "yearly": Decimal("1") / Decimal("12")}
    for frequency, total_value in recurring_query.group_by(Plan.frequency).all():
        mrr += Decimal(str(total_value or 0)) * factors.get(frequency, Decimal("1"))

    months = []
    today = date.today()
    for offset in range(5, -1, -1):
        month_index = today.month - offset
        year = today.year
        while month_index <= 0:
            month_index += 12
            year -= 1
        month_start = date(year, month_index, 1)
        next_month = next_period(month_start, "monthly")
        amount = payment_scope.filter(Payment.paid_at >= month_start, Payment.paid_at < next_month).with_entities(
            func.coalesce(func.sum(Payment.amount), 0)
        ).scalar() or 0
        months.append({"label": month_start.strftime("%b"), "value": float(amount)})
    recent = invoice_scope.options(joinedload(Invoice.customer), joinedload(Invoice.subscription),
                                   selectinload(Invoice.payments)).order_by(Invoice.created_at.desc()).limit(6).all()
    return jsonify({"kpis": {"active_subscriptions": active_count,
                             "mrr": float(mrr.quantize(Decimal("0.01"))),
                             "revenue": float(revenue), "outstanding": float(outstanding),
                             "overdue_invoices": overdue_count},
                    "revenue_trend": months,
                    "recent_invoices": [inv.to_dict() for inv in recent]})


# ---------------------------------- products -----------------------------------

@app.get("/api/products")
@auth_required
def list_products():
    user = get_current_user()
    query = Product.query.options(selectinload(Product.variants))
    if user.role == "customer":
        query = query.filter_by(active=True)
    search = request.args.get("q", "").strip()
    if search:
        query = query.filter(Product.name.ilike(f"%{search}%"))
    rows, meta = paginated_query(query.order_by(Product.name))
    if user.role == "admin":
        items = [p.to_dict() for p in rows]
    else:
        items = [{"id": p.id, "name": p.name, "product_type": p.product_type,
                  "sales_price": float(p.sales_price), "notes": p.notes or "", "active": p.active,
                  "variants": [v.to_dict() for v in p.variants if v.active]} for p in rows]
    return jsonify({"items": items, "pagination": meta})


@app.post("/api/products")
@role_required("admin")
def create_product():
    data = json_body()
    try:
        name = clean_text(data.get("name"), 160, True)
        variants = data.get("variants", [])
        if not isinstance(variants, list) or len(variants) > 30:
            raise ValueError("Variants must be a list containing no more than 30 entries.")
        if any(not isinstance(item, dict) for item in variants):
            raise ValueError("Each variant must have a name and a price adjustment.")
        variant_names = [clean_text(item.get("name"), 120, True).casefold() for item in variants]
        if len(variant_names) != len(set(variant_names)):
            raise ValueError("Variant names must be unique within a product.")
        product = Product(name=name, product_type=clean_text(data.get("product_type", "Software"), 80, True),
                          sales_price=parse_money(data.get("sales_price"), "Sales price"),
                          cost_price=parse_money(data.get("cost_price", 0), "Cost price"),
                          notes=clean_text(data.get("notes"), 2000))
        db.session.add(product)
        db.session.flush()
        for item in variants:
            variant_name = clean_text(item.get("name"), 120, True)
            adjustment = parse_money(item.get("price_adjustment", 0), "Variant adjustment")
            db.session.add(ProductVariant(product_id=product.id, name=variant_name, price_adjustment=adjustment))
        db.session.commit()
        return jsonify({"item": product.to_dict()}), 201
    except ValueError as exc:
        db.session.rollback()
        return api_error(str(exc))


@app.put("/api/products/<int:product_id>")
@role_required("admin")
def update_product(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        return api_error("Product not found.", 404)
    data = json_body()
    try:
        product.name = clean_text(data.get("name", product.name), 160, True)
        product.product_type = clean_text(data.get("product_type", product.product_type), 80, True)
        product.sales_price = parse_money(data.get("sales_price", product.sales_price), "Sales price")
        product.cost_price = parse_money(data.get("cost_price", product.cost_price), "Cost price")
        product.notes = clean_text(data.get("notes", product.notes), 2000)
        if "active" in data:
            product.active = bool(data["active"])
        if "variants" in data:
            variants = data["variants"]
            if not isinstance(variants, list) or len(variants) > 30:
                raise ValueError("Variants must be a list containing no more than 30 entries.")
            if any(not isinstance(item, dict) for item in variants):
                raise ValueError("Each variant must have a name and a price adjustment.")
            normalized_variants = []
            for item in variants:
                normalized_variants.append({
                    "name": clean_text(item.get("name"), 120, True),
                    "price_adjustment": parse_money(item.get("price_adjustment", 0), "Variant adjustment")
                })
            names = [v["name"].casefold() for v in normalized_variants]
            if len(names) != len(set(names)):
                raise ValueError("Variant names must be unique within a product.")
            existing_variants = ProductVariant.query.filter_by(product_id=product.id, active=True).order_by(ProductVariant.id).all()
            existing_signature = [(v.name, Decimal(str(v.price_adjustment))) for v in existing_variants]
            new_signature = [(v["name"], v["price_adjustment"]) for v in normalized_variants]
            if existing_signature != new_signature:
                used_variant_ids = {row[0] for row in db.session.query(SubscriptionLine.variant_id).filter(
                    SubscriptionLine.variant_id.isnot(None),
                    SubscriptionLine.variant_id.in_([v.id for v in existing_variants] or [-1])
                ).all()}
                # Keep variants already referenced by historical subscriptions, but retire them from future selection.
                for old_variant in existing_variants:
                    if old_variant.id in used_variant_ids:
                        old_variant.active = False
                    else:
                        db.session.delete(old_variant)
                for item in normalized_variants:
                    db.session.add(ProductVariant(product_id=product.id, name=item["name"],
                        price_adjustment=item["price_adjustment"], active=True))
        db.session.commit()
        return jsonify({"item": product.to_dict()})
    except ValueError as exc:
        db.session.rollback()
        return api_error(str(exc))


# ---------------------------------- tax rules ----------------------------------

@app.get("/api/tax-rules")
@role_required("admin", "staff")
def list_tax_rules():
    return jsonify({"items": [t.to_dict() for t in TaxRule.query.order_by(TaxRule.name).all()]})


@app.post("/api/tax-rules")
@role_required("admin")
def create_tax_rule():
    data = json_body()
    try:
        name = clean_text(data.get("name"), 100, True)
        rate = Decimal(str(data.get("rate")))
        if not rate.is_finite() or rate < 0 or rate > 100:
            raise ValueError
        row = TaxRule(name=name, rate=rate.quantize(Decimal("0.001")),
                      description=clean_text(data.get("description"), 255))
        db.session.add(row)
        db.session.commit()
        return jsonify({"item": row.to_dict()}), 201
    except (ValueError, TypeError, InvalidOperation):
        db.session.rollback()
        return api_error("Tax rate must be a number between 0 and 100.")


@app.put("/api/tax-rules/<int:tax_id>")
@role_required("admin")
def update_tax_rule(tax_id):
    row = db.session.get(TaxRule, tax_id)
    if not row:
        return api_error("Tax rule not found.", 404)
    data = json_body()
    try:
        row.name = clean_text(data.get("name", row.name), 100, True)
        rate = Decimal(str(data.get("rate", row.rate)))
        if not rate.is_finite() or rate < 0 or rate > 100:
            raise ValueError
        row.rate = rate.quantize(Decimal("0.001"))
        row.description = clean_text(data.get("description", row.description), 255)
        row.active = bool(data.get("active", row.active))
        db.session.commit()
        return jsonify({"item": row.to_dict()})
    except (ValueError, TypeError, InvalidOperation):
        db.session.rollback()
        return api_error("Tax rate must be a number between 0 and 100.")


# ------------------------------------- plans -----------------------------------

@app.get("/api/plans")
@auth_required
def list_plans():
    query = Plan.query.options(joinedload(Plan.product), joinedload(Plan.tax_rule))
    user = get_current_user()
    if user.role == "customer":
        query = query.join(Product, Plan.product_id == Product.id).filter(Plan.active.is_(True), Product.active.is_(True))
    return jsonify({"items": [p.to_dict() for p in query.order_by(Plan.name).all()]})


@app.post("/api/plans")
@role_required("admin")
def create_plan():
    data = json_body()
    try:
        product = db.session.get(Product, parse_int(data.get("product_id"), "Product", 1))
        if not product or not product.active:
            raise ValueError("Select an active product for this plan.")
        frequency = clean_text(data.get("frequency"), 20, True).lower()
        if frequency not in ("daily", "weekly", "monthly", "yearly"):
            raise ValueError("Billing frequency must be daily, weekly, monthly or yearly.")
        min_qty = parse_int(data.get("min_quantity", 1), "Minimum quantity", 1, 100000)
        starts = parse_date(data.get("available_from"), "Available from")
        ends = parse_date(data.get("available_until"), "Available until")
        if starts and ends and ends < starts:
            raise ValueError("Availability end date cannot be earlier than its start date.")
        tax_id = data.get("tax_rule_id")
        tax_row = db.session.get(TaxRule, parse_int(tax_id, "Tax rule", 1)) if tax_id else None
        if tax_id and (not tax_row or not tax_row.active):
            raise ValueError("Select a valid active tax rule.")
        row = Plan(name=clean_text(data.get("name"), 160, True), product_id=product.id,
                   tax_rule_id=tax_row.id if tax_row else None,
                   price=parse_money(data.get("price", product.sales_price), "Plan price"),
                   frequency=frequency, min_quantity=min_qty, available_from=starts, available_until=ends,
                   auto_close=bool(data.get("auto_close", True)),
                   allow_early_close=bool(data.get("allow_early_close", True)),
                   allow_pause=bool(data.get("allow_pause", True)), allow_renew=bool(data.get("allow_renew", True)))
        db.session.add(row)
        db.session.commit()
        return jsonify({"item": row.to_dict()}), 201
    except ValueError as exc:
        db.session.rollback()
        return api_error(str(exc))


@app.put("/api/plans/<int:plan_id>")
@role_required("admin")
def update_plan(plan_id):
    row = db.session.get(Plan, plan_id)
    if not row:
        return api_error("Plan not found.", 404)
    data = json_body()
    try:
        product = db.session.get(Product, parse_int(data.get("product_id", row.product_id), "Product", 1))
        if not product:
            raise ValueError("Select a valid product.")
        frequency = clean_text(data.get("frequency", row.frequency), 20, True).lower()
        if frequency not in ("daily", "weekly", "monthly", "yearly"):
            raise ValueError("Unsupported billing frequency.")
        starts = parse_date(data.get("available_from", row.available_from.isoformat() if row.available_from else None), "Available from")
        ends = parse_date(data.get("available_until", row.available_until.isoformat() if row.available_until else None), "Available until")
        if starts and ends and ends < starts:
            raise ValueError("Availability end date cannot be earlier than its start date.")
        tax_id = data.get("tax_rule_id", row.tax_rule_id)
        tax_row = db.session.get(TaxRule, parse_int(tax_id, "Tax rule", 1)) if tax_id else None
        if tax_id and (not tax_row or not tax_row.active):
            raise ValueError("Select a valid active tax rule.")
        row.name = clean_text(data.get("name", row.name), 160, True)
        row.product_id = product.id
        row.tax_rule_id = tax_row.id if tax_row else None
        row.price = parse_money(data.get("price", row.price), "Plan price")
        row.frequency = frequency
        row.min_quantity = parse_int(data.get("min_quantity", row.min_quantity), "Minimum quantity", 1, 100000)
        row.available_from, row.available_until = starts, ends
        for field in ("auto_close", "allow_early_close", "allow_pause", "allow_renew", "active"):
            if field in data:
                setattr(row, field, bool(data[field]))
        db.session.commit()
        return jsonify({"item": row.to_dict()})
    except ValueError as exc:
        db.session.rollback()
        return api_error(str(exc))


# -------------------------------- quote templates ------------------------------

@app.get("/api/templates")
@role_required("admin", "staff")
def list_templates():
    templates = QuoteTemplate.query.options(joinedload(QuoteTemplate.plan), selectinload(QuoteTemplate.lines).joinedload(QuoteTemplateLine.product)).order_by(QuoteTemplate.name).all()
    return jsonify({"items": [t.to_dict() for t in templates]})


@app.post("/api/templates")
@role_required("admin")
def create_template():
    data = json_body()
    try:
        plan = db.session.get(Plan, parse_int(data.get("plan_id"), "Plan", 1))
        if not plan:
            raise ValueError("Select a valid plan.")
        validity = parse_int(data.get("validity_days", 30), "Validity days", 1, 365)
        line_items = data.get("lines", [])
        if not isinstance(line_items, list) or len(line_items) > 30:
            raise ValueError("Template lines must be a list with no more than 30 entries.")
        if any(not isinstance(item, dict) for item in line_items):
            raise ValueError("Each template line must be an object.")
        template = QuoteTemplate(name=clean_text(data.get("name"), 160, True),
                                 plan_id=plan.id, validity_days=validity)
        db.session.add(template)
        db.session.flush()
        for item in line_items:
            product = db.session.get(Product, parse_int(item.get("product_id"), "Product", 1))
            if not product:
                raise ValueError("A template product does not exist.")
            tax_id = item.get("tax_rule_id")
            tax_row = db.session.get(TaxRule, parse_int(tax_id, "Tax rule", 1)) if tax_id else None
            if tax_id and (not tax_row or not tax_row.active):
                raise ValueError("A template tax rule does not exist or is inactive.")
            db.session.add(QuoteTemplateLine(template_id=template.id, product_id=product.id,
                quantity=parse_int(item.get("quantity", 1), "Template quantity", 1, 100000),
                tax_rule_id=int(tax_id) if tax_id else None))
        db.session.commit()
        return jsonify({"item": template.to_dict()}), 201
    except ValueError as exc:
        db.session.rollback()
        return api_error(str(exc))


# ------------------------------------ customers --------------------------------

@app.get("/api/customers")
@role_required("admin", "staff")
def list_customers():
    search = request.args.get("q", "").strip()
    query = User.query.filter_by(role="customer", is_active=True)
    if search:
        query = query.filter(or_(User.name.ilike(f"%{search}%"), User.email.ilike(f"%{search}%")))
    rows, meta = paginated_query(query.order_by(User.name))
    return jsonify({"items": [u.to_dict() for u in rows], "pagination": meta})


# -------------------------------------- team -----------------------------------

@app.get("/api/team")
@role_required("admin")
def list_team():
    rows = User.query.filter(User.role.in_(["admin", "staff"])).order_by(User.created_at.desc()).all()
    return jsonify({"items": [u.to_dict() for u in rows]})


@app.post("/api/team")
@role_required("admin")
def create_staff():
    data = json_body()
    try:
        name = clean_text(data.get("name"), 120, True)
        email = clean_text(data.get("email"), 255, True).lower()
        password = str(data.get("password") or "")
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise ValueError("Enter a valid email address.")
        problem = password_problem(password)
        if problem:
            raise ValueError(problem)
        if User.query.filter(func.lower(User.email) == email).first():
            raise ValueError("An account with this email already exists.")
        user = User(name=name, email=email, password_hash=generate_password_hash(password), role="staff")
        db.session.add(user)
        db.session.commit()
        return jsonify({"item": user.to_dict()}), 201
    except ValueError as exc:
        db.session.rollback()
        return api_error(str(exc))


# ----------------------------------- discounts ---------------------------------

@app.get("/api/discounts")
@role_required("admin", "staff")
def list_discounts():
    rows = DiscountRule.query.options(joinedload(DiscountRule.product)).order_by(DiscountRule.name).all()
    return jsonify({"items": [d.to_dict() for d in rows]})


@app.post("/api/discounts")
@role_required("admin")
def create_discount():
    data = json_body()
    try:
        dtype = clean_text(data.get("discount_type"), 20, True).lower()
        if dtype not in ("fixed", "percentage"):
            raise ValueError("Discount type must be fixed or percentage.")
        value = parse_money(data.get("value"), "Discount value", Decimal("0.01"))
        if dtype == "percentage" and value > 100:
            raise ValueError("Percentage discount cannot exceed 100%.")
        scope = clean_text(data.get("scope", "subscription"), 20, True).lower()
        if scope not in ("subscription", "product"):
            raise ValueError("Discount scope must be subscription or product.")
        product_id = None
        if scope == "product":
            product = db.session.get(Product, parse_int(data.get("product_id"), "Product", 1))
            if not product:
                raise ValueError("Select a product for this product discount.")
            product_id = product.id
        starts = parse_date(data.get("starts_at"), "Start date")
        ends = parse_date(data.get("ends_at"), "End date")
        if starts and ends and ends < starts:
            raise ValueError("Discount end date cannot be earlier than its start date.")
        usage_limit = data.get("usage_limit")
        usage_limit = parse_int(usage_limit, "Usage limit", 1, 10000000) if usage_limit not in (None, "") else None
        row = DiscountRule(name=clean_text(data.get("name"), 160, True), discount_type=dtype,
                           value=value, scope=scope, product_id=product_id,
                           min_purchase=parse_money(data.get("min_purchase", 0), "Minimum purchase"),
                           min_quantity=parse_int(data.get("min_quantity", 1), "Minimum quantity", 1, 100000),
                           starts_at=starts, ends_at=ends, usage_limit=usage_limit)
        db.session.add(row)
        db.session.commit()
        return jsonify({"item": row.to_dict()}), 201
    except ValueError as exc:
        db.session.rollback()
        return api_error(str(exc))


@app.put("/api/discounts/<int:discount_id>")
@role_required("admin")
def update_discount(discount_id):
    row = db.session.get(DiscountRule, discount_id)
    if not row:
        return api_error("Discount not found.", 404)
    data = json_body()
    try:
        row.active = bool(data.get("active", row.active))
        row.name = clean_text(data.get("name", row.name), 160, True)
        db.session.commit()
        return jsonify({"item": row.to_dict()})
    except ValueError as exc:
        db.session.rollback()
        return api_error(str(exc))


# -------------------------------- subscriptions --------------------------------

@app.get("/api/subscriptions")
@auth_required
def list_subscriptions():
    user = get_current_user()
    query = Subscription.query
    if user.role == "customer":
        query = query.filter_by(customer_id=user.id)
    status = request.args.get("status", "").strip()
    search = request.args.get("q", "").strip()
    if status:
        query = query.filter(Subscription.status == status)
    if search:
        query = query.join(User, Subscription.customer_id == User.id).filter(
            or_(Subscription.number.ilike(f"%{search}%"), User.name.ilike(f"%{search}%"), User.email.ilike(f"%{search}%")))
    query = query.options(joinedload(Subscription.customer), joinedload(Subscription.plan),
                          joinedload(Subscription.discount),
                          selectinload(Subscription.lines).joinedload(SubscriptionLine.product),
                          selectinload(Subscription.lines).joinedload(SubscriptionLine.variant),
                          selectinload(Subscription.lines).joinedload(SubscriptionLine.tax_rule))
    rows, meta = paginated_query(query.order_by(Subscription.created_at.desc()))
    return jsonify({"items": [s.to_dict() for s in rows], "pagination": meta})


@app.post("/api/subscriptions")
@role_required("admin", "staff")
def create_subscription():
    data = json_body()
    try:
        customer = db.session.get(User, parse_int(data.get("customer_id"), "Customer", 1))
        if not customer or customer.role != "customer" or not customer.is_active:
            raise ValueError("Select an active customer account.")
        sub = create_subscription_from_payload(data, customer, "Draft")
        db.session.commit()
        return jsonify({"item": sub.to_dict()}), 201
    except ValueError as exc:
        db.session.rollback()
        return api_error(str(exc))


@app.post("/api/portal/subscriptions")
@role_required("customer")
def portal_create_subscription():
    try:
        sub = create_subscription_from_payload(json_body(), get_current_user(), "Quotation", customer_portal=True)
        db.session.commit()
        return jsonify({"item": sub.to_dict(), "message": "Your subscription request has been submitted."}), 201
    except ValueError as exc:
        db.session.rollback()
        return api_error(str(exc))


@app.patch("/api/subscriptions/<int:subscription_id>")
@auth_required
def update_subscription(subscription_id):
    sub = db.session.get(Subscription, subscription_id)
    if not sub:
        return api_error("Subscription not found.", 404)
    user = get_current_user()
    if user.role == "customer" and sub.customer_id != user.id:
        return api_error("You can only access your own subscriptions.", 403)
    data = json_body()
    action = str(data.get("action") or "").lower()
    try:
        if user.role == "customer":
            if action == "close":
                if sub.status != "Active" or not sub.plan.allow_early_close:
                    raise ValueError("This plan does not allow early closure.")
                sub.status = "Closed"
                sub.closed_at = datetime.utcnow()
            elif action == "pause":
                if sub.status != "Active" or not sub.plan.allow_pause:
                    raise ValueError("This plan does not allow pausing.")
                until = parse_date(data.get("paused_until"), "Resume date", True)
                if until <= date.today():
                    raise ValueError("Resume date must be in the future.")
                sub.status = "Paused"
                sub.paused_until = until
            elif action == "resume":
                if sub.status != "Paused":
                    raise ValueError("Only paused subscriptions can be resumed.")
                sub.status = "Active"
                sub.paused_until = None
                if sub.next_billing_date and sub.next_billing_date < date.today():
                    sub.next_billing_date = date.today()
            else:
                raise ValueError("Unsupported customer action.")
        else:
            if action == "transition":
                target = clean_text(data.get("status"), 20, True).title()
                allowed = {"Draft": ["Quotation"], "Quotation": ["Confirmed", "Draft"],
                           "Confirmed": ["Active", "Closed"], "Active": ["Paused", "Closed"],
                           "Paused": ["Active", "Closed"]}
                if target not in allowed.get(sub.status, []):
                    raise ValueError(f"Cannot move a {sub.status} subscription to {target}.")
                if target == "Confirmed" and sub.quote_valid_until and sub.quote_valid_until < date.today():
                    raise ValueError("This quotation has expired. Create a new quotation to continue.")
                if target == "Closed" and not sub.plan.allow_early_close and not (sub.expiry_date and sub.expiry_date <= date.today()):
                    raise ValueError("This plan does not allow early closure.")
                if target == "Paused" and not sub.plan.allow_pause:
                    raise ValueError("This plan does not allow pausing.")
                sub.status = target
                if target == "Active" and not sub.next_billing_date:
                    sub.next_billing_date = max(sub.start_date, date.today())
                if target == "Closed":
                    sub.closed_at = datetime.utcnow()
                if target != "Paused":
                    sub.paused_until = None
            elif action == "set_discount":
                discount_id = data.get("discount_id")
                if discount_id:
                    rule = db.session.get(DiscountRule, parse_int(discount_id, "Discount", 1))
                    if not active_discount(rule) or rule.scope != "subscription":
                        raise ValueError("Select a currently active subscription discount.")
                    sub.discount_id = rule.id
                else:
                    sub.discount_id = None
            elif action == "renew":
                if not sub.plan.allow_renew:
                    raise ValueError("This plan does not allow renewal.")
                renewed = Subscription(number=make_number("SUB", Subscription), customer_id=sub.customer_id,
                    plan_id=sub.plan_id, start_date=date.today(), expiry_date=None,
                    payment_terms=sub.payment_terms, status="Confirmed", next_billing_date=date.today(),
                    discount_id=sub.discount_id)
                db.session.add(renewed)
                db.session.flush()
                for line in sub.lines:
                    db.session.add(SubscriptionLine(subscription_id=renewed.id, product_id=line.product_id,
                        variant_id=line.variant_id, description=line.description, quantity=line.quantity,
                        unit_price=line.unit_price, tax_rule_id=line.tax_rule_id))
                db.session.commit()
                return jsonify({"item": renewed.to_dict(), "message": "Renewal created as a new confirmed subscription."})
            else:
                raise ValueError("Unsupported subscription action.")
        db.session.commit()
        return jsonify({"item": sub.to_dict()})
    except ValueError as exc:
        db.session.rollback()
        return api_error(str(exc))


# ------------------------------------- invoices --------------------------------

@app.get("/api/invoices")
@auth_required
def list_invoices():
    user = get_current_user()
    query = Invoice.query
    if user.role == "customer":
        query = query.filter_by(customer_id=user.id)
    status = request.args.get("status", "").strip()
    search = request.args.get("q", "").strip()
    if status:
        query = query.filter(Invoice.status == status)
    if search:
        query = query.join(User, Invoice.customer_id == User.id).filter(
            or_(Invoice.invoice_number.ilike(f"%{search}%"), User.name.ilike(f"%{search}%")))
    overdue = request.args.get("overdue")
    if overdue == "true":
        query = query.filter(Invoice.status.notin_(["Paid", "Cancelled"]), Invoice.due_date < date.today())
    query = query.options(joinedload(Invoice.customer), joinedload(Invoice.subscription), selectinload(Invoice.payments))
    rows, meta = paginated_query(query.order_by(Invoice.created_at.desc()))
    return jsonify({"items": [inv.to_dict() for inv in rows], "pagination": meta})


@app.get("/api/invoices/<int:invoice_id>")
@auth_required
def get_invoice(invoice_id):
    inv = db.session.get(Invoice, invoice_id)
    if not inv:
        return api_error("Invoice not found.", 404)
    user = get_current_user()
    if user.role == "customer" and inv.customer_id != user.id:
        return api_error("You can only access your own invoices.", 403)
    inv = Invoice.query.options(joinedload(Invoice.customer), joinedload(Invoice.subscription),
                                selectinload(Invoice.lines), selectinload(Invoice.payments)).filter_by(id=invoice_id).first()
    return jsonify({"item": inv.to_dict(include_lines=True)})


@app.post("/api/billing/run")
@role_required("admin", "staff")
def run_billing():
    result = run_billing_cycle()
    return jsonify({"message": "Billing cycle completed.", **result})


@app.post("/api/subscriptions/<int:subscription_id>/bill")
@role_required("admin", "staff")
def bill_one_subscription(subscription_id):
    sub = db.session.get(Subscription, subscription_id)
    if not sub:
        return api_error("Subscription not found.", 404)
    if sub.status != "Active":
        return api_error("Only active subscriptions can be billed.")
    billing_date = sub.next_billing_date or sub.start_date
    if billing_date > date.today():
        return api_error("This subscription is not due for billing yet.")
    invoice = build_invoice(sub, billing_date)
    if not invoice:
        return api_error("An invoice already exists for this billing period.", 409)
    sub.next_billing_date = next_period(billing_date, sub.plan.frequency)
    db.session.commit()
    return jsonify({"item": invoice.to_dict(include_lines=True)}), 201


@app.post("/api/invoices/<int:invoice_id>/action")
@role_required("admin", "staff")
def invoice_action(invoice_id):
    inv = db.session.get(Invoice, invoice_id)
    if not inv:
        return api_error("Invoice not found.", 404)
    action = str(json_body().get("action") or "").lower()
    if action == "confirm":
        if inv.status != "Draft":
            return api_error("Only draft invoices can be confirmed.")
        inv.status = "Confirmed"
        db.session.commit()
        return jsonify({"item": inv.to_dict()})
    if action == "cancel":
        if inv.status == "Paid":
            return api_error("A paid invoice cannot be cancelled.")
        inv.status = "Cancelled"
        db.session.commit()
        return jsonify({"item": inv.to_dict()})
    if action == "send":
        if inv.status in ("Draft", "Cancelled"):
            return api_error("Confirm the invoice before sending it.")
        body = (f"Hello {inv.customer.name},\n\nYour Brightloop invoice {inv.invoice_number} is ready.\n"
                f"Total: INR {inv.total}\nDue date: {inv.due_date.isoformat()}\n\nThank you.")
        try:
            sent = send_email(inv.customer.email, f"Brightloop invoice {inv.invoice_number}", body)
            return jsonify({"message": "Invoice email sent." if sent else "SMTP is not configured; invoice details were logged in development mode."})
        except Exception:
            app.logger.exception("Invoice email failed")
            return api_error("The invoice email could not be sent. Check SMTP configuration.", 502)
    return api_error("Unsupported invoice action.")


# -------------------------------------- payments -------------------------------

@app.get("/api/payments")
@role_required("admin", "staff")
def list_payments():
    query = Payment.query.join(Invoice).options(joinedload(Payment.invoice).joinedload(Invoice.customer))
    start = parse_date(request.args.get("start"), "Start date")
    end = parse_date(request.args.get("end"), "End date")
    if start:
        query = query.filter(Payment.paid_at >= start)
    if end:
        query = query.filter(Payment.paid_at <= end)
    rows, meta = paginated_query(query.order_by(Payment.paid_at.desc(), Payment.id.desc()))
    return jsonify({"items": [p.to_dict() for p in rows], "pagination": meta})


@app.post("/api/invoices/<int:invoice_id>/payments")
@role_required("admin", "staff")
def record_payment(invoice_id):
    inv = db.session.get(Invoice, invoice_id)
    if not inv:
        return api_error("Invoice not found.", 404)
    if inv.status in ("Draft", "Cancelled"):
        return api_error("Confirm the invoice before recording a payment.")
    data = json_body()
    try:
        amount = parse_money(data.get("amount"), "Payment amount", Decimal("0.01"))
        if amount > inv.outstanding:
            raise ValueError(f"Payment exceeds the outstanding amount of INR {inv.outstanding}.")
        method = clean_text(data.get("method"), 40, True)
        if method not in ("Bank transfer", "UPI", "Card", "Cash", "Cheque", "Other"):
            raise ValueError("Select a supported payment method.")
        paid_at = parse_date(data.get("paid_at") or date.today().isoformat(), "Payment date", True)
        payment = Payment(invoice_id=inv.id, method=method, amount=amount, paid_at=paid_at,
                          note=clean_text(data.get("note"), 255), reference=clean_text(data.get("reference"), 120))
        db.session.add(payment)
        db.session.flush()
        update_invoice_payment_status(inv)
        db.session.commit()
        return jsonify({"item": payment.to_dict(), "invoice": inv.to_dict()}), 201
    except ValueError as exc:
        db.session.rollback()
        return api_error(str(exc))


# -------------------------------------- reports --------------------------------

@app.get("/api/reports")
@role_required("admin", "staff")
def reports():
    start = parse_date(request.args.get("start"), "Start date")
    end = parse_date(request.args.get("end"), "End date")
    payment_query = Payment.query
    payment_sum = db.session.query(
        Payment.invoice_id.label("invoice_id"), func.sum(Payment.amount).label("paid")
    ).group_by(Payment.invoice_id).subquery()
    invoice_query = db.session.query(
        Invoice.id, Invoice.total, Invoice.status, Invoice.due_date,
        func.coalesce(payment_sum.c.paid, 0).label("paid")
    ).outerjoin(payment_sum, payment_sum.c.invoice_id == Invoice.id).filter(Invoice.status != "Cancelled")
    if start:
        invoice_query = invoice_query.filter(Invoice.issue_date >= start)
        payment_query = payment_query.filter(Payment.paid_at >= start)
    if end:
        invoice_query = invoice_query.filter(Invoice.issue_date <= end)
        payment_query = payment_query.filter(Payment.paid_at <= end)

    invoiced = invoice_query.with_entities(func.coalesce(func.sum(Invoice.total), 0)).scalar() or 0
    outstanding_expr = case(
        ((Invoice.total - func.coalesce(payment_sum.c.paid, 0)) > 0,
         Invoice.total - func.coalesce(payment_sum.c.paid, 0)),
        else_=0
    )
    base_balance_query = db.session.query(
        func.coalesce(func.sum(outstanding_expr), 0)
    ).select_from(Invoice).outerjoin(payment_sum, payment_sum.c.invoice_id == Invoice.id).filter(
        Invoice.status != "Cancelled"
    )
    overdue_expr = case(
        ((Invoice.due_date < date.today()) &
         (Invoice.status.notin_(["Paid", "Cancelled"])) &
         (func.coalesce(payment_sum.c.paid, 0) < Invoice.total), outstanding_expr),
        else_=0
    )
    overdue_query = db.session.query(func.coalesce(func.sum(overdue_expr), 0)).select_from(Invoice).outerjoin(
        payment_sum, payment_sum.c.invoice_id == Invoice.id
    ).filter(Invoice.status != "Cancelled")
    if start:
        base_balance_query = base_balance_query.filter(Invoice.issue_date >= start)
        overdue_query = overdue_query.filter(Invoice.issue_date >= start)
    if end:
        base_balance_query = base_balance_query.filter(Invoice.issue_date <= end)
        overdue_query = overdue_query.filter(Invoice.issue_date <= end)
    collected = payment_query.with_entities(func.coalesce(func.sum(Payment.amount), 0)).scalar() or 0
    outstanding = base_balance_query.scalar() or 0
    overdue_total = overdue_query.scalar() or 0
    invoice_count = invoice_query.with_entities(func.count(Invoice.id)).scalar() or 0
    latest_query = Invoice.query.filter(Invoice.status != "Cancelled")
    if start:
        latest_query = latest_query.filter(Invoice.issue_date >= start)
    if end:
        latest_query = latest_query.filter(Invoice.issue_date <= end)
    latest = latest_query.options(joinedload(Invoice.customer), joinedload(Invoice.subscription),
                                  selectinload(Invoice.payments)).order_by(Invoice.issue_date.desc(), Invoice.id.desc()).limit(100).all()
    return jsonify({"summary": {"invoiced": float(invoiced), "collected": float(collected),
                                "outstanding": float(outstanding), "overdue": float(overdue_total),
                                "invoice_count": invoice_count},
                    "invoices": [i.to_dict() for i in latest]})


# -------------------------------------- seed data ------------------------------

def seed_data():
    seed_demo = os.getenv("SEED_DEMO_DATA", "true").lower() == "true"
    # Keep the advertised demo admin credentials synchronized on every startup.
    # Find by email (case-insensitive) so an older seeded account cannot retain
    # a stale password and cause the login page to reject the demo credentials.
    admin_email = os.getenv("SEED_ADMIN_EMAIL", "admin@brightloop.test").strip().lower()
    admin_password = os.getenv("SEED_ADMIN_PASSWORD", "ChangeMe@12345")
    admin = User.query.filter(func.lower(User.email) == admin_email).first()

    if not admin:
        admin = User(
            name="Brightloop Admin",
            email=admin_email,
            password_hash=generate_password_hash(admin_password),
            role="admin",
            is_active=True,
        )
        db.session.add(admin)
    else:
        admin.password_hash = generate_password_hash(admin_password)
        admin.role = "admin"
        admin.is_active = True
    if seed_demo and Product.query.count() == 0:
        crm = Product(name="Brightloop CRM", product_type="Business Software",
                      sales_price=Decimal("2499.00"), cost_price=Decimal("700.00"),
                      notes="Customer relationship management platform.")
        analytics = Product(name="Analytics Add-on", product_type="Add-on",
                            sales_price=Decimal("599.00"), cost_price=Decimal("150.00"),
                            notes="Advanced analytics and reporting.")
        support = Product(name="Priority Support", product_type="Service",
                          sales_price=Decimal("399.00"), cost_price=Decimal("100.00"),
                          notes="Priority customer support.")
        db.session.add_all([crm, analytics, support])
        db.session.flush()
        db.session.add_all([
            ProductVariant(product_id=crm.id, name="Standard", price_adjustment=Decimal("0.00")),
            ProductVariant(product_id=crm.id, name="Odoo brand", price_adjustment=Decimal("560.00")),
            ProductVariant(product_id=crm.id, name="Enterprise", price_adjustment=Decimal("1500.00")),
        ])
        gst = TaxRule(name="GST 18%", rate=Decimal("18.000"), description="Example GST rule")
        db.session.add(gst)
        db.session.flush()
        monthly = Plan(name="CRM Monthly", product_id=crm.id, tax_rule_id=gst.id, price=Decimal("2499.00"),
                       frequency="monthly", min_quantity=1, auto_close=True, allow_early_close=True,
                       allow_pause=True, allow_renew=True)
        annual = Plan(name="CRM Annual", product_id=crm.id, tax_rule_id=gst.id, price=Decimal("24990.00"),
                      frequency="yearly", min_quantity=5, auto_close=True, allow_early_close=False,
                      allow_pause=True, allow_renew=True)
        db.session.add_all([monthly, annual])
        db.session.flush()
        db.session.add_all([
            QuoteTemplate(name="Small Business Starter", plan_id=monthly.id, validity_days=30),
            QuoteTemplate(name="Enterprise Annual Offer", plan_id=annual.id, validity_days=45),
        ])
        db.session.flush()
        templates = QuoteTemplate.query.all()
        db.session.add(QuoteTemplateLine(template_id=templates[0].id, product_id=analytics.id, quantity=1, tax_rule_id=gst.id))
        db.session.add(QuoteTemplateLine(template_id=templates[1].id, product_id=support.id, quantity=2, tax_rule_id=gst.id))
        db.session.add(DiscountRule(name="Welcome 10%", discount_type="percentage", value=Decimal("10.00"),
                                    scope="subscription", min_purchase=Decimal("1000.00"), min_quantity=1,
                                    starts_at=date.today() - timedelta(days=30), ends_at=date.today() + timedelta(days=365),
                                    usage_limit=100))
        db.session.flush()
    if seed_demo:
        if not User.query.filter_by(role="staff").first():
            db.session.add(User(name="Demo Staff", email="staff@brightloop.test",
                                password_hash=generate_password_hash("Staff@12345"), role="staff"))
        if not User.query.filter_by(role="customer").first():
            db.session.add(User(name="Aarav Traders", email="customer@brightloop.test",
                                password_hash=generate_password_hash("Customer@12345"), role="customer"))
        db.session.flush()
        demo_customer = User.query.filter_by(email="customer@brightloop.test").first()
        if demo_customer and Subscription.query.count() == 0:
            plan = Plan.query.filter_by(name="CRM Monthly").first()
            if plan:
                gst = TaxRule.query.filter_by(name="GST 18%").first()
                variant = ProductVariant.query.filter_by(name="Standard", product_id=plan.product_id).first()
                sub = Subscription(number=make_number("SUB", Subscription), customer_id=demo_customer.id,
                                   plan_id=plan.id, start_date=date.today() - timedelta(days=5),
                                   payment_terms="Net 15", status="Active",
                                   next_billing_date=date.today() - timedelta(days=1))
                db.session.add(sub)
                db.session.flush()
                db.session.add(SubscriptionLine(subscription_id=sub.id, product_id=plan.product_id,
                    variant_id=variant.id if variant else None, description="CRM Monthly — Standard", quantity=1,
                    unit_price=plan.price, tax_rule_id=gst.id if gst else None))
        db.session.flush()
    db.session.commit()


def start_scheduler():
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(lambda: run_billing_cycle_with_context(), "cron", hour=1, minute=0,
                      id="daily-billing", replace_existing=True)
    scheduler.start()
    return scheduler


def run_billing_cycle_with_context():
    with app.app_context():
        try:
            run_billing_cycle()
        except Exception:
            db.session.rollback()
            app.logger.exception("Scheduled billing run failed")


with app.app_context():
    db.create_all()
    seed_data()


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    scheduler = None
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        scheduler = start_scheduler()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=debug)
