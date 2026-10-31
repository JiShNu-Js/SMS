import os
from datetime import datetime, timedelta
from typing import List, Optional
import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Header, Request, status
from pydantic import BaseModel, Field, EmailStr
from sqlmodel import Session, select, func, or_

from app.db import get_session
from app.models import (
    Customer,
    CustomerStatus,
    Plan,
    Quotation,
    QuotationItem,
    QuotationStatus,
    Subscription,
    SubscriptionStatus,
    BillingInterval,
    get_utc_now,
    calculate_normalized_mrr_paise,
)
from app.services.subscription_service import (
    calculate_period_end,
    generate_subscription_number,
    generate_quotation_number,
    calculate_quote_financials,
    convert_quotation_to_subscription,
    ensure_utc,
)

# Root router for Member 3
router = APIRouter()

JWT_SECRET = os.getenv("JWT_SECRET", "brightloop_secret")
JWT_ALGORITHM = "HS256"


# =============================================================================
# PYDANTIC SCHEMAS
# =============================================================================

# --- Customer Schemas ---
class CustomerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: Optional[str] = None
    company_name: Optional[str] = None
    gstin: Optional[str] = None
    billing_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: str = "India"
    currency: str = "INR"
    user_id: Optional[int] = None


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    company_name: Optional[str] = None
    gstin: Optional[str] = None
    billing_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    status: Optional[CustomerStatus] = None


class CustomerRead(BaseModel):
    id: int
    user_id: Optional[int]
    name: str
    email: str
    phone: Optional[str]
    company_name: Optional[str]
    gstin: Optional[str]
    billing_address: Optional[str]
    city: Optional[str]
    state: Optional[str]
    postal_code: Optional[str]
    country: str
    currency: str
    status: CustomerStatus
    created_at: datetime
    updated_at: datetime
    active_subscriptions_count: int = 0
    quotations_count: int = 0


# --- Quotation Schemas ---
class QuotationItemCreate(BaseModel):
    description: str = Field(..., min_length=1)
    quantity: int = Field(default=1, ge=1)
    unit_price_paise: int = Field(..., ge=0)
    plan_id: Optional[int] = None


class QuotationCreate(BaseModel):
    customer_id: int
    expiry_days: int = Field(default=30, ge=1, le=365)
    discount_code_snapshot: Optional[str] = None
    discount_paise: int = Field(default=0, ge=0)
    tax_name_snapshot: Optional[str] = "GST"
    tax_rate_basis_points_snapshot: int = Field(default=1800, ge=0, le=10000)
    notes: Optional[str] = None
    items: List[QuotationItemCreate] = Field(..., min_items=1)


class QuotationUpdate(BaseModel):
    notes: Optional[str] = None
    expiry_date: Optional[datetime] = None
    discount_code_snapshot: Optional[str] = None
    discount_paise: Optional[int] = Field(default=None, ge=0)
    tax_rate_basis_points_snapshot: Optional[int] = Field(default=None, ge=0, le=10000)
    items: Optional[List[QuotationItemCreate]] = None


class QuotationItemRead(BaseModel):
    id: int
    quotation_id: int
    plan_id: Optional[int]
    description: str
    quantity: int
    unit_price_paise: int
    amount_paise: int


class QuotationRead(BaseModel):
    id: int
    quotation_number: str
    customer_id: int
    customer_name: Optional[str] = None
    issue_date: datetime
    expiry_date: datetime
    subtotal_paise: int
    discount_code_snapshot: Optional[str]
    discount_paise: int
    tax_name_snapshot: Optional[str]
    tax_rate_basis_points_snapshot: int
    tax_paise: int
    total_paise: int
    currency: str
    status: QuotationStatus
    notes: Optional[str]
    created_at: datetime
    items: List[QuotationItemRead] = []


# --- Subscription Schemas ---
class SubscriptionCreate(BaseModel):
    customer_id: int
    plan_id: int
    quantity: int = Field(default=1, ge=1)
    unit_price_paise: Optional[int] = Field(default=None, ge=0)
    billing_interval: Optional[BillingInterval] = None
    start_date: Optional[datetime] = None
    auto_renew: bool = True
    quotation_id: Optional[int] = None
    status: Optional[SubscriptionStatus] = SubscriptionStatus.ACTIVE


class SubscriptionUpdate(BaseModel):
    quantity: Optional[int] = Field(default=None, ge=1)
    unit_price_paise: Optional[int] = Field(default=None, ge=0)
    auto_renew: Optional[bool] = None
    billing_interval: Optional[BillingInterval] = None


