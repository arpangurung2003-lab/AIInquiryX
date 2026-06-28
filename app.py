from dotenv import load_dotenv
import os
import re
import secrets
import smtplib
from io import BytesIO
from email.message import EmailMessage
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, send_file, abort, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from sqlalchemy import inspect, text

from services.gemini_service import (
    AIServiceError,
    classify_inquiry,
    generate_ai_reply,
    generate_completion_notification,
    summarize_inquiry,
)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

app = Flask(__name__)

database_url = os.getenv("DATABASE_URL")

if not database_url:
    raise RuntimeError(
        "DATABASE_URL is missing. Create a .env file and add your PostgreSQL DATABASE_URL."
    )

if database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

is_production = os.getenv("FLASK_ENV", "").lower() == "production" or os.getenv("APP_ENV", "").lower() == "production"
secret_key = os.getenv("SECRET_KEY") or ("dev-only-" + secrets.token_urlsafe(32))

app.config["SECRET_KEY"] = secret_key
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=7)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = is_production or os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
app.config["REMEMBER_COOKIE_HTTPONLY"] = True
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "8")) * 1024 * 1024
app.config["UPLOAD_FOLDER"] = os.getenv("UPLOAD_FOLDER") or os.path.join(BASE_DIR, "protected_uploads")

Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')

serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "admin_login"
login_manager.login_message_category = "error"

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "pdf", "doc", "docx", "txt"}

VALID_STATUSES = ["Pending", "Under Review", "In Progress", "Waiting for Customer", "Fixed", "Completed", "Closed", "Reopened"]

OLD_STATUS_MAP = {
    "".join(["Res", "olved"]): "Completed",
    "".join(["Rej", "ected"]): "Fixed",
}

CONTACT_CHOICES = ["Email", "Phone", "Both"]

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PHONE_RE = re.compile(r"^[0-9+()\-\s]{7,20}$")


class Admin(UserMixin, db.Model):
    __tablename__ = "admins"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, default="Administrator")
    email = db.Column(db.String(160), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(40), nullable=False, default="Super Admin")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Customer(db.Model):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(140), nullable=False)
    email = db.Column(db.String(160), nullable=False, index=True)
    phone = db.Column(db.String(40))
    company = db.Column(db.String(140))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    inquiries = db.relationship(
        "Inquiry",
        backref="customer",
        lazy=True,
        cascade="all, delete",
    )


class Inquiry(db.Model):
    __tablename__ = "inquiries"

    inquiry_id = db.Column(db.Integer, primary_key=True)
    tracking_id = db.Column(
        db.String(24),
        unique=True,
        index=True,
        nullable=False,
        default=lambda: create_tracking_id(),
    )
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=True)

    customer_name = db.Column(db.String(140), nullable=False)
    email = db.Column(db.String(160), nullable=False, index=True)
    phone = db.Column(db.String(40))

    contact_preference = db.Column(db.String(20), default="Email")
    category = db.Column(db.String(80), default="General")
    subject = db.Column(db.String(220), nullable=False)
    message = db.Column(db.Text, nullable=False)
    priority = db.Column(db.String(30), default="Normal")
    status = db.Column(db.String(30), default="Pending")

    admin_response = db.Column(db.Text)

    attachment_filename = db.Column(db.String(255))
    attachment_original = db.Column(db.String(255))

    rating = db.Column(db.Integer)
    rating_comment = db.Column(db.Text)
    rated_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    responses = db.relationship(
        "Response",
        backref="inquiry",
        lazy=True,
        cascade="all, delete",
    )

    notifications = db.relationship(
        "Notification",
        backref="inquiry",
        lazy=True,
        cascade="all, delete",
    )


class Response(db.Model):
    __tablename__ = "responses"

    id = db.Column(db.Integer, primary_key=True)
    inquiry_id = db.Column(
        db.Integer,
        db.ForeignKey("inquiries.inquiry_id"),
        nullable=False,
    )
    admin_id = db.Column(db.Integer, db.ForeignKey("admins.id"), nullable=True)
    response_text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    inquiry_id = db.Column(
        db.Integer,
        db.ForeignKey("inquiries.inquiry_id"),
        nullable=False,
    )
    email_sent = db.Column(db.Boolean, default=False)
    sms_prepared = db.Column(db.Boolean, default=False)
    notification_type = db.Column(db.String(80), nullable=False)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    error_message = db.Column(db.Text)
    is_read = db.Column(db.Boolean, default=False)


