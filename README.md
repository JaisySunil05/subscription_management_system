# subscription_management_system
# Brightloop — Subscription Management System

A database-backed subscription and recurring billing application built from the supplied Brightloop Software problem statement.

## 1. Technology stack

### Frontend
- HTML5 — page structure and forms (`templates/index.html`)
- CSS3 — responsive layout and styling (`static/css/styles.css`)
- Vanilla JavaScript — navigation, API calls, tables, forms, filters and dynamic page rendering (`static/js/app.js`)

### Backend
- Python 3.10+
- Flask — REST API and application server
- Flask-SQLAlchemy / SQLAlchemy — database models and queries
- SQLite by default — persistent relational data in `instance/brightloop.db`
- Werkzeug password hashing — passwords are stored as hashes, not plain text
- itsdangerous — signed, time-limited password reset tokens
- APScheduler — automatic daily recurring billing run
- SMTP — optional email delivery for password reset links and invoices

The frontend does not read static JSON files. It calls Flask API endpoints, and the API reads and writes records in the database. The sample data is inserted into SQLite only the first time the application starts.

## 2. Features implemented

- Customer registration with unique email validation and password complexity checks.
- Login, logout and password reset links (SMTP configuration optional).
- Role-based access for administrator, internal staff and customers.
- Only the administrator can create internal staff accounts.
- Product catalogue with sales price, cost price, notes and variants with price adjustments.
- Plans with daily, weekly, monthly or yearly billing, minimum quantity, availability dates, auto-close, early-close, pause and renewal controls.
- Reusable quotation templates with product lines and a quotation validity period.
- Subscription workflow: Draft → Quotation → Confirmed → Active → Closed. Pause, resume and renewal actions are also supported where the plan permits them.
- Customer portal to request a subscription and view only that customer's subscriptions and invoices.
- Recurring invoice generation from active subscriptions.
- A unique database constraint on subscription + billing period prevents a second invoice for the same cycle.
- Automatic tax calculation from each plan’s administrator-configured default tax rule, with optional tax rules on quotation add-ons.
- Fixed-amount and percentage discounts, with product/subscription scope, minimum purchase, minimum quantity, validity dates and usage limits.
- Payment recording by UPI, bank transfer, card, cash, cheque or other method; partial payments are supported.
- Invoice confirmation, cancellation, email sending and print view.
- Dashboard KPIs, six-month collection trend, overdue invoice visibility and filtered revenue reports.
- Search fields, responsive layout and database pagination endpoints.

## 3. Run locally

### Windows PowerShell

```powershell
cd brightloop-subscription-system
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python app.py
```

### macOS / Linux

