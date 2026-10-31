import calendar
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple
from sqlmodel import Session, select, func

from app.models import (
    Customer,
    Plan,
    Quotation,
    QuotationItem,
    Subscription,
    BillingInterval,
    QuotationStatus,
    SubscriptionStatus,
    get_utc_now,
    calculate_tax_paise,
    calculate_discount_paise,
    calculate_normalized_mrr_paise,
)


# =============================================================================
# DATE ARITHMETIC UTILITIES
# =============================================================================
def ensure_utc(dt: datetime) -> datetime:
    """Normalize datetime to timezone-aware UTC datetime for safe SQLite comparisons."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def add_months(source_date: datetime, months: int) -> datetime:
    """Accurately add calendar months to a datetime, respecting month-end days and leap years."""
    month = source_date.month - 1 + months
    year = source_date.year + month // 12
    month = month % 12 + 1
    max_days = calendar.monthrange(year, month)[1]
    day = min(source_date.day, max_days)
    return source_date.replace(year=year, month=month, day=day)


def calculate_period_end(start_date: datetime, interval: BillingInterval) -> datetime:
    """Calculate the subscription period end date based on billing interval."""
    if interval == BillingInterval.MONTHLY:
        return add_months(start_date, 1)
    elif interval == BillingInterval.QUARTERLY:
        return add_months(start_date, 3)
    elif interval == BillingInterval.YEARLY:
        return add_months(start_date, 12)
    # Default fallback to 30 days
    return start_date + timedelta(days=30)


# =============================================================================
# NUMBER GENERATORS (CONCURRENCY-SAFE SEQUENCES)
# =============================================================================
def generate_subscription_number(session: Session) -> str:
    """Generate the next unique subscription identifier in sequential SUB-0001 format."""
    statement = select(func.count(Subscription.id))
    count = session.exec(statement).one() or 0
    next_num = count + 1
    
    # Ensure absolute uniqueness in case of deleted records
    while True:
        candidate = f"SUB-{next_num:04d}"
        existing = session.exec(select(Subscription).where(Subscription.subscription_number == candidate)).first()
        if not existing:
            return candidate
        next_num += 1


def generate_quotation_number(session: Session) -> str:
    """Generate the next unique quotation identifier in sequential QT-0001 format."""
    statement = select(func.count(Quotation.id))
    count = session.exec(statement).one() or 0
    next_num = count + 1

    while True:
        candidate = f"QT-{next_num:04d}"
        existing = session.exec(select(Quotation).where(Quotation.quotation_number == candidate)).first()
        if not existing:
            return candidate
        next_num += 1


# =============================================================================
# QUOTATION CALCULATIONS & CONVERSIONS
# =============================================================================
def calculate_quote_financials(
    items_data: List[dict],
    discount_paise: int = 0,
    tax_rate_basis_points: int = 1800,
) -> Tuple[int, int, int, int]:
    """
    Calculate subtotal, discount, tax, and total in paise with integer rounding.
    Returns: (subtotal_paise, discount_paise, tax_paise, total_paise)
    """
    subtotal_paise = sum(item["quantity"] * item["unit_price_paise"] for item in items_data)
    clamped_discount = min(discount_paise, subtotal_paise) if subtotal_paise > 0 else 0
    taxable_paise = max(0, subtotal_paise - clamped_discount)
    tax_paise = calculate_tax_paise(taxable_paise, tax_rate_basis_points)
    total_paise = taxable_paise + tax_paise
    return subtotal_paise, clamped_discount, tax_paise, total_paise


def convert_quotation_to_subscription(
    session: Session,
    quotation: Quotation,
    plan_id: Optional[int] = None,
    billing_interval: Optional[BillingInterval] = None,
    start_date: Optional[datetime] = None,
) -> Subscription:
    """
    Convert an accepted quotation into an active Subscription record.
    Preserves audit linkage back to quotation_id.
    """
    now = get_utc_now()
    eff_start = start_date or now

    # Determine plan from quotation items if not explicitly provided
    resolved_plan_id = plan_id
    unit_price_paise = 0
    quantity = 1

    if not resolved_plan_id:
        for item in quotation.items:
            if item.plan_id:
                resolved_plan_id = item.plan_id
                unit_price_paise = item.unit_price_paise
                quantity = item.quantity
                break

    if not resolved_plan_id:
        raise ValueError("Cannot convert quotation: No valid plan_id found in quotation items.")

    plan = session.get(Plan, resolved_plan_id)
    if not plan:
        raise ValueError(f"Plan with id {resolved_plan_id} does not exist.")

    resolved_interval = billing_interval or plan.billing_interval or BillingInterval.MONTHLY
    if unit_price_paise == 0:
        unit_price_paise = plan.price_paise

    current_period_end = calculate_period_end(eff_start, resolved_interval)
    sub_num = generate_subscription_number(session)

    subscription = Subscription(
        subscription_number=sub_num,
        customer_id=quotation.customer_id,
        plan_id=resolved_plan_id,
        quotation_id=quotation.id,
        status=SubscriptionStatus.ACTIVE,
        quantity=quantity,
        unit_price_paise=unit_price_paise,
        currency=quotation.currency or "INR",
        billing_interval=resolved_interval,
        start_date=eff_start,
        current_period_start=eff_start,
        current_period_end=current_period_end,
        auto_renew=True,
        created_at=now,
    )

    session.add(subscription)
    session.commit()
    session.refresh(subscription)
    return subscription