class AIChatHistory(db.Model):
    __tablename__ = "ai_chat_history"

    id = db.Column(db.Integer, primary_key=True)
    user_message = db.Column(db.Text, nullable=False)
    assistant_reply = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    event_date = db.Column(db.Date, nullable=False)
    location = db.Column(db.String(160), default="Online")
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), default="Upcoming")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ContactMessage(db.Model):
    __tablename__ = "contact_messages"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False)
    email = db.Column(db.String(160), nullable=False, index=True)
    phone = db.Column(db.String(40))
    company = db.Column(db.String(140))
    subject = db.Column(db.String(220), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class StatusHistory(db.Model):
    __tablename__ = "status_history"

    id = db.Column(db.Integer, primary_key=True)
    inquiry_id = db.Column(db.Integer, db.ForeignKey("inquiries.inquiry_id"), nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey("admins.id"), nullable=True)
    old_status = db.Column(db.String(40))
    new_status = db.Column(db.String(40), nullable=False)
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    inquiry = db.relationship("Inquiry", backref=db.backref("status_history", lazy=True, cascade="all, delete-orphan"))
    admin = db.relationship("Admin")


class InternalNote(db.Model):
    __tablename__ = "internal_notes"

    id = db.Column(db.Integer, primary_key=True)
    inquiry_id = db.Column(db.Integer, db.ForeignKey("inquiries.inquiry_id"), nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey("admins.id"), nullable=True)
    note = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    inquiry = db.relationship("Inquiry", backref=db.backref("internal_notes", lazy=True, cascade="all, delete-orphan"))
    admin = db.relationship("Admin")


def create_tracking_id():
    return "AIX-" + secrets.token_hex(4).upper()

def normalize_phone_digits(value):
    """Keep only phone number digits for safe phone matching."""
    return re.sub(r"\D", "", value or "")

BLOG_ARTICLES = [
    {
        "slug": "support-workflow",
        "category": "Support",
        "title": "Building a faster support workflow with inquiry tracking",
        "summary": "A practical guide to organizing customer requests from first contact to final resolution.",
        "read_time": "5 Min Read",
        "image": "https://images.unsplash.com/photo-1552664730-d307ca884978?auto=format&fit=crop&w=900&q=80",
        "lead": "Good support starts when every inquiry has a clear owner, status, priority, and next action. A tracking system gives customers confidence and gives the team a clean process to follow.",
        "paragraphs": [
            "When customers submit a request, the system should immediately capture the customer name, email, phone, subject, message, category, priority, and preferred contact method. This creates a full support record instead of a loose message that can be forgotten. A tracking ID also gives the customer a simple way to return later and check progress without calling or sending repeated emails.",
            "Inside the admin dashboard, support staff can review new inquiries, update the status, add a response, and keep the conversation organized. Clear statuses such as Pending, Under Review, Fixed, and Completed help everyone understand exactly what stage the inquiry is in. This reduces confusion and keeps the support team focused on the next useful step.",
            "A strong workflow also improves communication. Confirmation emails, completion messages, and admin notes make the process feel professional. When a customer knows that their inquiry has been received and is being handled, trust increases even before the issue is fully resolved.",
            "For growing teams, inquiry tracking becomes even more important because multiple people may work on the same customer issue. A shared system prevents duplicated work, missed replies, and unclear responsibility. Every ticket keeps its own history, making it easier for another admin to understand what already happened. Over time, this organized record becomes useful training material for new support staff and helps managers identify which customer problems appear most often."
        ],
        "highlights": [
            "Use tracking IDs so customers can check progress anytime.",
            "Keep every inquiry status simple, visible, and updated.",
            "Store admin responses and customer details in one place.",
            "Send email notifications when important status changes happen."
        ]
    },
    {
        "slug": "analytics-dashboard",
        "category": "Analytics",
        "title": "Using analytics to improve customer inquiry decisions",
        "summary": "How dashboard numbers help admins understand workload, response quality, and support performance.",
        "read_time": "5 Min Read",
        "image": "https://images.unsplash.com/photo-1551288049-bebda4e38f71?auto=format&fit=crop&w=900&q=80",
        "lead": "Analytics turns normal inquiry data into useful business decisions. Instead of guessing how busy the support team is, admins can look at real numbers and act faster.",
        "paragraphs": [
            "A modern inquiry dashboard should show total inquiries, completed inquiries, pending inquiries, urgent cases, customer count, and recent activity. These numbers help admins understand whether the team is handling work smoothly or whether support demand is increasing. When the dashboard is clean and easy to read, decisions become faster.",
            "Analytics also helps identify patterns. If many customers are asking the same question, the company may need to improve a service page, update a product description, or create a helpful FAQ. If urgent inquiries are increasing, managers can adjust staffing or priority rules before the backlog becomes a serious problem. A clean analytics view also helps compare today’s workload with recent days, making it easier to notice when the team is falling behind.",
            "Charts and summary cards are most useful when they are simple. A support team does not need confusing reports every day; they need quick visibility into what is open, what is delayed, what is finished, and what needs attention now. This is why the dashboard should use clear cards, badges, tables, and trend visuals.",
            "When analytics is combined with AI assistance, admins can move even faster. Gemini-powered summaries, classifications, and response suggestions can save time, while dashboard metrics show whether those improvements are actually reducing response delays. The best dashboards do not only look attractive; they guide the next action by showing what needs attention, what is improving, and what should be reviewed first."
        ],
        "highlights": [
            "Track pending, completed, urgent, and under-review inquiries.",
            "Use trends to understand busy days and support bottlenecks.",
            "Keep charts simple enough for quick admin decisions.",
            "Combine AI tools with analytics for faster response planning."
        ]
    },
    {
        "slug": "security-admin-portal",
        "category": "Security",
        "title": "Securing the admin portal and customer inquiry data",
        "summary": "Important security practices for login, verification, customer records, and admin-only actions.",
        "read_time": "5 Min Read",
        "image": "https://images.unsplash.com/photo-1555949963-aa79dcee981c?auto=format&fit=crop&w=900&q=80",
        "lead": "Customer inquiries often contain private contact details, business problems, attachments, and service history. The admin portal must protect that information with secure access and careful handling.",
        "paragraphs": [
            "Admin login should be separated from public customer pages and protected with strong password hashing, session control, and login validation. Only authorized admins should access inquiry records, customer details, dashboard analytics, export tools, and status update actions. This keeps the system professional and reduces the risk of accidental data exposure.",
            "Email verification is another important layer. When customers submit inquiries using a real email address, verification helps confirm that the contact information belongs to them. This makes tracking updates and completion notifications more reliable and prevents fake or incorrect addresses from filling the database.",
            "Security also means reducing unnecessary data. The system should only collect information needed to respond to the inquiry. Attachments should be controlled, file types should be limited, and sensitive dashboard actions should be available only after admin authentication. Clear validation protects both the company and the customer.",
            "A secure support platform should feel easy to use without feeling weak. Good design, clear alerts, protected forms, safe redirects, and consistent admin navigation all help create a system that is both trustworthy and comfortable for staff to use every day. Security should also be practical: hide default passwords from public screens, avoid exposing sensitive configuration values, and keep every admin action behind authentication."
        ],
        "highlights": [
            "Use hashed passwords and protected admin-only routes.",
            "Verify customer emails before saving final inquiry records.",
            "Validate form inputs and uploaded attachment types.",
            "Keep dashboard access limited to authenticated admins."
        ]
    }
]

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_attachment(file_storage):
    if not file_storage or not file_storage.filename:
        return None, None

    if not allowed_file(file_storage.filename):
        raise ValueError("Unsupported attachment type. Use image, PDF, DOC/DOCX, or TXT.")

    original = secure_filename(file_storage.filename)
    if not original:
        raise ValueError("Invalid attachment filename.")

    extension = original.rsplit(".", 1)[1].lower()
    content_type = (file_storage.mimetype or "").lower()
    expected_groups = {
        "png": "image/", "jpg": "image/", "jpeg": "image/", "gif": "image/", "webp": "image/",
        "pdf": "application/pdf",
        "txt": "text/",
        "doc": "application/", "docx": "application/",
    }
    expected = expected_groups.get(extension)
    if expected and content_type and not content_type.startswith(expected):
        raise ValueError("Attachment file type does not match the uploaded file.")

    unique = f"{secrets.token_hex(12)}_{original}"
    file_storage.save(os.path.join(app.config["UPLOAD_FOLDER"], unique))

    return unique, original


def is_valid_email(email):
    return bool(EMAIL_RE.match(email or ""))


def is_valid_phone(phone):
    return not phone or bool(PHONE_RE.match(phone))


def normalize_status(status):
    status = OLD_STATUS_MAP.get(status, status)
    return status if status in VALID_STATUSES else "Pending"


def has_role(*roles):
    return current_user.is_authenticated and getattr(current_user, "role", "Super Admin") in roles


def require_roles(*roles):
    def decorator(fn):
        from functools import wraps

        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not has_role(*roles):
                flash("You do not have permission to perform that action.", "error")
                return redirect(url_for("admin_dashboard"))
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def mask_phone(phone):
    if not phone:
        return ""

    digits = re.sub(r"\D", "", phone)
    return ("*" * max(0, len(digits) - 4)) + digits[-4:] if len(digits) > 4 else phone


def send_email(to_email, subject, body):
    """SMTP email sender for Gmail App Password or any SMTP provider."""
    if not is_valid_email(to_email):
        return False, "Invalid recipient email."

    host = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    port = int(os.getenv("MAIL_PORT", "587"))
    username = os.getenv("MAIL_USERNAME", "").strip()
    password = os.getenv("MAIL_PASSWORD", "").strip()
    sender = os.getenv("MAIL_DEFAULT_SENDER", username).strip()
    use_tls = os.getenv("MAIL_USE_TLS", "true").lower() == "true"

    if not username or not password or not sender:
        return False, "Mail is not configured. Set MAIL_USERNAME, MAIL_PASSWORD, and MAIL_DEFAULT_SENDER in .env."

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            if use_tls:
                smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(msg)

        return True, None

    except Exception as exc:
        return False, str(exc)


def prepare_sms_notification(inquiry, notification_type):
    """Send an SMS using Twilio when TWILIO_* values are configured."""
    if not inquiry.phone:
        return False, "No phone number supplied."

    sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    from_number = os.getenv("TWILIO_FROM_NUMBER", "").strip()

    if not sid or not token or not from_number:
        return False, "Twilio is not configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER in .env."

    try:
        from twilio.rest import Client

        body = f"AI InquiryX update: {inquiry.tracking_id} is {inquiry.status}. Check your tracking page for details."

        Client(sid, token).messages.create(
            body=body,
            from_=from_number,
            to=inquiry.phone,
        )

        return True, None

    except Exception as exc:
        return False, str(exc)


def log_notification(
    inquiry,
    notification_type,
    email_sent=False,
    sms_prepared=False,
    error_message=None,
):
    db.session.add(
        Notification(
            inquiry_id=inquiry.inquiry_id,
            email_sent=email_sent,
            sms_prepared=sms_prepared,
            notification_type=notification_type,
            error_message=error_message,
        )
    )


def email_body_for_status(inquiry, status):
    if status == "Under Review":
        return (
            f"Dear {inquiry.customer_name},\n\n"
            "Thank you for contacting AI InquiryX.\n"
            "Your inquiry has been received and is currently under review.\n"
            "We will notify you once it is solved.\n\n"
            f"Tracking ID: {inquiry.tracking_id}\n"
            "Status: Under Review\n\n"
            "Regards,\nAI InquiryX Team"
        )

    if status in ["Fixed", "Completed"]:
        return (
            f"Dear {inquiry.customer_name},\n\n"
            "Your inquiry has been successfully resolved.\n"
            "Thank you for contacting AI InquiryX.\n\n"
            f"Tracking ID: {inquiry.tracking_id}\n"
            f"Status: {status}\n"
            f"Admin reply: {inquiry.admin_response or 'Completed by AI InquiryX support team.'}\n\n"
            "Regards,\nAI InquiryX Team"
        )

    return (
        f"Dear {inquiry.customer_name},\n\n"
        "Your inquiry has been received. Our team is reviewing it.\n\n"
        f"Tracking ID: {inquiry.tracking_id}\n"
        f"Status: {status}\n\n"
        "Regards,\nAI InquiryX Team"
    )


def notify_customer(inquiry, notification_type, force_email=False):
    wants_email = force_email or inquiry.contact_preference in ["Email", "Both"]
    wants_sms = inquiry.contact_preference in ["Phone", "Both"]

    email_sent = False
    sms_prepared = False
    errors = []

    if wants_email:
        subject = "Your Inquiry Has Been Completed" if notification_type == "completed" else "Inquiry Received - AI InquiryX"

        ok, err = send_email(
            inquiry.email,
            subject,
            email_body_for_status(inquiry, inquiry.status),
        )

        email_sent = ok

        if err:
            errors.append(err)

    if wants_sms:
        sms_prepared, err = prepare_sms_notification(inquiry, notification_type)

        if err:
            errors.append(err)

    log_notification(
        inquiry,
        notification_type,
        email_sent=email_sent,
        sms_prepared=sms_prepared,
        error_message=" | ".join(errors) or None,
    )

    return email_sent, sms_prepared, errors


@login_manager.user_loader
def load_user(admin_id):
    return db.session.get(Admin, int(admin_id))


@app.context_processor
def inject_global_context():
    token = session.get("csrf_token")

    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token

    unread_notifications = 0
    header_notifications = []

    if current_user.is_authenticated:
        try:
            unread_notifications = Notification.query.filter_by(is_read=False).count()
            header_notifications = (
                Notification.query
                .order_by(Notification.sent_at.desc())
                .limit(6)
                .all()
            )
        except Exception:
            unread_notifications = 0
            header_notifications = []

    return {
        "current_year": datetime.now(timezone.utc).year,
        "csrf_token": token,
        "valid_statuses": VALID_STATUSES,
        "unread_notifications": unread_notifications,
        "header_notifications": header_notifications,
    }


@app.before_request
def csrf_protect():
    if request.method != "POST":
        return None

    if request.endpoint in {"chatbot"}:
        return None

    token = session.get("csrf_token")
    submitted = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")

    if token and submitted and secrets.compare_digest(token, submitted):
        return None

    if request.is_json or request.headers.get("Accept") == "application/json":
        return jsonify({"success": False, "error": "Security token expired. Please refresh and try again."}), 400

    flash("Security token expired. Please try again.", "error")
    return redirect(request.referrer or url_for("home"))


@app.after_request
def apply_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response


@app.route("/")
def home():
    recent_events = Event.query.order_by(Event.event_date.asc()).limit(3).all()
    return render_template("home.html", events=recent_events, blog_articles=BLOG_ARTICLES)


@app.route("/blog")
def blog():
    return render_template("blog.html", articles=BLOG_ARTICLES)


@app.route("/blog/<slug>")
def blog_article(slug):
    article = next((item for item in BLOG_ARTICLES if item["slug"] == slug), None)
    if article is None:
        abort(404)
    return render_template("blog_article.html", article=article)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/services")
def services():
    return render_template("services.html")


@app.route("/gallery")
def gallery():
    return render_template("gallery.html")


@app.route("/events")
def events():
    return render_template(
        "events.html",
        events=Event.query.order_by(Event.event_date.asc()).all(),
    )


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        company = request.form.get("company", "").strip()
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()

        if not name or not is_valid_email(email) or not subject or not message:
            flash("Please enter a valid name, email, subject, and message.", "error")
            return redirect(url_for("contact"))

        if not is_valid_phone(phone):
            flash("Please enter a valid phone number, or leave it blank.", "error")
            return redirect(url_for("contact"))

        db.session.add(ContactMessage(name=name, email=email, phone=phone, company=company, subject=subject, message=message))
        db.session.commit()

        admin_email = os.getenv("ADMIN_NOTIFY_EMAIL") or os.getenv("MAIL_DEFAULT_SENDER")
        if admin_email:
            send_email(admin_email, f"New AI InquiryX contact: {subject}", f"From: {name} <{email}>\nPhone: {phone or '-'}\nCompany: {company or '-'}\n\n{message}")

        flash("Thank you. Your message was received by the InquiryX support team.", "success")
        return redirect(url_for("contact"))

    return render_template("contact.html")


@app.route("/submit-inquiry", methods=["GET", "POST"])
def submit_inquiry():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        company = request.form.get("company", "").strip()
        category = request.form.get("category", "General")
        subject = request.form.get("subject", "").strip() or category
        message = request.form.get("message", "").strip()
        priority = request.form.get("priority", "Normal")
        contact_preference = request.form.get("contact_preference", "Email")
        contact_preference = contact_preference if contact_preference in CONTACT_CHOICES else "Email"

        if not full_name or not is_valid_email(email) or not message:
            flash("Please enter a valid name, email, and inquiry message.", "error")
            return redirect(url_for("submit_inquiry"))

        if not is_valid_phone(phone):
            flash("Please enter a valid phone number, or leave it blank.", "error")
            return redirect(url_for("submit_inquiry"))

        if contact_preference in ["Phone", "Both"] and not phone:
            flash("Phone number is required when you choose phone updates.", "error")
            return redirect(url_for("submit_inquiry"))

        posted_code = request.form.get("email_verification_code", "").strip()
        verified_key = session.get("verified_inquiry_email")
        expected_email = session.get("pending_inquiry_email")
        expected_code = session.get("pending_inquiry_code")
        form_data = request.form.to_dict()

        if verified_key != email:
            if (
                posted_code
                and expected_email == email
                and expected_code
                and secrets.compare_digest(posted_code, expected_code)
            ):
                session["verified_inquiry_email"] = email
                session.pop("pending_inquiry_code", None)
                session.pop("pending_inquiry_email", None)

            else:
                code = f"{secrets.randbelow(900000) + 100000}"
                session["pending_inquiry_code"] = code
                session["pending_inquiry_email"] = email

                ok, err = send_email(
                    email,
                    "AI InquiryX email verification code",
                    f"Your AI InquiryX verification code is: {code}",
                )

                if ok:
                    flash("We sent a verification code to your email. Enter it below and submit again.", "info")
                else:
                    flash(f"Email verification is required. Development code: {code}. SMTP note: {err}", "info")

                return render_template(
                    "submit_inquiry.html",
                    pending_email=email,
                    form_data=form_data,
                )

        try:
            attachment_filename, attachment_original = save_attachment(request.files.get("attachment"))
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("submit_inquiry"))

        customer = Customer.query.filter_by(email=email).first()

        if not customer:
            customer = Customer(
                full_name=full_name,
                email=email,
                phone=phone,
                company=company,
            )
            db.session.add(customer)
            db.session.flush()

        else:
            customer.full_name = full_name
            customer.phone = phone or customer.phone
            customer.company = company or customer.company

        inquiry = Inquiry(
            tracking_id=create_tracking_id(),
            customer_id=customer.id,
            customer_name=full_name,
            email=email,
            phone=phone,
            contact_preference=contact_preference,
            category=category,
            subject=subject,
            message=message,
            priority=priority,
            status="Under Review",
            attachment_filename=attachment_filename,
            attachment_original=attachment_original,
        )

        db.session.add(inquiry)
        db.session.flush()

        email_sent, sms_prepared, errors = notify_customer(
            inquiry,
            "received",
            force_email=True,
        )

        print("EMAIL DEBUG:", email_sent, errors)

        db.session.commit()

        session.pop("verified_inquiry_email", None)

        flash(
            f"Your inquiry has been received. Our team is reviewing it. Tracking ID: {inquiry.tracking_id}",
            "success",
        )

        return redirect(url_for("track_inquiry", tracking_id=inquiry.tracking_id))

    return render_template("submit_inquiry.html")


