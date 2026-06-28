from datetime import datetime, timedelta
from app import app, db, Customer, Inquiry, create_tracking_id


sample_customers = [
    {
        "full_name": "Sarah Lama",
        "email": "sarah.lama@example.com",
        "phone": "+977 9800000001",
        "company": "Bright Retail",
        "inquiries": [
            {
                "category": "Technical",
                "subject": "Unable to track my support ticket",
                "message": "I submitted an inquiry but cannot see the updated status on the tracking page.",
                "priority": "High",
                "status": "Under Review",
            }
        ],
    },
    {
        "full_name": "Michael Reed",
        "email": "michael.reed@example.com",
        "phone": "+977 9800000002",
        "company": "Himalayan Coffee",
        "inquiries": [
            {
                "category": "Complaint",
                "subject": "Delayed response from support team",
                "message": "I contacted support two days ago but still have not received a reply.",
                "priority": "Urgent",
                "status": "Pending",
            }
        ],
    },
    {
        "full_name": "David Shrestha",
        "email": "david.shrestha@example.com",
        "phone": "+977 9800000003",
        "company": "Everest Supplies",
        "inquiries": [
            {
                "category": "Billing",
                "subject": "Invoice correction request",
                "message": "The company name on my invoice is incorrect. Please update it and resend.",
                "priority": "Normal",
                "status": "Completed",
            }
        ],
    },
    {
        "full_name": "Anurodh Sapkota",
        "email": "anurodh.sapkota@example.com",
        "phone": "+977 9800000004",
        "company": "CloudTech Nepal",
        "inquiries": [
            {
                "category": "Technical",
                "subject": "Login issue in customer portal",
                "message": "The customer portal is not accepting my email and tracking ID.",
                "priority": "High",
                "status": "In Progress",
            }
        ],
    },
    {
        "full_name": "Maya Tamang",
        "email": "maya.tamang@example.com",
        "phone": "+977 9800000005",
        "company": "Tamang Boutique",
        "inquiries": [
            {
                "category": "Feedback",
                "subject": "Suggestion for faster ticket updates",
                "message": "It would be helpful if customers receive more frequent email updates.",
                "priority": "Low",
                "status": "Fixed",
            }
        ],
    },
    {
        "full_name": "Prakash Thapa",
        "email": "prakash.thapa@example.com",
        "phone": "+977 9800000006",
        "company": "Thapa Electronics",
        "inquiries": [
            {
                "category": "General",
                "subject": "Need help understanding inquiry process",
                "message": "I want to know how long it usually takes to complete an inquiry.",
                "priority": "Normal",
                "status": "Under Review",
            }
        ],
    },
]


with app.app_context():
    for data in sample_customers:
        customer = Customer.query.filter_by(email=data["email"]).first()

        if not customer:
            customer = Customer(
                full_name=data["full_name"],
                email=data["email"],
                phone=data["phone"],
                company=data["company"],
            )
            db.session.add(customer)
            db.session.flush()

        for item in data["inquiries"]:
            existing = Inquiry.query.filter_by(
                email=data["email"],
                subject=item["subject"],
            ).first()

            if existing:
                continue

            inquiry = Inquiry(
                tracking_id=create_tracking_id(),
                customer_id=customer.id,
                customer_name=data["full_name"],
                email=data["email"],
                phone=data["phone"],
                contact_preference="Email",
                category=item["category"],
                subject=item["subject"],
                message=item["message"],
                priority=item["priority"],
                status=item["status"],
                created_at=datetime.utcnow() - timedelta(days=sample_customers.index(data)),
                updated_at=datetime.utcnow(),
            )

            if item["status"] in ["Fixed", "Completed"]:
                inquiry.admin_response = "Thank you for contacting AI InquiryX. Your inquiry has been reviewed and resolved by our support team."

            db.session.add(inquiry)

    db.session.commit()
    print("Sample customers and inquiries added successfully.")