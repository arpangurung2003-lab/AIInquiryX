import json
import os
from pathlib import Path
from typing import Any, Dict, Union

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

load_dotenv(dotenv_path=ENV_PATH, override=True)


class AIServiceError(Exception):
    """Raised when the AI helper cannot complete a request safely."""


def _clean_env_value(value: str) -> str:
    value = (value or "").strip()
    value = value.replace("\ufeff", "")
    value = value.strip().strip('"').strip("'").strip()
    return value


GEMINI_MODEL = _clean_env_value(os.getenv("GEMINI_MODEL", "gemini-2.0-flash"))
OPENAI_MODEL = _clean_env_value(os.getenv("OPENAI_MODEL", "gpt-4o-mini"))


def _format_inquiry(inquiry: Union[str, Dict[str, Any]]) -> str:
    if isinstance(inquiry, dict):
        return "\n".join(
            [
                f"Inquiry ID: {inquiry.get('id', '')}",
                f"Tracking ID: {inquiry.get('tracking_id', '')}",
                f"Customer: {inquiry.get('customer_name', inquiry.get('name', ''))}",
                f"Email: {inquiry.get('email', '')}",
                f"Phone: {inquiry.get('phone', '')}",
                f"Category: {inquiry.get('category', '')}",
                f"Subject: {inquiry.get('subject', '')}",
                f"Current priority: {inquiry.get('priority', '')}",
                f"Current status: {inquiry.get('status', '')}",
                f"Message: {inquiry.get('message', '')}",
            ]
        )

    return str(inquiry)


def _local_reply(inquiry_message: Union[str, Dict[str, Any]]) -> str:
    if isinstance(inquiry_message, dict):
        name = inquiry_message.get("customer_name") or inquiry_message.get("name") or "Customer"
        subject = inquiry_message.get("subject") or inquiry_message.get("category") or "your inquiry"
    else:
        name = "Customer"
        subject = "your inquiry"

    return (
        f"Dear {name},\n\n"
        f"Thank you for contacting AI InquiryX regarding {subject}. "
        "We have received your inquiry and our support team will review it carefully. "
        "We will update you as soon as possible with the next steps.\n\n"
        "Thank you for your patience.\n\n"
        "Best regards,\n"
        "AI InquiryX Support Team"
    )


def _local_summary(inquiry_message: Union[str, Dict[str, Any]]) -> str:
    text = _format_inquiry(inquiry_message)

    return (
        "• Customer inquiry received and needs admin review.\n"
        "• Main message:\n"
        f"  {text[:350]}{'...' if len(text) > 350 else ''}\n"
        "• Suggested next step: review the customer message, update status, and send a clear response."
    )


def _local_classify(inquiry_message: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    text = _format_inquiry(inquiry_message).lower()

    urgency = "low"
    priority = "Normal"
    inquiry_type = "general question"

    urgent_words = [
        "urgent",
        "immediately",
        "asap",
        "not working",
        "cannot access",
        "failed",
        "error",
        "delayed",
        "problem",
        "issue",
    ]
    billing_words = [
        "payment",
        "invoice",
        "bill",
        "price",
        "refund",
        "charge",
        "paid",
        "money",
    ]
    technical_words = [
        "login",
        "website",
        "dashboard",
        "bug",
        "error",
        "technical",
        "access",
        "password",
        "account",
    ]

    if any(word in text for word in urgent_words):
        urgency = "high"
        priority = "Urgent"

    if any(word in text for word in billing_words):
        inquiry_type = "billing issue"
    elif any(word in text for word in technical_words):
        inquiry_type = "technical issue"

    return {
        "inquiry_type": inquiry_type,
        "urgency": urgency,
        "short_admin_note": "Review this inquiry and respond with a clear solution or next step.",
        "recommended_priority": priority,
    }


def _local_completion_notification(customer_name: str, inquiry_subject: str) -> str:
    customer_name = customer_name or "Customer"
    inquiry_subject = inquiry_subject or "your inquiry"

    return (
        f"Dear {customer_name},\n\n"
        f"Your inquiry about {inquiry_subject} has been marked as completed. "
        "Please reply if you need any further help.\n\n"
        "Best regards,\n"
        "AI InquiryX Support Team"
    )


def _ask_openai(system_instruction: str, user_content: str, *, as_json: bool = False) -> Any:
    try:
        from openai import OpenAI
    except Exception:
        raise AIServiceError("OpenAI package is not installed.")

    api_key = _clean_env_value(os.getenv("OPENAI_API_KEY", ""))

    if not api_key or api_key.startswith("your-"):
        raise AIServiceError("OPENAI_API_KEY is missing.")

    client = OpenAI(api_key=api_key)

    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_content},
        ],
    )

    output = getattr(response, "output_text", "") or ""
    output = output.strip()

    if not output:
        raise AIServiceError("OpenAI returned an empty response.")

    if as_json:
        cleaned = output.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"raw": output}

    return output