@app.route("/track-inquiry", methods=["GET", "POST"])
def track_inquiry():
    result = None
    prefill_tracking_id = request.args.get("tracking_id", "")
    prefill_identity = request.args.get("identity", "")

    if request.method == "POST":
        tracking_id = request.form.get("tracking_id", "").strip().upper()
        identity = request.form.get("identity", "").strip().lower()

        identity_phone = normalize_phone_digits(identity)

        conditions = [
            db.func.lower(Inquiry.email) == identity
        ]

        if "@" not in identity and identity_phone:
            stored_phone_digits = db.func.regexp_replace(
                db.func.coalesce(Inquiry.phone, ""),
                r"\D",
                "",
                "g"
            )
            conditions.append(stored_phone_digits == identity_phone)

        result = (
            Inquiry.query.filter_by(tracking_id=tracking_id)
            .filter(db.or_(*conditions))
            .order_by(Inquiry.created_at.desc())
            .first()
        )

        if result:
            session["verified_tracking_id"] = result.tracking_id
        else:
            flash("No inquiry found. Please check your tracking ID and the email or phone used when submitting.", "error")

    return render_template(
        "track_inquiry.html",
        inquiry=result,
        prefill_tracking_id=prefill_tracking_id,
        prefill_identity=prefill_identity,
    )