class SubscriptionRead(BaseModel):
    id: int
    subscription_number: str
    customer_id: int
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    customer_company: Optional[str] = None
    plan_id: int
    plan_name: Optional[str] = None
    quotation_id: Optional[int] = None
    status: SubscriptionStatus
    quantity: int
    unit_price_paise: int
    currency: str
    billing_interval: BillingInterval
    start_date: datetime
    current_period_start: datetime
    current_period_end: datetime
    auto_renew: bool
    created_at: datetime
    normalized_mrr_paise: int = 0


# --- Portal & Response Schemas ---
class PortalProfileRead(BaseModel):
    customer: CustomerRead
    active_subscriptions: List[SubscriptionRead]
    open_quotations: List[QuotationRead]


class ActionResponse(BaseModel):
    success: bool
    message: str
    data: Optional[dict] = None


# =============================================================================
# AUTHENTICATION & PORTAL CONTEXT DEPENDENCY
# =============================================================================
def get_current_portal_customer(
    request: Request,
    x_customer_id: Optional[int] = Header(None, alias="X-Customer-Id"),
    customer_id_query: Optional[int] = Query(None, alias="customer_id"),
    session: Session = Depends(get_session),
) -> Customer:
    """
    Authenticate and resolve the customer context for portal endpoints.
    Accepts:
      1. Direct X-Customer-Id header or ?customer_id query param
      2. Bearer JWT token in Authorization header
    """
    # 1. Check direct customer header/query
    resolved_id = x_customer_id or customer_id_query
    if resolved_id:
        cust = session.get(Customer, resolved_id)
        if cust and cust.status == CustomerStatus.ACTIVE:
            return cust
        elif cust:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Customer account is inactive.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")

    # 2. Check Bearer JWT token
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            user_id = payload.get("sub") or payload.get("user_id")
            if user_id:
                cust = session.exec(select(Customer).where(Customer.user_id == int(user_id))).first()
                if cust and cust.status == CustomerStatus.ACTIVE:
                    return cust
                elif cust:
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Customer account is inactive.")
        except jwt.PyJWTError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization token.")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Customer authentication required. Pass Authorization header or X-Customer-Id.",
    )