```bash
cd brightloop-subscription-system
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

## 4. Demo accounts

The first run seeds these accounts and starter records:

| Role | Email | Password |
|---|---|---|
| Administrator | `admin@brightloop.test` | `ChangeMe@12345` |
| Internal staff | `staff@brightloop.test` | `Staff@12345` |
| Customer | `customer@brightloop.test` | `Customer@12345` |

Set `SEED_ADMIN_EMAIL` and `SEED_ADMIN_PASSWORD` in `.env` **before the first launch** to choose the initial administrator credentials. The app stores password hashes in the database. Set `SEED_DEMO_DATA=false` for a blank production database; the demo staff, customer, plans and sample subscription are created only when this flag is `true`.

The sample customer has an active plan due for billing. Sign in as administrator or staff and select **Run billing cycle** to generate its first invoice. Sign in as the customer to see the customer portal.

## 5. Email configuration

Without SMTP settings, the application still runs. Password reset links and invoice email content are written to the backend console for local testing. The password reset API response deliberately does not reveal whether an email address belongs to an account.

To send real emails, set these values in `.env`:

```env
APP_BASE_URL=http://127.0.0.1:5000
MAIL_SERVER=smtp.example.com
MAIL_PORT=587
MAIL_USERNAME=your-smtp-user
MAIL_PASSWORD=your-smtp-password
MAIL_USE_TLS=true
MAIL_DEFAULT_SENDER=Brightloop Billing <no-reply@yourdomain.com>
```

Use an SMTP provider's application password or API credential. Do not commit `.env` or real credentials to Git.

## 6. Recurring billing behaviour

- A subscription's `next_billing_date` determines when it is due.
- The billing service generates an invoice from the saved subscription lines and tax rules.
- The next billing date advances according to the plan frequency.
- The database unique constraint `uq_invoice_subscription_period` prevents duplicate invoices for a subscription and billing period.
- A daily scheduler runs at 01:00 using the server's local timezone when the app is started with `python app.py`.
- The **Run billing cycle** button calls the same service manually. This is useful for demos and testing.
- Paused subscriptions are resumed when their configured resume date arrives during a billing cycle.

For production deployments with multiple application workers, move scheduled billing to a single dedicated worker or external scheduler. The database uniqueness constraint remains the final duplicate-protection layer.

## 7. API overview

All API routes return JSON. State-changing requests require the CSRF token supplied by the page.

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/auth/register` | Customer registration |
| POST | `/api/auth/login` | Sign in |
| GET | `/api/auth/me` | Current session |
| POST | `/api/auth/logout` | Sign out |
| POST | `/api/auth/forgot-password` | Request reset email |
| POST | `/api/auth/reset-password` | Set new password |
| GET / POST / PUT | `/api/products` | Product catalogue |
| GET / POST / PUT | `/api/plans` | Subscription plans |
| GET / POST / PUT | `/api/tax-rules` | Tax configuration |
| GET / POST | `/api/templates` | Quotation templates |
| GET / POST / PATCH | `/api/subscriptions` | Subscription lifecycle |
| POST | `/api/portal/subscriptions` | Customer subscription request |
| POST | `/api/billing/run` | Run recurring billing |
| GET / POST | `/api/invoices` | Invoice listing / invoice creation through billing |
| POST | `/api/invoices/{id}/action` | Confirm, cancel or send invoice |
| POST | `/api/invoices/{id}/payments` | Record a payment |
| GET / POST / PUT | `/api/discounts` | Discount rules |
| GET / POST | `/api/team` | Administrator-only team management |
| GET | `/api/dashboard` | Dashboard aggregates |
| GET | `/api/reports` | Revenue and collections report |

List endpoints support `page` and `limit` query parameters. The default is 20 records per page and the maximum is 100.

## 8. Important implementation notes

1. **Payments:** This version records payments entered by an administrator or staff member. It does not connect to a real payment gateway or process card/UPI transactions. A Razorpay/Stripe integration would require merchant credentials, webhook verification and a separate payment-intent flow.
2. **Email:** Actual email delivery requires SMTP configuration. The local development fallback logs message content to the server console.
3. **Database:** SQLite is suitable for a hackathon prototype and local demonstration. For multi-user production deployment, configure PostgreSQL with an appropriate SQLAlchemy driver and use migrations.
4. **Deployment security:** Replace `SECRET_KEY`, configure HTTPS, use a production WSGI server, set secure cookie settings, restrict database backups and configure SMTP credentials through environment variables.
5. **Schema changes:** This starter uses `db.create_all()` for first-run table creation. If you modify model columns after creating a database, use a migration tool such as Flask-Migrate/Alembic or delete the local demo database and restart. Deleting the database removes all saved local data.
6. **Revenue interpretation:** Monthly recurring revenue is a normalized estimate from active subscription line values (daily × 365/12, weekly × 52/12, monthly × 1, yearly × 1/12). It excludes tax and one-time payments.

## 9. Project structure

```text
brightloop-subscription-system/
├── app.py                    # Flask API, auth, billing and scheduled job
├── models.py                 # SQLAlchemy database models
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── start_windows.bat
├── start_unix.sh
├── templates/
│   └── index.html            # Frontend shell
└── static/
    ├── css/
    │   └── styles.css        # Responsive UI styles
    └── js/
        └── app.js            # Frontend logic and API integration
```