@app.route("/rate-inquiry/<tracking_id>", methods=["POST"])
def rate_inquiry(tracking_id):
    inquiry = Inquiry.query.filter_by(tracking_id=tracking_id.upper()).first_or_404()

    if session.get("verified_tracking_id") != inquiry.tracking_id:
        flash("Please verify your tracking ID and email/phone before rating.", "error")
        return redirect(url_for("track_inquiry", tracking_id=inquiry.tracking_id))

    if inquiry.status not in ["Fixed", "Completed", "Closed"]:
        flash("Ratings are available after the inquiry is completed.", "error")
        return redirect(url_for("track_inquiry", tracking_id=inquiry.tracking_id))

    try:
        rating = int(request.form.get("rating", "0"))
    except ValueError:
        rating = 0

    if rating < 1 or rating > 5:
        flash("Please select a rating from 1 to 5.", "error")
    else:
        inquiry.rating = rating
        inquiry.rating_comment = request.form.get("rating_comment", "").strip()[:1000]
        inquiry.rated_at = datetime.now(timezone.utc)
        db.session.commit()
        flash("Thank you for rating our support.", "success")

    return redirect(url_for("track_inquiry", tracking_id=inquiry.tracking_id))


@app.route("/customer/register")
def customer_register():
    return redirect(url_for("submit_inquiry"))


@app.route("/customer/login", methods=["GET", "POST"])
def customer_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        tracking_id = request.form.get("tracking_id", "").strip().upper()

        inquiry = Inquiry.query.filter_by(email=email, tracking_id=tracking_id).first()
        if not inquiry:
            flash("We could not verify that email and tracking ID together.", "error")
            return redirect(url_for("customer_login"))

        session["customer_email"] = email
        session["customer_id"] = inquiry.customer_id
        session["verified_tracking_id"] = inquiry.tracking_id
        flash("Customer portal opened securely.", "success")
        return redirect(url_for("customer_tracking_portal"))

    return render_template("customer_login.html")


@app.route("/customer/logout")
def customer_logout():
    session.pop("customer_id", None)
    session.pop("customer_email", None)
    session.pop("verified_tracking_id", None)
    return redirect(url_for("home"))


@app.route("/customer/dashboard")
@app.route("/customer/tracking-portal")
def customer_tracking_portal():
    customer_email = session.get("customer_email")
    if not customer_email:
        flash("Please verify your email and tracking ID to open the customer portal.", "info")
        return redirect(url_for("customer_login"))

    inquiries = Inquiry.query.filter_by(email=customer_email).order_by(Inquiry.created_at.desc()).all()
    return render_template("customer_dashboard.html", inquiries=inquiries, customer_email=customer_email)


@app.route("/customer/reopen/<tracking_id>", methods=["POST"])
def customer_reopen_inquiry(tracking_id):
    customer_email = session.get("customer_email")
    inquiry = Inquiry.query.filter_by(tracking_id=tracking_id.upper()).first_or_404()

    if not customer_email or inquiry.email != customer_email:
        flash("Please verify your customer portal access before reopening an inquiry.", "error")
        return redirect(url_for("customer_login"))

    if inquiry.status not in ["Fixed", "Completed", "Closed"]:
        flash("Only fixed, completed, or closed inquiries can be reopened.", "error")
        return redirect(url_for("customer_tracking_portal"))

    old_status = inquiry.status
    inquiry.status = "Reopened"
    inquiry.updated_at = datetime.now(timezone.utc)
    db.session.add(StatusHistory(inquiry_id=inquiry.inquiry_id, old_status=old_status, new_status="Reopened", note="Customer reopened the inquiry from the portal."))
    db.session.commit()
    flash("Your inquiry has been reopened. Our support team will review it again.", "success")
    return redirect(url_for("customer_tracking_portal"))