# =============================================================================
# 1. CUSTOMER MANAGEMENT APIS
# =============================================================================
@router.post("/customers", response_model=CustomerRead, status_code=status.HTTP_201_CREATED, tags=["Customers"])
def create_customer(data: CustomerCreate, session: Session = Depends(get_session)):
    """Create a new customer profile."""
    # Check duplicate email
    existing = session.exec(select(Customer).where(Customer.email == data.email)).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Customer with email '{data.email}' already exists.")

    now = get_utc_now()
    customer = Customer(
        name=data.name,
        email=data.email,
        phone=data.phone,
        company_name=data.company_name,
        gstin=data.gstin,
        billing_address=data.billing_address,
        city=data.city,
        state=data.state,
        postal_code=data.postal_code,
        country=data.country,
        currency=data.currency,
        user_id=data.user_id,
        status=CustomerStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    session.add(customer)
    session.commit()
    session.refresh(customer)
    return customer


@router.get("/customers", response_model=List[CustomerRead], tags=["Customers"])
def list_customers(
    search: Optional[str] = Query(None, description="Search by name, email, company or gstin"),
    status: Optional[CustomerStatus] = Query(None, description="Filter by active/inactive"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    """List customers with optional search and status filtering."""
    query = select(Customer)
    if status:
        query = query.where(Customer.status == status)
    if search:
        s = f"%{search.strip()}%"
        query = query.where(
            or_(
                Customer.name.ilike(s),
                Customer.email.ilike(s),
                Customer.company_name.ilike(s),
                Customer.gstin.ilike(s),
            )
        )
    query = query.offset(skip).limit(limit).order_by(Customer.created_at.desc())
    customers = session.exec(query).all()

    # Enrich with counts
    result = []
    for c in customers:
        active_subs = len([s for s in c.subscriptions if s.status == SubscriptionStatus.ACTIVE])
        quotes_count = len(c.quotations)
        c_dict = c.model_dump()
        c_dict["active_subscriptions_count"] = active_subs
        c_dict["quotations_count"] = quotes_count
        result.append(CustomerRead(**c_dict))
    return result


@router.get("/customers/{customer_id}", response_model=CustomerRead, tags=["Customers"])
def get_customer(customer_id: int, session: Session = Depends(get_session)):
    """Retrieve detailed customer profile by ID."""
    customer = session.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Customer #{customer_id} not found.")

    active_subs = len([s for s in customer.subscriptions if s.status == SubscriptionStatus.ACTIVE])
    quotes_count = len(customer.quotations)
    c_dict = customer.model_dump()
    c_dict["active_subscriptions_count"] = active_subs
    c_dict["quotations_count"] = quotes_count
    return CustomerRead(**c_dict)


@router.put("/customers/{customer_id}", response_model=CustomerRead, tags=["Customers"])
def update_customer(customer_id: int, data: CustomerUpdate, session: Session = Depends(get_session)):
    """Update customer profile information."""
    customer = session.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Customer #{customer_id} not found.")

    update_dict = data.model_dump(exclude_unset=True)
    if "email" in update_dict and update_dict["email"] != customer.email:
        existing = session.exec(select(Customer).where(Customer.email == update_dict["email"])).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Email '{update_dict['email']}' is already in use.")

    for k, v in update_dict.items():
        setattr(customer, k, v)

    customer.updated_at = get_utc_now()
    session.add(customer)
    session.commit()
    session.refresh(customer)

    active_subs = len([s for s in customer.subscriptions if s.status == SubscriptionStatus.ACTIVE])
    c_dict = customer.model_dump()
    c_dict["active_subscriptions_count"] = active_subs
    c_dict["quotations_count"] = len(customer.quotations)
    return CustomerRead(**c_dict)


@router.delete("/customers/{customer_id}", response_model=ActionResponse, tags=["Customers"])
def deactivate_customer(customer_id: int, session: Session = Depends(get_session)):
    """Deactivate a customer (soft delete). Fails if active subscriptions exist."""
    customer = session.get(Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Customer #{customer_id} not found.")

    active_subs = [s for s in customer.subscriptions if s.status == SubscriptionStatus.ACTIVE]
    if active_subs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot deactivate customer with {len(active_subs)} active subscription(s). Please cancel subscriptions first.",
        )

    customer.status = CustomerStatus.INACTIVE
    customer.updated_at = get_utc_now()
    session.add(customer)
    session.commit()
    return ActionResponse(success=True, message=f"Customer #{customer_id} successfully deactivated.")


# =============================================================================
# 2. QUOTATIONS APIS
# =============================================================================
@router.post("/quotations", response_model=QuotationRead, status_code=status.HTTP_201_CREATED, tags=["Quotations"])
def create_quotation(data: QuotationCreate, session: Session = Depends(get_session)):
    """Create a draft quotation for a customer with itemized plans/services."""
    customer = session.get(Customer, data.customer_id)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Customer #{data.customer_id} not found.")

    now = get_utc_now()
    expiry_date = now + timedelta(days=data.expiry_days)

    # Calculate financials
    items_raw = [item.model_dump() for item in data.items]
    subtotal, discount, tax, total = calculate_quote_financials(
        items_raw,
        discount_paise=data.discount_paise,
        tax_rate_basis_points=data.tax_rate_basis_points_snapshot,
    )

    quote_num = generate_quotation_number(session)
    quotation = Quotation(
        quotation_number=quote_num,
        customer_id=data.customer_id,
        issue_date=now,
        expiry_date=expiry_date,
        subtotal_paise=subtotal,
        discount_code_snapshot=data.discount_code_snapshot,
        discount_paise=discount,
        tax_name_snapshot=data.tax_name_snapshot,
        tax_rate_basis_points_snapshot=data.tax_rate_basis_points_snapshot,
        tax_paise=tax,
        total_paise=total,
        currency=customer.currency or "INR",
        status=QuotationStatus.DRAFT,
        notes=data.notes,
        created_at=now,
    )
    session.add(quotation)
    session.commit()
    session.refresh(quotation)

    # Insert quotation line items
    for item in data.items:
        q_item = QuotationItem(
            quotation_id=quotation.id,
            plan_id=item.plan_id,
            description=item.description,
            quantity=item.quantity,
            unit_price_paise=item.unit_price_paise,
            amount_paise=item.quantity * item.unit_price_paise,
        )
        session.add(q_item)

    session.commit()
    session.refresh(quotation)

    q_read = QuotationRead(**quotation.model_dump())
    q_read.customer_name = customer.name
    q_read.items = [QuotationItemRead(**item.model_dump()) for item in quotation.items]
    return q_read


@router.get("/quotations", response_model=List[QuotationRead], tags=["Quotations"])
def list_quotations(
    customer_id: Optional[int] = Query(None),
    status: Optional[QuotationStatus] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    """List quotations with optional filtering by customer and status."""
    query = select(Quotation)
    if customer_id:
        query = query.where(Quotation.customer_id == customer_id)
    if status:
        query = query.where(Quotation.status == status)

    query = query.offset(skip).limit(limit).order_by(Quotation.created_at.desc())
    quotations = session.exec(query).all()

    result = []
    for q in quotations:
        q_read = QuotationRead(**q.model_dump())
        q_read.customer_name = q.customer.name if q.customer else None
        q_read.items = [QuotationItemRead(**it.model_dump()) for it in q.items]
        result.append(q_read)
    return result


@router.get("/quotations/{quotation_id}", response_model=QuotationRead, tags=["Quotations"])
def get_quotation(quotation_id: int, session: Session = Depends(get_session)):
    """Retrieve quotation by ID including line items."""
    quotation = session.get(Quotation, quotation_id)
    if not quotation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Quotation #{quotation_id} not found.")

    q_read = QuotationRead(**quotation.model_dump())
    q_read.customer_name = quotation.customer.name if quotation.customer else None
    q_read.items = [QuotationItemRead(**it.model_dump()) for it in quotation.items]
    return q_read


@router.put("/quotations/{quotation_id}", response_model=QuotationRead, tags=["Quotations"])
def update_quotation(quotation_id: int, data: QuotationUpdate, session: Session = Depends(get_session)):
    """Update quotation (only allowed in DRAFT status)."""
    quotation = session.get(Quotation, quotation_id)
    if not quotation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Quotation #{quotation_id} not found.")
    if quotation.status != QuotationStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot edit quotation in '{quotation.status}' status. Only DRAFT quotes can be edited.",
        )

    if data.notes is not None:
        quotation.notes = data.notes
    if data.expiry_date is not None:
        quotation.expiry_date = data.expiry_date
    if data.discount_code_snapshot is not None:
        quotation.discount_code_snapshot = data.discount_code_snapshot
    if data.discount_paise is not None:
        quotation.discount_paise = data.discount_paise
    if data.tax_rate_basis_points_snapshot is not None:
        quotation.tax_rate_basis_points_snapshot = data.tax_rate_basis_points_snapshot

    # If items updated, replace line items
    if data.items is not None:
        # Delete old items
        for old_it in quotation.items:
            session.delete(old_it)
        session.commit()

        # Insert new items
        for item in data.items:
            q_item = QuotationItem(
                quotation_id=quotation.id,
                plan_id=item.plan_id,
                description=item.description,
                quantity=item.quantity,
                unit_price_paise=item.unit_price_paise,
                amount_paise=item.quantity * item.unit_price_paise,
            )
            session.add(q_item)

    session.commit()
    session.refresh(quotation)

    # Recalculate totals
    items_raw = [
        {"quantity": it.quantity, "unit_price_paise": it.unit_price_paise}
        for it in quotation.items
    ]
    subtotal, discount, tax, total = calculate_quote_financials(
        items_raw,
        discount_paise=quotation.discount_paise,
        tax_rate_basis_points=quotation.tax_rate_basis_points_snapshot,
    )
    quotation.subtotal_paise = subtotal
    quotation.discount_paise = discount
    quotation.tax_paise = tax
    quotation.total_paise = total

    session.add(quotation)
    session.commit()
    session.refresh(quotation)

    q_read = QuotationRead(**quotation.model_dump())
    q_read.customer_name = quotation.customer.name if quotation.customer else None
    q_read.items = [QuotationItemRead(**it.model_dump()) for it in quotation.items]
    return q_read


@router.post("/quotations/{quotation_id}/send", response_model=ActionResponse, tags=["Quotations"])
def send_quotation(quotation_id: int, session: Session = Depends(get_session)):
    """Transition quotation from DRAFT to SENT."""
    quotation = session.get(Quotation, quotation_id)
    if not quotation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Quotation #{quotation_id} not found.")
    if quotation.status != QuotationStatus.DRAFT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot send quotation in '{quotation.status}' status.")

    quotation.status = QuotationStatus.SENT
    quotation.issue_date = get_utc_now()
    session.add(quotation)
    session.commit()
    return ActionResponse(success=True, message=f"Quotation {quotation.quotation_number} marked as SENT.")


@router.post("/quotations/{quotation_id}/accept", response_model=ActionResponse, tags=["Quotations"])
def accept_quotation(
    quotation_id: int,
    auto_create_subscription: bool = Query(True, description="Automatically activate subscription upon acceptance"),
    session: Session = Depends(get_session),
):
    """
    Accept quotation and optionally generate an active subscription immediately.
    """
    quotation = session.get(Quotation, quotation_id)
    if not quotation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Quotation #{quotation_id} not found.")
    if quotation.status not in (QuotationStatus.SENT, QuotationStatus.DRAFT):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot accept quotation in '{quotation.status}' status.")

    now = get_utc_now()
    if ensure_utc(quotation.expiry_date) < now:
        quotation.status = QuotationStatus.EXPIRED
        session.add(quotation)
        session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot accept expired quotation.")

    quotation.status = QuotationStatus.ACCEPTED
    session.add(quotation)
    session.commit()

    sub_info = None
    if auto_create_subscription:
        try:
            subscription = convert_quotation_to_subscription(session, quotation)
            sub_info = {
                "subscription_id": subscription.id,
                "subscription_number": subscription.subscription_number,
                "status": subscription.status,
            }
        except Exception as e:
            # If no plan exists in items, quotation is still accepted, but subscription wasn't auto-created
            sub_info = {"note": f"Accepted without subscription creation: {str(e)}"}

    return ActionResponse(
        success=True,
        message=f"Quotation {quotation.quotation_number} ACCEPTED.",
        data=sub_info,
    )


@router.post("/quotations/{quotation_id}/reject", response_model=ActionResponse, tags=["Quotations"])
def reject_quotation(quotation_id: int, reason: Optional[str] = Query(None), session: Session = Depends(get_session)):
    """Reject quotation."""
    quotation = session.get(Quotation, quotation_id)
    if not quotation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Quotation #{quotation_id} not found.")
    if quotation.status not in (QuotationStatus.SENT, QuotationStatus.DRAFT):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot reject quotation in '{quotation.status}' status.")

    quotation.status = QuotationStatus.REJECTED
    if reason:
        quotation.notes = f"{quotation.notes or ''} [Rejected: {reason}]".strip()
    session.add(quotation)
    session.commit()
    return ActionResponse(success=True, message=f"Quotation {quotation.quotation_number} REJECTED.")


# =============================================================================
# 3. SUBSCRIPTIONS APIS
# =============================================================================
@router.post("/subscriptions", response_model=SubscriptionRead, status_code=status.HTTP_201_CREATED, tags=["Subscriptions"])
def create_subscription(data: SubscriptionCreate, session: Session = Depends(get_session)):
    """Create a new subscription linking customer and plan."""
    customer = session.get(Customer, data.customer_id)
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Customer #{data.customer_id} not found.")

    plan = session.get(Plan, data.plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Plan #{data.plan_id} not found.")

    now = get_utc_now()
    eff_start = data.start_date or now
    interval = data.billing_interval or plan.billing_interval or BillingInterval.MONTHLY
    unit_price = data.unit_price_paise if data.unit_price_paise is not None else plan.price_paise
    current_period_end = calculate_period_end(eff_start, interval)

    # Initial status: if plan has trial and status was default ACTIVE, start in TRIALING
    init_status = data.status or (SubscriptionStatus.TRIALING if plan.trial_period_days > 0 else SubscriptionStatus.ACTIVE)
    sub_num = generate_subscription_number(session)

    subscription = Subscription(
        subscription_number=sub_num,
        customer_id=data.customer_id,
        plan_id=data.plan_id,
        quotation_id=data.quotation_id,
        status=init_status,
        quantity=data.quantity,
        unit_price_paise=unit_price,
        currency=plan.currency or "INR",
        billing_interval=interval,
        start_date=eff_start,
        current_period_start=eff_start,
        current_period_end=current_period_end,
        auto_renew=data.auto_renew,
        created_at=now,
    )
    session.add(subscription)
    session.commit()
    session.refresh(subscription)

    s_dict = subscription.model_dump()
    s_dict["customer_name"] = customer.name
    s_dict["customer_email"] = customer.email
    s_dict["customer_company"] = customer.company_name
    s_dict["plan_name"] = plan.name
    s_dict["normalized_mrr_paise"] = calculate_normalized_mrr_paise(
        subscription.unit_price_paise, subscription.quantity, subscription.billing_interval
    )
    return SubscriptionRead(**s_dict)


@router.post("/subscriptions/from-quotation/{quotation_id}", response_model=SubscriptionRead, tags=["Subscriptions"])
def create_subscription_from_quotation(
    quotation_id: int,
    plan_id: Optional[int] = Query(None, description="Explicit plan override if multiple quotation items exist"),
    session: Session = Depends(get_session),
):
    """Convert an accepted quotation into an active subscription."""
    quotation = session.get(Quotation, quotation_id)
    if not quotation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Quotation #{quotation_id} not found.")
    if quotation.status != QuotationStatus.ACCEPTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Quotation #{quotation_id} must be in ACCEPTED status to convert (current status: {quotation.status}).",
        )

    try:
        sub = convert_quotation_to_subscription(session, quotation, plan_id=plan_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    s_dict = sub.model_dump()
    s_dict["customer_name"] = quotation.customer.name if quotation.customer else None
    s_dict["customer_email"] = quotation.customer.email if quotation.customer else None
    s_dict["customer_company"] = quotation.customer.company_name if quotation.customer else None
    s_dict["plan_name"] = sub.plan.name if sub.plan else None
    s_dict["normalized_mrr_paise"] = calculate_normalized_mrr_paise(
        sub.unit_price_paise, sub.quantity, sub.billing_interval
    )
    return SubscriptionRead(**s_dict)


@router.get("/subscriptions", response_model=List[SubscriptionRead], tags=["Subscriptions"])
def list_subscriptions(
    search: Optional[str] = Query(None, description="Search by SUB#, customer name, email or company"),
    status: Optional[SubscriptionStatus] = Query(None),
    customer_id: Optional[int] = Query(None),
    plan_id: Optional[int] = Query(None),
    interval: Optional[BillingInterval] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
):
    """List subscriptions with comprehensive filters for admin dashboard."""
    query = select(Subscription)
    if status:
        query = query.where(Subscription.status == status)
    if customer_id:
        query = query.where(Subscription.customer_id == customer_id)
    if plan_id:
        query = query.where(Subscription.plan_id == plan_id)
    if interval:
        query = query.where(Subscription.billing_interval == interval)

    query = query.offset(skip).limit(limit).order_by(Subscription.created_at.desc())
    subscriptions = session.exec(query).all()

    result = []
    for s in subscriptions:
        # Check text search filter if provided
        if search:
            term = search.strip().lower()
            match_sub = term in s.subscription_number.lower()
            match_cust = s.customer and (
                term in s.customer.name.lower()
                or term in s.customer.email.lower()
                or (s.customer.company_name and term in s.customer.company_name.lower())
            )
            match_plan = s.plan and (term in s.plan.name.lower())
            if not (match_sub or match_cust or match_plan):
                continue

        s_dict = s.model_dump()
        s_dict["customer_name"] = s.customer.name if s.customer else None
        s_dict["customer_email"] = s.customer.email if s.customer else None
        s_dict["customer_company"] = s.customer.company_name if s.customer else None
        s_dict["plan_name"] = s.plan.name if s.plan else None
        s_dict["normalized_mrr_paise"] = calculate_normalized_mrr_paise(
            s.unit_price_paise, s.quantity, s.billing_interval
        )
        result.append(SubscriptionRead(**s_dict))
    return result


@router.get("/subscriptions/{subscription_id}", response_model=SubscriptionRead, tags=["Subscriptions"])
def get_subscription(subscription_id: int, session: Session = Depends(get_session)):
    """Retrieve subscription details by ID."""
    sub = session.get(Subscription, subscription_id)
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Subscription #{subscription_id} not found.")

    s_dict = sub.model_dump()
    s_dict["customer_name"] = sub.customer.name if sub.customer else None
    s_dict["customer_email"] = sub.customer.email if sub.customer else None
    s_dict["customer_company"] = sub.customer.company_name if sub.customer else None
    s_dict["plan_name"] = sub.plan.name if sub.plan else None
    s_dict["normalized_mrr_paise"] = calculate_normalized_mrr_paise(
        sub.unit_price_paise, sub.quantity, sub.billing_interval
    )
    return SubscriptionRead(**s_dict)


@router.put("/subscriptions/{subscription_id}", response_model=SubscriptionRead, tags=["Subscriptions"])
def update_subscription(subscription_id: int, data: SubscriptionUpdate, session: Session = Depends(get_session)):
    """Update subscription terms (auto_renew, quantity, billing_interval)."""
    sub = session.get(Subscription, subscription_id)
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Subscription #{subscription_id} not found.")
    if sub.status in (SubscriptionStatus.CANCELED, SubscriptionStatus.EXPIRED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot edit subscription in '{sub.status}' state.",
        )

    if data.quantity is not None:
        sub.quantity = data.quantity
    if data.unit_price_paise is not None:
        sub.unit_price_paise = data.unit_price_paise
    if data.auto_renew is not None:
        sub.auto_renew = data.auto_renew
    if data.billing_interval is not None:
        sub.billing_interval = data.billing_interval
        # Recalculate next period end
        sub.current_period_end = calculate_period_end(sub.current_period_start, sub.billing_interval)

    session.add(sub)
    session.commit()
    session.refresh(sub)

    s_dict = sub.model_dump()
    s_dict["customer_name"] = sub.customer.name if sub.customer else None
    s_dict["customer_email"] = sub.customer.email if sub.customer else None
    s_dict["customer_company"] = sub.customer.company_name if sub.customer else None
    s_dict["plan_name"] = sub.plan.name if sub.plan else None
    s_dict["normalized_mrr_paise"] = calculate_normalized_mrr_paise(
        sub.unit_price_paise, sub.quantity, sub.billing_interval
    )
    return SubscriptionRead(**s_dict)


@router.post("/subscriptions/{subscription_id}/pause", response_model=ActionResponse, tags=["Subscriptions"])
def pause_subscription(subscription_id: int, session: Session = Depends(get_session)):
    """Pause an active subscription."""
    sub = session.get(Subscription, subscription_id)
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Subscription #{subscription_id} not found.")
    if sub.status != SubscriptionStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Only ACTIVE subscriptions can be paused (current: {sub.status}).")

    sub.status = SubscriptionStatus.PAUSED
    session.add(sub)
    session.commit()
    return ActionResponse(success=True, message=f"Subscription {sub.subscription_number} has been PAUSED.")


@router.post("/subscriptions/{subscription_id}/resume", response_model=ActionResponse, tags=["Subscriptions"])
def resume_subscription(subscription_id: int, session: Session = Depends(get_session)):
    """Resume a paused subscription."""
    sub = session.get(Subscription, subscription_id)
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Subscription #{subscription_id} not found.")
    if sub.status != SubscriptionStatus.PAUSED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Only PAUSED subscriptions can be resumed (current: {sub.status}).")

    sub.status = SubscriptionStatus.ACTIVE
    session.add(sub)
    session.commit()
    return ActionResponse(success=True, message=f"Subscription {sub.subscription_number} is now ACTIVE.")


@router.post("/subscriptions/{subscription_id}/cancel", response_model=ActionResponse, tags=["Subscriptions"])
def cancel_subscription(subscription_id: int, session: Session = Depends(get_session)):
    """Cancel subscription immediately."""
    sub = session.get(Subscription, subscription_id)
    if not sub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Subscription #{subscription_id} not found.")
    if sub.status in (SubscriptionStatus.CANCELED, SubscriptionStatus.EXPIRED):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Subscription is already {sub.status}.")

    sub.status = SubscriptionStatus.CANCELED
    sub.auto_renew = False
    session.add(sub)
    session.commit()
    return ActionResponse(success=True, message=f"Subscription {sub.subscription_number} has been CANCELED.")


# =============================================================================
# 4. CUSTOMER PORTAL APIS (TENANCY & AUTH-SCOPED)
# =============================================================================
@router.get("/portal/profile", response_model=PortalProfileRead, tags=["Customer Portal"])
def get_portal_profile(
    customer: Customer = Depends(get_current_portal_customer),
    session: Session = Depends(get_session),
):
    """Retrieve authenticated customer profile and overview metrics."""
    c_dict = customer.model_dump()
    active_subs = [s for s in customer.subscriptions if s.status == SubscriptionStatus.ACTIVE]
    c_dict["active_subscriptions_count"] = len(active_subs)
    c_dict["quotations_count"] = len(customer.quotations)
    cust_read = CustomerRead(**c_dict)

    subs_read = []
    for s in customer.subscriptions:
        s_dict = s.model_dump()
        s_dict["customer_name"] = customer.name
        s_dict["customer_email"] = customer.email
        s_dict["customer_company"] = customer.company_name
        s_dict["plan_name"] = s.plan.name if s.plan else None
        s_dict["normalized_mrr_paise"] = calculate_normalized_mrr_paise(s.unit_price_paise, s.quantity, s.billing_interval)
        subs_read.append(SubscriptionRead(**s_dict))

    quotes_read = []
    for q in customer.quotations:
        q_read = QuotationRead(**q.model_dump())
        q_read.customer_name = customer.name
        q_read.items = [QuotationItemRead(**it.model_dump()) for it in q.items]
        quotes_read.append(q_read)

    return PortalProfileRead(
        customer=cust_read,
        active_subscriptions=subs_read,
        open_quotations=quotes_read,
    )


@router.get("/portal/subscriptions", response_model=List[SubscriptionRead], tags=["Customer Portal"])
def list_portal_subscriptions(
    customer: Customer = Depends(get_current_portal_customer),
):
    """List subscriptions owned exclusively by the authenticated customer."""
    result = []
    for s in customer.subscriptions:
        s_dict = s.model_dump()
        s_dict["customer_name"] = customer.name
        s_dict["customer_email"] = customer.email
        s_dict["customer_company"] = customer.company_name
        s_dict["plan_name"] = s.plan.name if s.plan else None
        s_dict["normalized_mrr_paise"] = calculate_normalized_mrr_paise(s.unit_price_paise, s.quantity, s.billing_interval)
        result.append(SubscriptionRead(**s_dict))
    return result


@router.get("/portal/subscriptions/{subscription_id}", response_model=SubscriptionRead, tags=["Customer Portal"])
def get_portal_subscription(
    subscription_id: int,
    customer: Customer = Depends(get_current_portal_customer),
    session: Session = Depends(get_session),
):
    """Get single subscription details with customer isolation verification."""
    sub = session.get(Subscription, subscription_id)
    if not sub or sub.customer_id != customer.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subscription #{subscription_id} not found for this account.",
        )

    s_dict = sub.model_dump()
    s_dict["customer_name"] = customer.name
    s_dict["customer_email"] = customer.email
    s_dict["customer_company"] = customer.company_name
    s_dict["plan_name"] = sub.plan.name if sub.plan else None
    s_dict["normalized_mrr_paise"] = calculate_normalized_mrr_paise(sub.unit_price_paise, sub.quantity, sub.billing_interval)
    return SubscriptionRead(**s_dict)


@router.get("/portal/quotations", response_model=List[QuotationRead], tags=["Customer Portal"])
def list_portal_quotations(
    customer: Customer = Depends(get_current_portal_customer),
):
    """List quotations belonging exclusively to the authenticated customer."""
    result = []
    for q in customer.quotations:
        q_read = QuotationRead(**q.model_dump())
        q_read.customer_name = customer.name
        q_read.items = [QuotationItemRead(**it.model_dump()) for it in q.items]
        result.append(q_read)
    return result


@router.post("/portal/quotations/{quotation_id}/accept", response_model=ActionResponse, tags=["Customer Portal"])
def portal_accept_quotation(
    quotation_id: int,
    customer: Customer = Depends(get_current_portal_customer),
    session: Session = Depends(get_session),
):
    """Customer self-service quote acceptance."""
    quotation = session.get(Quotation, quotation_id)
    if not quotation or quotation.customer_id != customer.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quotation not found.")

    if quotation.status != QuotationStatus.SENT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot accept quotation in '{quotation.status}' state.")

    now = get_utc_now()
    if ensure_utc(quotation.expiry_date) < now:
        quotation.status = QuotationStatus.EXPIRED
        session.add(quotation)
        session.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quotation has expired.")

    quotation.status = QuotationStatus.ACCEPTED
    session.add(quotation)
    session.commit()

    sub_info = None
    try:
        sub = convert_quotation_to_subscription(session, quotation)
        sub_info = {
            "subscription_id": sub.id,
            "subscription_number": sub.subscription_number,
            "status": sub.status,
        }
    except Exception as e:
        sub_info = {"note": str(e)}

    return ActionResponse(
        success=True,
        message=f"Quotation {quotation.quotation_number} accepted successfully. Service agreement created.",
        data=sub_info,
    )


@router.post("/portal/quotations/{quotation_id}/reject", response_model=ActionResponse, tags=["Customer Portal"])
def portal_reject_quotation(
    quotation_id: int,
    reason: Optional[str] = Query(None),
    customer: Customer = Depends(get_current_portal_customer),
    session: Session = Depends(get_session),
):
    """Customer self-service quote rejection."""
    quotation = session.get(Quotation, quotation_id)
    if not quotation or quotation.customer_id != customer.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quotation not found.")

    if quotation.status != QuotationStatus.SENT:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot reject quotation in '{quotation.status}' state.")

    quotation.status = QuotationStatus.REJECTED
    if reason:
        quotation.notes = f"{quotation.notes or ''} [Customer Rejected: {reason}]".strip()
    session.add(quotation)
    session.commit()
    return ActionResponse(success=True, message=f"Quotation {quotation.quotation_number} has been rejected.")
