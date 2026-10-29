"""Model boundary: only fixed application-owned instructions can cross it."""

from enum import StrEnum


class Capability(StrEnum):
    SPENDING = "spending"
    INCOME = "income"
    CASHFLOW = "cashflow"
    NET_WORTH = "net_worth"
    BUDGET_REVIEW = "budget_review"
    TRANSACTION_DRAFT = "transaction_draft"


_PROMPTS: dict[Capability, str] = {
    Capability.SPENDING: "Explain how to review recorded spending in a finance app.",
    Capability.INCOME: "Explain how to review recorded income in a finance app.",
    Capability.CASHFLOW: "Explain the meaning of cash flow in a finance app.",
    Capability.NET_WORTH: "Explain the meaning of net worth in a finance app.",
    Capability.BUDGET_REVIEW: "Explain how to review a proposed budget change.",
    Capability.TRANSACTION_DRAFT: "Explain how to review a proposed transaction.",
}

SYSTEM_PROMPT = (
    "Give a short, generic explanation. Do not invent figures, personal details, "
    "specific records, or actions taken. Do not request or use tools."
)


def model_prompt(capability: Capability) -> str:
    """Never accept a question, financial value, label, or identifier as model input."""
    if not isinstance(capability, Capability):
        raise ValueError("Unsupported capability")
    return _PROMPTS[capability]