@app.route("/login")
def login():
    return redirect(url_for("admin_login"))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if current_user.is_authenticated:
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        now_ts = datetime.now(timezone.utc).timestamp()
        lock_until = float(session.get("admin_login_lock_until", 0) or 0)

        if lock_until and now_ts < lock_until:
            wait_minutes = max(1, int((lock_until - now_ts) // 60) + 1)
            flash(f"Too many failed attempts. Try again in about {wait_minutes} minute(s).", "error")
            return render_template("admin/login.html")

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = request.form.get("remember") == "on"

        admin = Admin.query.filter_by(email=email).first()

        if admin and admin.check_password(password):
            session.pop("admin_login_failures", None)
            session.pop("admin_login_lock_until", None)

            login_user(admin, remember=remember)

            flash("Welcome back to the admin dashboard.", "success")
            return redirect(url_for("admin_dashboard"))

        failures = int(session.get("admin_login_failures", 0)) + 1
        session["admin_login_failures"] = failures

        if failures >= 5:
            session["admin_login_lock_until"] = now_ts + 600
            session["admin_login_failures"] = 0
            flash("Too many failed attempts. Admin login is locked for 10 minutes.", "error")
        else:
            flash("Invalid email or password.", "error")

    return render_template("admin/login.html")


@app.route("/admin/register", methods=["GET", "POST"])
def admin_register():
    if current_user.is_authenticated:
        return redirect(url_for("admin_dashboard"))

    invite_code_required = os.getenv("ADMIN_INVITE_CODE", "").strip()

    if not invite_code_required:
        flash("Admin registration is disabled. Set ADMIN_INVITE_CODE in .env to create admins.", "error")
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        name = request.form.get("name", "").strip() or "Administrator"
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        invite_code = request.form.get("invite_code", "").strip()

        if invite_code != invite_code_required:
            flash("Invalid admin invite code.", "error")
        elif not is_valid_email(email):
            flash("Please enter a valid email address.", "error")
        elif len(password) < 10:
            flash("Password must be at least 10 characters.", "error")
        elif password != confirm_password:
            flash("Passwords do not match.", "error")
        elif Admin.query.filter_by(email=email).first():
            flash("An admin account with this email already exists.", "error")
            return redirect(url_for("admin_login"))
        else:
            admin = Admin(name=name, email=email)
            admin.set_password(password)

            db.session.add(admin)
            db.session.commit()

            flash("Admin account created successfully. Please sign in.", "success")
            return redirect(url_for("admin_login"))

    return render_template("admin/register.html", invite_code_required=True)


@app.route("/admin/forgot-password", methods=["GET", "POST"])
def forgot_password():
    reset_link = None
    submitted_email = ""

    if request.method == "POST":
        submitted_email = request.form.get("email", "").strip().lower()

        if not is_valid_email(submitted_email):
            flash("Please enter a valid admin email address.", "error")
            return render_template(
                "admin/forgot_password.html",
                reset_link=reset_link,
                submitted_email=submitted_email,
            )

        admin = Admin.query.filter_by(email=submitted_email).first()

        if admin:
            token = serializer.dumps(admin.email, salt="password-reset-salt")
            reset_link = url_for("reset_password", token=token, _external=True)
            ok, err = send_email(admin.email, "AI InquiryX password reset", f"Use this secure reset link within 30 minutes:\n\n{reset_link}")
            if ok:
                flash("A password reset link was sent to your admin email.", "success")
            else:
                flash("Password reset email could not be sent. Check SMTP settings before production use.", "error")
        else:
            flash("No admin account was found for that email address.", "error")

    return render_template(
        "admin/forgot_password.html",
        reset_link=reset_link,
        submitted_email=submitted_email,
    )


@app.route("/admin/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    try:
        email = serializer.loads(token, salt="password-reset-salt", max_age=1800)
    except SignatureExpired:
        flash("Reset link has expired. Please request a new one.", "error")
        return redirect(url_for("forgot_password"))
    except BadSignature:
        flash("Invalid reset link.", "error")
        return redirect(url_for("forgot_password"))

    admin = Admin.query.filter_by(email=email).first_or_404()

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if len(password) < 10:
            flash("Password must be at least 10 characters.", "error")
        elif password != confirm_password:
            flash("Passwords do not match.", "error")
        else:
            admin.set_password(password)
            db.session.commit()

            flash("Password updated successfully. Please sign in.", "success")
            return redirect(url_for("admin_login"))

    return render_template("admin/reset_password.html")


def _ai_rate_limit(action_name, limit_seconds=8):
    key = f"ai_rate_{getattr(current_user, 'id', 'guest')}_{action_name}"
    now = datetime.now(timezone.utc).timestamp()
    last_used = session.get(key, 0)

    if now - float(last_used) < limit_seconds:
        wait = int(limit_seconds - (now - float(last_used))) + 1
        return False, f"Please wait {wait} seconds before using this AI action again."

    session[key] = now
    session.modified = True

    return True, None


def _inquiry_payload(inquiry):
    return {
        "id": inquiry.tracking_id,
        "customer_name": inquiry.customer_name,
        "email": inquiry.email,
        "category": inquiry.category,
        "subject": inquiry.subject,
        "message": inquiry.message,
        "priority": inquiry.priority,
        "status": inquiry.status,
    }


@app.route("/admin/logout")
@login_required
def admin_logout():
    logout_user()
    return redirect(url_for("home"))


@app.route("/admin/dashboard")
@login_required
def admin_dashboard():
    total = Inquiry.query.count()
    customers_total = Customer.query.count()

    pending = Inquiry.query.filter_by(status="Pending").count()
    under_review = Inquiry.query.filter_by(status="Under Review").count()
    fixed = Inquiry.query.filter_by(status="Fixed").count()
    completed = Inquiry.query.filter_by(status="Completed").count()

    open_tickets = pending + under_review

    resolved_today = Inquiry.query.filter(
        Inquiry.status.in_(["Fixed", "Completed", "Closed"]),
        db.func.date(Inquiry.updated_at) == date.today(),
    ).count()

    urgent = Inquiry.query.filter_by(priority="Urgent").count()
    high_priority = Inquiry.query.filter(Inquiry.priority.in_(["High", "Urgent"])).count()

    recent = Inquiry.query.order_by(Inquiry.created_at.desc()).limit(7).all()
    latest_customers = Customer.query.order_by(Customer.created_at.desc()).limit(4).all()

    category_rows = (
        db.session.query(Inquiry.category, db.func.count(Inquiry.inquiry_id))
        .group_by(Inquiry.category)
        .all()
    )

    categories = [
        {
            "name": row[0] or "General",
            "count": row[1],
        }
        for row in category_rows
    ]

    daily_stats = []

    for i in range(6, -1, -1):
        day = date.today() - timedelta(days=i)

        created_count = Inquiry.query.filter(
            db.func.date(Inquiry.created_at) == day
        ).count()

        completed_count = Inquiry.query.filter(
            Inquiry.status.in_(["Fixed", "Completed", "Closed"]),
            db.func.date(Inquiry.updated_at) == day,
        ).count()

        daily_stats.append(
            {
                "label": day.strftime("%a"),
                "date": day.strftime("%Y-%m-%d"),
                "created": created_count,
                "completed": completed_count,
            }
        )

    max_daily = max(
        [d["created"] for d in daily_stats]
        + [d["completed"] for d in daily_stats]
        + [1]
    )

    latest_notifications = Notification.query.order_by(Notification.sent_at.desc()).limit(6).all()

    def pct(value):
        return int(round((value / total) * 100)) if total else 0

    chart = {
        "resolved": pct(completed + fixed),
        "pending": pct(pending),
        "in_progress": pct(under_review),
        "open": pct(open_tickets),
        "urgent": pct(urgent),
        "high_priority": pct(high_priority),
    }

    return render_template(
        "admin/dashboard.html",
        total=total,
        customers_total=customers_total,
        open_tickets=open_tickets,
        resolved_today=resolved_today,
        resolved=completed,
        pending=pending,
        in_progress=under_review,
        under_review=under_review,
        fixed=fixed,
        completed=completed,
        escalated=urgent,
        recent=recent,
        latest_customers=latest_customers,
        categories=categories,
        chart=chart,
        daily_stats=daily_stats,
        max_daily=max_daily,
        latest_notifications=latest_notifications,
    )


@app.route("/admin/inquiries")
@login_required
def admin_inquiries():
    search = request.args.get("search", "").strip()
    status = request.args.get("status", "")
    priority = request.args.get("priority", "")
    category = request.args.get("category", "")

    query = Inquiry.query

    if search:
        like = f"%{search}%"

        query = query.filter(
            db.or_(
                Inquiry.customer_name.ilike(like),
                Inquiry.email.ilike(like),
                Inquiry.phone.ilike(like),
                Inquiry.category.ilike(like),
                Inquiry.subject.ilike(like),
                Inquiry.tracking_id.ilike(like),
            )
        )

    if status:
        query = query.filter_by(status=normalize_status(status))

    if priority:
        query = query.filter_by(priority=priority)

    if category:
        query = query.filter_by(category=category)

    inquiries = query.order_by(Inquiry.created_at.desc()).all()

    return render_template("admin/inquiries.html", inquiries=inquiries)


@app.route("/admin/inquiry/<int:inquiry_id>", methods=["GET", "POST"])
@login_required
def admin_inquiry_detail(inquiry_id):
    inquiry = Inquiry.query.get_or_404(inquiry_id)

    if request.method == "POST":
        if not has_role("Super Admin", "Support Staff"):
            flash("Viewer accounts cannot update inquiries.", "error")
            return redirect(url_for("admin_inquiry_detail", inquiry_id=inquiry.inquiry_id))

        old_status = normalize_status(inquiry.status)
        new_status = normalize_status(request.form.get("status", inquiry.status))
        old_response = inquiry.admin_response or ""

        inquiry.status = new_status
        inquiry.priority = request.form.get("priority", inquiry.priority)

        response_text = request.form.get("admin_response", "").strip()
        internal_note = request.form.get("internal_note", "").strip()
        inquiry.admin_response = response_text
        inquiry.updated_at = datetime.now(timezone.utc)

        if response_text and response_text != old_response:
            db.session.add(
                Response(
                    inquiry_id=inquiry.inquiry_id,
                    admin_id=current_user.id,
                    response_text=response_text,
                )
            )

        if internal_note:
            db.session.add(InternalNote(inquiry_id=inquiry.inquiry_id, admin_id=current_user.id, note=internal_note[:3000]))

        if new_status != old_status:
            db.session.add(
                StatusHistory(
                    inquiry_id=inquiry.inquiry_id,
                    admin_id=current_user.id,
                    old_status=old_status,
                    new_status=new_status,
                    note=internal_note or None,
                )
            )
            notification_type = (
                "completed"
                if new_status in ["Fixed", "Completed", "Closed"]
                else "under_review"
                if new_status in ["Under Review", "In Progress"]
                else "status_update"
            )
            notify_customer(inquiry, notification_type, force_email=True)
        elif response_text and response_text != old_response:
            notify_customer(inquiry, "response_update", force_email=True)

        db.session.commit()

        flash("Inquiry updated successfully. Customer notification was logged.", "success")
        return redirect(url_for("admin_inquiry_detail", inquiry_id=inquiry.inquiry_id))

    return render_template("admin/inquiry_detail.html", inquiry=inquiry)


@app.route("/admin/inquiry/<int:inquiry_id>/ai-reply", methods=["POST"])
@login_required
def admin_ai_reply(inquiry_id):
    inquiry = Inquiry.query.get_or_404(inquiry_id)

    allowed, message = _ai_rate_limit("reply")

    if not allowed:
        return jsonify({"success": False, "error": message}), 429

    try:
        return jsonify(
            {
                "success": True,
                "type": "reply",
                "output": generate_ai_reply(_inquiry_payload(inquiry)),
            }
        )

    except AIServiceError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@app.route("/admin/inquiry/<int:inquiry_id>/summarize", methods=["POST"])
@login_required
def admin_ai_summarize(inquiry_id):
    inquiry = Inquiry.query.get_or_404(inquiry_id)

    allowed, message = _ai_rate_limit("summary")

    if not allowed:
        return jsonify({"success": False, "error": message}), 429

    try:
        return jsonify(
            {
                "success": True,
                "type": "summary",
                "output": summarize_inquiry(_inquiry_payload(inquiry)),
            }
        )

    except AIServiceError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@app.route("/admin/inquiry/<int:inquiry_id>/classify", methods=["POST"])
@login_required
def admin_ai_classify(inquiry_id):
    inquiry = Inquiry.query.get_or_404(inquiry_id)

    allowed, message = _ai_rate_limit("classify")

    if not allowed:
        return jsonify({"success": False, "error": message}), 429

    try:
        return jsonify(
            {
                "success": True,
                "type": "classification",
                "output": classify_inquiry(_inquiry_payload(inquiry)),
            }
        )

    except AIServiceError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@app.route("/admin/inquiry/<int:inquiry_id>/completion-notification", methods=["POST"])
@login_required
def admin_ai_completion_notification(inquiry_id):
    inquiry = Inquiry.query.get_or_404(inquiry_id)

    allowed, message = _ai_rate_limit("completion")

    if not allowed:
        return jsonify({"success": False, "error": message}), 429

    try:
        return jsonify(
            {
                "success": True,
                "type": "completion",
                "output": generate_completion_notification(inquiry.customer_name, inquiry.subject),
            }
        )

    except AIServiceError as exc:
        return jsonify({"success": False, "error": str(exc)}), 503


@app.route("/admin/inquiry/<int:inquiry_id>/delete", methods=["POST"])
@login_required
@require_roles("Super Admin")
def admin_delete_inquiry(inquiry_id):
    inquiry = Inquiry.query.get_or_404(inquiry_id)

    db.session.delete(inquiry)
    db.session.commit()

    flash("Inquiry deleted successfully.", "success")

    return redirect(url_for("admin_inquiries"))


@app.route("/admin/customers")
@login_required
def admin_customers():
    search = request.args.get("search", "").strip()

    base_query = Customer.query

    if search:
        like = f"%{search}%"

        base_query = base_query.filter(
            db.or_(
                Customer.full_name.ilike(like),
                Customer.email.ilike(like),
                Customer.phone.ilike(like),
                Customer.company.ilike(like),
            )
        )

    customers = (
        db.session.query(
            Customer,
            db.func.count(Inquiry.inquiry_id).label("total_inquiries"),
            db.func.max(Inquiry.created_at).label("last_inquiry"),
            db.func.sum(
                db.case(
                    (Inquiry.status.in_(["Pending", "Under Review"]), 1),
                    else_=0,
                )
            ).label("open_count"),
        )
        .select_from(Customer)
        .outerjoin(Inquiry)
        .filter(Customer.id.in_(base_query.with_entities(Customer.id)))
        .group_by(Customer.id)
        .order_by(Customer.created_at.desc())
        .all()
    )

    total_customers = Customer.query.count()
    active_customers = db.session.query(Customer.id).join(Inquiry).distinct().count()

    open_customer_count = (
        db.session.query(Customer.id)
        .join(Inquiry)
        .filter(Inquiry.status.in_(["Pending", "Under Review"]))
        .distinct()
        .count()
    )

    total_inquiries = Inquiry.query.count()

    return render_template(
        "admin/customers.html",
        customers=customers,
        search=search,
        total_customers=total_customers,
        active_customers=active_customers,
        open_customer_count=open_customer_count,
        total_inquiries=total_inquiries,
    )


@app.route("/admin/customer/<int:customer_id>")
@login_required
def admin_customer_detail(customer_id):
    customer = Customer.query.get_or_404(customer_id)

    inquiries = Inquiry.query.filter_by(customer_id=customer.id).order_by(Inquiry.created_at.desc()).all()

    return render_template(
        "admin/customer_detail.html",
        customer=customer,
        inquiries=inquiries,
    )


@app.route("/admin/attachment/<int:inquiry_id>")
@login_required
def admin_attachment(inquiry_id):
    inquiry = Inquiry.query.get_or_404(inquiry_id)
    if not inquiry.attachment_filename:
        abort(404)

    return send_from_directory(
        app.config["UPLOAD_FOLDER"],
        inquiry.attachment_filename,
        as_attachment=False,
        download_name=inquiry.attachment_original or inquiry.attachment_filename,
    )


@app.route("/admin/events", methods=["GET", "POST"])
@login_required
def admin_events():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        event_date = request.form.get("event_date", "")
        location = request.form.get("location", "Online")
        description = request.form.get("description", "")
        status = request.form.get("status", "Upcoming")

        if title and event_date and description:
            db.session.add(
                Event(
                    title=title,
                    event_date=datetime.strptime(event_date, "%Y-%m-%d").date(),
                    location=location,
                    description=description,
                    status=status,
                )
            )

            db.session.commit()

            flash("Event added successfully.", "success")
            return redirect(url_for("admin_events"))

        flash("Please complete all required event fields.", "error")

    return render_template(
        "admin/events.html",
        events=Event.query.order_by(Event.event_date.asc()).all(),
    )


@app.route("/admin/events/<int:event_id>/delete", methods=["POST"])
@login_required
def admin_delete_event(event_id):
    event = Event.query.get_or_404(event_id)

    db.session.delete(event)
    db.session.commit()

    flash("Event deleted successfully.", "success")

    return redirect(url_for("admin_events"))


@app.route("/admin/settings", methods=["GET", "POST"])
@login_required
def admin_settings():
    if request.method == "POST":
        action = request.form.get("action", "password")

        if action == "profile":
            current_user.name = request.form.get("name", current_user.name).strip() or current_user.name

            if has_role("Super Admin"):
                selected_role = request.form.get("role")

                if selected_role in ["Super Admin", "Support Staff", "Viewer"]:
                    current_user.role = selected_role

            db.session.commit()
            flash("Admin profile updated successfully.", "success")

        elif action == "email_test":
            to_email = request.form.get("test_email", current_user.email).strip().lower()

            ok, err = send_email(
                to_email,
                "AI InquiryX SMTP test",
                "Your AI InquiryX email setup is working.",
            )

            flash(
                "Test email sent successfully." if ok else f"Email test failed: {err}",
                "success" if ok else "error",
            )

        else:
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")

            if not current_user.check_password(current_password):
                flash("Current password is incorrect.", "error")
            elif len(new_password) < 10:
                flash("New password must be at least 10 characters.", "error")
            else:
                current_user.set_password(new_password)
                db.session.commit()

                flash("Password updated successfully.", "success")

    mail_summary = {
        "MAIL_SERVER": os.getenv("MAIL_SERVER", "smtp.gmail.com"),
        "MAIL_PORT": os.getenv("MAIL_PORT", "587"),
        "MAIL_USERNAME": os.getenv("MAIL_USERNAME", ""),
        "MAIL_DEFAULT_SENDER": os.getenv("MAIL_DEFAULT_SENDER", ""),
        "TWILIO_FROM_NUMBER": os.getenv("TWILIO_FROM_NUMBER", ""),
    }

    return render_template("admin/settings.html", mail_summary=mail_summary)


@app.route("/admin/notifications/mark-read", methods=["POST"])
@login_required
def admin_mark_notifications_read():
    Notification.query.filter_by(is_read=False).update({"is_read": True})
    db.session.commit()

    return jsonify({"success": True})

@app.route("/admin/notifications/<int:notification_id>/delete", methods=["POST"])
@login_required
def admin_delete_notification(notification_id):
    notification = db.session.get(Notification, notification_id)

    if not notification:
        return jsonify({"success": False, "error": "Notification not found"}), 404

    db.session.delete(notification)
    db.session.commit()

    unread_count = Notification.query.filter_by(is_read=False).count()

    return jsonify({
        "success": True,
        "unread_count": unread_count
    })


@app.route("/admin/export/excel")
@login_required
def admin_export_excel():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Inquiries"

    ws.append(
        [
            "Tracking ID",
            "Customer",
            "Email",
            "Phone",
            "Category",
            "Subject",
            "Priority",
            "Status",
            "Rating",
            "Created",
            "Updated",
        ]
    )

    for item in Inquiry.query.order_by(Inquiry.created_at.desc()).all():
        ws.append(
            [
                item.tracking_id,
                item.customer_name,
                item.email,
                item.phone,
                item.category,
                item.subject,
                item.priority,
                item.status,
                item.rating,
                item.created_at.strftime("%Y-%m-%d %H:%M") if item.created_at else "",
                item.updated_at.strftime("%Y-%m-%d %H:%M") if item.updated_at else "",
            ]
        )

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="inquiryx_inquiries.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/admin/export/pdf")
@login_required
def admin_export_pdf():
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    output = BytesIO()
    c = canvas.Canvas(output, pagesize=letter)

    width, height = letter
    y = height - 40

    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, y, "AI InquiryX - Inquiry Report")

    y -= 30
    c.setFont("Helvetica", 9)

    for item in Inquiry.query.order_by(Inquiry.created_at.desc()).limit(60).all():
        line = (
            f"{item.tracking_id} | "
            f"{item.customer_name} | "
            f"{item.category} | "
            f"{item.priority} | "
            f"{item.status} | "
            f"{item.created_at:%Y-%m-%d}"
        )

        c.drawString(40, y, line[:120])
        y -= 16

        if y < 50:
            c.showPage()
            y = height - 40
            c.setFont("Helvetica", 9)

    c.save()
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="inquiryx_report.pdf",
        mimetype="application/pdf",
    )


