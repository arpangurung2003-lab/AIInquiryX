# AI InquiryX

AI InquiryX is a professional customer inquiry management system built with **Python Flask**, **HTML**, **CSS**, **JavaScript**, and **PostgreSQL**. It allows customers to submit support inquiries, track ticket progress, receive status updates, and interact with an AI-powered help assistant. Admins can manage inquiries, update statuses, view customer details, use AI assistance, manage events, and export reports.

## Features

### Public Website

* Modern responsive homepage
* About, Services, Gallery, Events, Blog, and Contact pages
* Professional smoke/platinum UI theme
* Poppins and Inter Google Fonts
* Smooth hover animations and premium card effects
* Floating AI chatbot assistant
* Contact form with database saving

### Customer Inquiry System

* Submit inquiry form
* Tracking ID generation
* Inquiry status tracking using tracking ID plus email or phone
* Optional file attachment upload
* Customer rating for completed inquiries
* Customer login using email and tracking ID
* Customer dashboard to view previous inquiries
* Reopen completed inquiries

### Admin Dashboard

* Secure admin login and registration with invite code
* Dashboard statistics and inquiry overview
* Inquiry list and detailed inquiry management
* Update inquiry status
* Add admin responses
* Add private internal notes
* View status history
* Manage customers
* Manage events
* View contact messages
* Export reports to Excel and PDF
* Protected attachment preview
* Logout option in admin sidebar

### AI Features

* AI chatbot support
* AI reply generation for admins
* Inquiry summarization
* Priority classification
* Completion notification drafting
* Gemini AI integration through `services/gemini_service.py`

### Security Improvements

* `.env` excluded from GitHub
* `.env.example` included for setup guidance
* PostgreSQL database required through `DATABASE_URL`
* Protected uploads folder
* CSRF protection support
* Secure tracking flow requiring tracking ID plus contact detail
* Password reset through email token
* Debug mode disabled by default for safer deployment

## Technologies Used

* Python Flask
* Flask-SQLAlchemy
* Flask-Login
* PostgreSQL
* HTML5
* CSS3
* JavaScript
* Google Gemini AI
* SMTP email notification
* OpenPyXL for Excel export
* ReportLab for PDF export
* Gunicorn for production server

## Installation

```bash
git clone https://github.com/arpangurung2003-lab/AIInquiryX
cd AIInquiryX
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Environment Setup

Create a `.env` file in the project root by copying `.env.example`.

```env
SECRET_KEY=change-this-to-a-long-random-secret-key
DATABASE_URL=postgresql://postgres:your_password@localhost:5432/inquiryx_db

ADMIN_INVITE_CODE=change-this-admin-invite-code
ADMIN_DEFAULT_PASSWORD=change-this-strong-temporary-admin-password

MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-gmail-app-password
MAIL_DEFAULT_SENDER=your-email@gmail.com
ADMIN_NOTIFY_EMAIL=admin@example.com

AI_PROVIDER=gemini
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-2.0-flash

MAX_UPLOAD_MB=8
FLASK_DEBUG=false
SESSION_COOKIE_SECURE=false
```

Important: never upload `.env` to GitHub because it may contain passwords, API keys, and private configuration.

## Database Setup

AI InquiryX is configured to use **PostgreSQL only**.

Make sure PostgreSQL is installed and running. Create a database named:

```text
inquiryx_db
```

Then make sure your `.env` file contains a valid PostgreSQL connection string:

```env
DATABASE_URL=postgresql://postgres:your_password@localhost:5432/inquiryx_db
```

Initialize the database:

```bash
flask --app app.py init-db
```

If `DATABASE_URL` is missing or PostgreSQL is not configured correctly, the application will stop with an error. This prevents the project from accidentally using the wrong database.

## Run the Project

```bash
python app.py
```

Open the website in your browser:

```text
http://127.0.0.1:5000
```

## Main Pages

### Public Pages

```text
/
/about
/services
/gallery
/events
/blog
/contact
/submit-inquiry
/track-inquiry
```

### Customer Pages

```text
/customer/login
/customer/dashboard
/customer/tracking-portal
```

### Admin Pages

```text
/admin/login
/admin/register
/admin/dashboard
/admin/inquiries
/admin/customers
/admin/events
/admin/settings
```

## GitHub Commands for Future Updates

After changing files in VS Code, run:

```powershell
cd D:\AIInquiryX
git status
git add .
git commit -m "Update AI InquiryX website"
git push
```

## Production Notes

Before making the website public:

* Use a strong `SECRET_KEY`
* Set `FLASK_DEBUG=false`
* Use PostgreSQL with a secure production database URL
* Use a proper Gmail app password or SMTP service
* Keep API keys private
* Enable HTTPS on the hosting platform
* Set `SESSION_COOKIE_SECURE=true` on HTTPS hosting
* Use Gunicorn or another production WSGI server

Example production command:

```bash
gunicorn app:app
```

## Project Status

AI InquiryX is ready as a polished Flask-based customer inquiry management project with public pages, customer tracking, admin dashboard, AI assistance, protected uploads, and report export features.

Further improvements can include full threaded messaging, advanced role permissions, background email jobs, automated tests, and more advanced analytics.

## Author

Developed by **Arpan Gurung**.