def _resolve_gemini_model(genai) -> str:
    preferred_names = [
        GEMINI_MODEL,
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-flash-latest",
        "gemini-pro",
    ]

    try:
        available = []

        for model in genai.list_models():
            methods = getattr(model, "supported_generation_methods", []) or []

            if "generateContent" in methods:
                name = getattr(model, "name", "")

                if name.startswith("models/"):
                    name = name.replace("models/", "", 1)

                available.append(name)

        for preferred in preferred_names:
            if preferred in available:
                return preferred

        if available:
            return available[0]

    except Exception:
        pass

    return GEMINI_MODEL


def _ask_gemini(system_instruction: str, user_content: str, *, as_json: bool = False) -> Any:
    try:
        import google.generativeai as genai
    except Exception:
        raise AIServiceError("Gemini package is not installed.")

    api_key = _clean_env_value(os.getenv("GEMINI_API_KEY", ""))

    if not api_key or api_key.startswith("your-"):
        raise AIServiceError("GEMINI_API_KEY is missing.")

    genai.configure(api_key=api_key)

    selected_model = _resolve_gemini_model(genai)
    model = genai.GenerativeModel(selected_model)

    prompt = f"""
{system_instruction}

Customer inquiry:
{user_content}
"""

    response = model.generate_content(prompt)
    output = (getattr(response, "text", "") or "").strip()

    if not output:
        raise AIServiceError("Gemini returned an empty response.")

    if as_json:
        cleaned = output.replace("```json", "").replace("```", "").strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {"raw": output}

    return output


def _ask_configured_ai(system_instruction: str, user_content: str, *, as_json: bool = False) -> Any:
    provider = _clean_env_value(os.getenv("AI_PROVIDER", "none")).lower()

    if provider == "none":
        raise AIServiceError("AI_PROVIDER is set to none.")

    if provider == "openai":
        return _ask_openai(system_instruction, user_content, as_json=as_json)

    if provider == "gemini":
        return _ask_gemini(system_instruction, user_content, as_json=as_json)

    raise AIServiceError(f"Unsupported AI_PROVIDER: {provider}")


def generate_ai_reply(inquiry_message: Union[str, Dict[str, Any]]) -> str:
    try:
        return _ask_configured_ai(
            "You help customer-support admins write polished replies. "
            "Draft a helpful, empathetic, concise response. "
            "Do not claim the issue is fixed unless the admin says so. "
            "Do not send anything automatically; this is only a draft for admin review.",
            _format_inquiry(inquiry_message),
        )
    except Exception:
        return _local_reply(inquiry_message)


def summarize_inquiry(inquiry_message: Union[str, Dict[str, Any]]) -> str:
    try:
        return _ask_configured_ai(
            "Summarize this customer inquiry in 3 to 5 bullet points. "
            "Include the core problem, customer expectation, and any risk.",
            _format_inquiry(inquiry_message),
        )
    except Exception:
        return _local_summary(inquiry_message)


def classify_inquiry(inquiry_message: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    try:
        result = _ask_configured_ai(
            "Classify the inquiry. Return only valid JSON with keys: "
            "inquiry_type, urgency, short_admin_note, recommended_priority. "
            "Allowed inquiry_type values: technical issue, billing issue, general question, "
            "urgent complaint, solved request. "
            "Allowed urgency values: low, medium, high.",
            _format_inquiry(inquiry_message),
            as_json=True,
        )

        if isinstance(result, dict):
            return {
                "inquiry_type": result.get("inquiry_type", "general question"),
                "urgency": result.get("urgency", "low"),
                "short_admin_note": result.get(
                    "short_admin_note",
                    "Review this inquiry and respond with a clear solution or next step.",
                ),
                "recommended_priority": result.get("recommended_priority", "Normal"),
            }

        return _local_classify(inquiry_message)

    except Exception:
        return _local_classify(inquiry_message)


def generate_completion_notification(customer_name: str, inquiry_subject: str) -> str:
    try:
        return _ask_configured_ai(
            "Write a short professional notification telling the customer their inquiry has been completed. "
            "Keep it friendly and include that they can reply if they need more help.",
            f"Customer name: {customer_name}\nInquiry subject: {inquiry_subject}",
        )
    except Exception:
        return _local_completion_notification(customer_name, inquiry_subject)