@app.route("/chatbot", methods=["POST"])
def chatbot():
    data = request.get_json(silent=True) or {}
    message = (data.get("message", "") or "").strip()
    low = message.lower()

    if not message:
        return jsonify(
            {
                "reply": "Please type a question and I will help you before you submit an inquiry."
            }
        )

    cleaned_message = " ".join("".join(ch if ch.isalnum() or ch.isspace() else " " for ch in low).split())
    greeting_words = {"hi", "hii", "hello", "hey", "hy", "yo", "namaste", "namaskar"}

    if cleaned_message in greeting_words or (len(cleaned_message.split()) <= 3 and any(word in greeting_words for word in cleaned_message.split())):
        reply = "Hi! I’m your AI InquiryX assistant. I can help you submit an inquiry, track a ticket, check events, or write a clear support message."

    elif any(word in low for word in ["category", "choose", "type"]):
        reply = "Tell me your issue briefly. Common categories are Technical, Billing, Complaint, Feedback, and General."

    elif "track" in low or "status" in low:
        reply = "Use the Track Inquiry page with your tracking ID plus email or phone number to see status, submitted date, updated date, and admin reply."

    elif "write" in low or "message" in low:
        reply = "A good inquiry should include what happened, when it happened, screenshots or attachment if available, and what result you expect."

    elif "submit" in low or "complaint" in low:
        reply = "Open Submit Inquiry, enter your name, email, phone if desired, category, message, and choose email/phone/both for updates."

    elif "admin" in low:
        reply = "Admins can log in at /admin/login to search, filter, reply, update status, and mark inquiries as completed."

    else:
        try:
            reply = generate_ai_reply(
                {
                    "customer_name": "Website visitor",
                    "subject": "Pre-inquiry help",
                    "message": message,
                    "category": "General",
                    "status": "Draft",
                }
            )
        except Exception:
            reply = "I can help you submit, track, or write a clearer inquiry. Please describe your issue in one or two sentences."

    db.session.add(
        AIChatHistory(
            user_message=message[:2000],
            assistant_reply=reply[:4000],
        )
    )

    db.session.commit()

    return jsonify({"reply": reply})


@app.cli.command("init-db")
def init_db():
    db.drop_all()
    db.create_all()

    admin = Admin(
        name="InquiryX Admin",
        email="admin@inquiryx.com",
        role="Super Admin",
    )
    admin_password = os.getenv("ADMIN_DEFAULT_PASSWORD") or (secrets.token_urlsafe(14) + "A1!")
    admin.set_password(admin_password)

    db.session.add(admin)

    sample_events = [
        Event(
            title="Customer Support Automation Workshop",
            event_date=date(2026, 7, 15),
            location="Online Webinar",
            description="Learn how AI improves inquiry routing, response quality, and support team productivity.",
        ),
        Event(
            title="Inquiry Management Training Session",
            event_date=date(2026, 7, 22),
            location="Training Lab",
            description="Practical admin training for ticket handling, status updates, and response workflows.",
        ),
    ]

    db.session.add_all(sample_events)

    customer = Customer(
        full_name="Riya Sharma",
        email="riya@example.com",
        phone="9800000000",
        company="Bright Retail",
    )

    db.session.add(customer)
    db.session.flush()

    db.session.add_all(
        [
            Inquiry(
                tracking_id=create_tracking_id(),
                customer_id=customer.id,
                customer_name="Riya Sharma",
                email="riya@example.com",
                phone="9800000000",
                contact_preference="Both",
                category="Technical",
                subject="Cannot access tracking panel",
                message="I cannot see my support ticket status.",
                priority="High",
                status="Under Review",
            ),
            Inquiry(
                tracking_id=create_tracking_id(),
                customer_name="Nabin Lawati",
                email="nabin@example.com",
                phone="9700000000",
                category="Complaint",
                subject="Delayed response",
                message="My last inquiry has not been answered yet.",
                priority="Urgent",
                status="Pending",
            ),
            Inquiry(
                tracking_id=create_tracking_id(),
                customer_name="Sita Rai",
                email="sita@example.com",
                phone="9600000000",
                category="Billing",
                subject="Invoice correction",
                message="Please correct my billing details.",
                priority="Normal",
                status="Completed",
                admin_response="Your billing details have been updated.",
            ),
        ]
    )

    db.session.commit()

    print("Database initialized.")
    print("Default admin created. Set a secure password in production.")


def ensure_schema():
    """Auto-create and auto-upgrade PostgreSQL tables safely."""
    db.create_all()

    inspector = inspect(db.engine)
    table_names = inspector.get_table_names()
    dialect = db.engine.dialect.name

    if dialect != "postgresql":
        raise RuntimeError("This project is configured for PostgreSQL only.")

    if "inquiries" in table_names:
        existing = {col["name"] for col in inspector.get_columns("inquiries")}

        varchar_24 = "VARCHAR(24)"
        varchar_20 = "VARCHAR(20)"
        varchar_255 = "VARCHAR(255)"
        timestamp_type = "TIMESTAMP"

        additions = {
            "tracking_id": f"ALTER TABLE inquiries ADD COLUMN tracking_id {varchar_24}",
            "contact_preference": f"ALTER TABLE inquiries ADD COLUMN contact_preference {varchar_20} DEFAULT 'Email'",
            "attachment_filename": f"ALTER TABLE inquiries ADD COLUMN attachment_filename {varchar_255}",
            "attachment_original": f"ALTER TABLE inquiries ADD COLUMN attachment_original {varchar_255}",
            "rating": "ALTER TABLE inquiries ADD COLUMN rating INTEGER",
            "rating_comment": "ALTER TABLE inquiries ADD COLUMN rating_comment TEXT",
            "rated_at": f"ALTER TABLE inquiries ADD COLUMN rated_at {timestamp_type}",
        }

        for column, sql in additions.items():
            if column not in existing:
                db.session.execute(text(sql))

        db.session.commit()

    if "admins" in table_names:
        admin_cols = {col["name"] for col in inspector.get_columns("admins")}

        if "role" not in admin_cols:
            db.session.execute(
                text("ALTER TABLE admins ADD COLUMN role VARCHAR(40) DEFAULT 'Super Admin'")
            )
            db.session.commit()

    if "notifications" in table_names:
        note_cols = {col["name"] for col in inspector.get_columns("notifications")}

        if "is_read" not in note_cols:
            db.session.execute(
                text("ALTER TABLE notifications ADD COLUMN is_read BOOLEAN DEFAULT FALSE")
            )
            db.session.commit()

    if "inquiries" in table_names:
        for inquiry in Inquiry.query.all():
            changed = False

            if not inquiry.tracking_id:
                inquiry.tracking_id = create_tracking_id()
                changed = True

            normalized = normalize_status(inquiry.status)

            if normalized != inquiry.status:
                inquiry.status = normalized
                changed = True

            if not inquiry.contact_preference:
                inquiry.contact_preference = "Email"
                changed = True

            if changed:
                db.session.add(inquiry)

        db.session.commit()

    if not Admin.query.filter_by(email="admin@inquiryx.com").first():
        default_admin = Admin(
            name="InquiryX Admin",
            email="admin@inquiryx.com",
            role="Super Admin"
        )

        admin_password = os.getenv("ADMIN_DEFAULT_PASSWORD")

        if not admin_password:
            raise RuntimeError(
                "ADMIN_DEFAULT_PASSWORD is missing. Add it inside your .env file."
            )

        default_admin.set_password(admin_password)
        db.session.add(default_admin)
        db.session.commit()

if __name__ == "__main__":
    with app.app_context():
        ensure_schema()

    print("Starting AI InquiryX Flask server...")
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true"
    )