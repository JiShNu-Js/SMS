from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List
from sqlalchemy import CheckConstraint
from sqlmodel import SQLModel, Field, Relationship


def get_utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


# ===========================================================================
# ENUMS
# ===========================================================================
class UserRole(str, Enum):
    ADMIN = "admin"
    STAFF = "staff"
    CUSTOMER = "customer"


class CustomerStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class ProductType(str, Enum):
    RECURRING = "recurring"
    ONE_TIME = "one_time"


class BillingInterval(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class DiscountType(str, Enum):
    PERCENTAGE = "percentage"
    FIXED_AMOUNT = "fixed_amount"


class QuotationStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class SubscriptionStatus(str, Enum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    PAUSED = "paused"
    CANCELED = "canceled"
    EXPIRED = "expired"


class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    OPEN = "open"
    PAID = "paid"
    VOID = "void"


class PaymentStatus(str, Enum):
    UNPAID = "unpaid"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"


class PaymentMethod(str, Enum):
    UPI = "upi"
    NET_BANKING = "net_banking"
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    CASH = "cash"
    OTHER = "other"


class TransactionStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


# ===========================================================================
# HELPER ARITHMETIC FUNCTIONS (INTEGER ROUNDING)
# ===========================================================================
def calculate_tax_paise(taxable_paise: int, rate_basis_points: int) -> int:
    """Calculate tax in paise from integer basis points using half-up integer rounding."""
    if taxable_paise <= 0 or rate_basis_points <= 0:
        return 0
    return (taxable_paise * rate_basis_points + 5000) // 10000


def calculate_discount_paise(
    subtotal_paise: int,
    discount_type: DiscountType,
    percentage_basis_points: Optional[int] = None,
    fixed_amount_paise: Optional[int] = None,
) -> int:
    """Calculate discount in paise using half-up integer rounding."""
    if subtotal_paise <= 0:
        return 0
    if discount_type == DiscountType.PERCENTAGE and percentage_basis_points is not None:
        discount = (subtotal_paise * percentage_basis_points + 5000) // 10000
        return min(discount, subtotal_paise)
    elif discount_type == DiscountType.FIXED_AMOUNT and fixed_amount_paise is not None:
        return min(fixed_amount_paise, subtotal_paise)
    return 0


def calculate_normalized_mrr_paise(unit_price_paise: int, quantity: int, interval: BillingInterval) -> int:
    """Normalize recurring subscription rate to monthly revenue in paise with integer half-up rounding."""
    total_cycle_paise = unit_price_paise * quantity
    if interval == BillingInterval.MONTHLY:
        return total_cycle_paise
    elif interval == BillingInterval.QUARTERLY:
        # Half-up rounding for divisor 3: (total + 1) // 3
        return (total_cycle_paise + 1) // 3
    elif interval == BillingInterval.YEARLY:
        # Half-up rounding for divisor 12: (total + 6) // 12
        return (total_cycle_paise + 6) // 12
    return 0


# ===========================================================================
# 1. MEMBER 1: FOUNDATION & AUTH
# ===========================================================================
class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True, nullable=False)
    hashed_password: str = Field(nullable=False)
    full_name: str = Field(nullable=False)
    role: UserRole = Field(default=UserRole.CUSTOMER, nullable=False)
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(default_factory=get_utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=get_utc_now, nullable=False)

    customer: Optional["Customer"] = Relationship(back_populates="user")


# ===========================================================================
# 2. MEMBER 2: CATALOG, PRICING, TAXES & DISCOUNTS
# ===========================================================================
class Product(SQLModel, table=True):
    __tablename__ = "products"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, nullable=False)
    code: str = Field(unique=True, index=True, nullable=False)
    description: Optional[str] = Field(default=None)
    type: ProductType = Field(default=ProductType.RECURRING, nullable=False)
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(default_factory=get_utc_now, nullable=False)

    plans: List["Plan"] = Relationship(back_populates="product")


class Plan(SQLModel, table=True):
    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint("price_paise >= 0", name="chk_plan_price_non_negative"),
        CheckConstraint("trial_period_days >= 0", name="chk_plan_trial_non_negative"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="products.id", nullable=False)
    name: str = Field(nullable=False)
    code: str = Field(unique=True, index=True, nullable=False)
    price_paise: int = Field(default=0, ge=0, nullable=False)
    currency: str = Field(default="INR", nullable=False)
    billing_interval: Optional[BillingInterval] = Field(default=None, nullable=True)  # None for one-time plans
    trial_period_days: int = Field(default=0, ge=0, nullable=False)
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(default_factory=get_utc_now, nullable=False)

    product: Product = Relationship(back_populates="plans")
    subscriptions: List["Subscription"] = Relationship(back_populates="plan")


class Tax(SQLModel, table=True):
    __tablename__ = "taxes"
    __table_args__ = (
        CheckConstraint("rate_basis_points >= 0 AND rate_basis_points <= 10000", name="chk_tax_basis_points_range"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(nullable=False)
    code: str = Field(unique=True, index=True, nullable=False)
    rate_basis_points: int = Field(default=1800, ge=0, le=10000, nullable=False)  # 1800 = 18.00%
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(default_factory=get_utc_now, nullable=False)


class Discount(SQLModel, table=True):
    __tablename__ = "discounts"
    __table_args__ = (
        CheckConstraint(
            "(type IN ('PERCENTAGE', 'percentage') AND percentage_basis_points IS NOT NULL AND fixed_amount_paise IS NULL) OR "
            "(type IN ('FIXED_AMOUNT', 'fixed_amount') AND fixed_amount_paise IS NOT NULL AND percentage_basis_points IS NULL)",
            name="chk_discount_single_valid_value",
        ),
        CheckConstraint("percentage_basis_points IS NULL OR (percentage_basis_points >= 0 AND percentage_basis_points <= 10000)", name="chk_discount_pct_range"),
        CheckConstraint("fixed_amount_paise IS NULL OR fixed_amount_paise >= 0", name="chk_discount_fixed_non_negative"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True, nullable=False)
    name: str = Field(nullable=False)
    type: DiscountType = Field(default=DiscountType.PERCENTAGE, nullable=False)
    percentage_basis_points: Optional[int] = Field(default=None, ge=0, le=10000)
    fixed_amount_paise: Optional[int] = Field(default=None, ge=0)
    valid_until: Optional[datetime] = Field(default=None)
    is_active: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(default_factory=get_utc_now, nullable=False)


# ===========================================================================
# 3. MEMBER 3: CUSTOMER PORTAL, QUOTATIONS & SUBSCRIPTIONS
# ===========================================================================
class Customer(SQLModel, table=True):
    __tablename__ = "customers"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", unique=True, nullable=True)  # 1:1 portal user
    name: str = Field(index=True, nullable=False)
    email: str = Field(index=True, nullable=False)
    phone: Optional[str] = Field(default=None)
    company_name: Optional[str] = Field(default=None)
    gstin: Optional[str] = Field(default=None)
    billing_address: Optional[str] = Field(default=None)
    city: Optional[str] = Field(default=None)
    state: Optional[str] = Field(default=None)
    postal_code: Optional[str] = Field(default=None)
    country: str = Field(default="India", nullable=False)
    currency: str = Field(default="INR", nullable=False)
    status: CustomerStatus = Field(default=CustomerStatus.ACTIVE, nullable=False)
    created_at: datetime = Field(default_factory=get_utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=get_utc_now, nullable=False)

    user: Optional[User] = Relationship(back_populates="customer")
    quotations: List["Quotation"] = Relationship(back_populates="customer")
    subscriptions: List["Subscription"] = Relationship(back_populates="customer")
    invoices: List["Invoice"] = Relationship(back_populates="customer")


class Quotation(SQLModel, table=True):
    __tablename__ = "quotations"
    __table_args__ = (
        CheckConstraint("subtotal_paise >= 0", name="chk_quotation_subtotal_non_negative"),
        CheckConstraint("discount_paise >= 0", name="chk_quotation_discount_non_negative"),
        CheckConstraint("tax_rate_basis_points_snapshot >= 0 AND tax_rate_basis_points_snapshot <= 10000", name="chk_quotation_tax_bps_range"),
        CheckConstraint("tax_paise >= 0", name="chk_quotation_tax_non_negative"),
        CheckConstraint("total_paise >= 0", name="chk_quotation_total_non_negative"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    quotation_number: str = Field(unique=True, index=True, nullable=False)
    customer_id: int = Field(foreign_key="customers.id", nullable=False)
    issue_date: datetime = Field(default_factory=get_utc_now, nullable=False)
    expiry_date: datetime = Field(nullable=False)
    subtotal_paise: int = Field(default=0, ge=0, nullable=False)
    discount_code_snapshot: Optional[str] = Field(default=None)
    discount_paise: int = Field(default=0, ge=0, nullable=False)
    tax_name_snapshot: Optional[str] = Field(default=None)
    tax_rate_basis_points_snapshot: int = Field(default=0, ge=0, le=10000, nullable=False)
    tax_paise: int = Field(default=0, ge=0, nullable=False)
    total_paise: int = Field(default=0, ge=0, nullable=False)
    currency: str = Field(default="INR", nullable=False)
    status: QuotationStatus = Field(default=QuotationStatus.DRAFT, nullable=False)
    notes: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=get_utc_now, nullable=False)

    customer: Customer = Relationship(back_populates="quotations")
    items: List["QuotationItem"] = Relationship(back_populates="quotation")


class QuotationItem(SQLModel, table=True):
    __tablename__ = "quotation_items"
    __table_args__ = (
        CheckConstraint("quantity >= 1", name="chk_quote_item_qty_positive"),
        CheckConstraint("unit_price_paise >= 0", name="chk_quote_item_unit_price_non_negative"),
        CheckConstraint("amount_paise >= 0", name="chk_quote_item_amount_non_negative"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    quotation_id: int = Field(foreign_key="quotations.id", nullable=False)
    plan_id: Optional[int] = Field(default=None, foreign_key="plans.id")
    description: str = Field(nullable=False)
    quantity: int = Field(default=1, ge=1, nullable=False)
    unit_price_paise: int = Field(default=0, ge=0, nullable=False)
    amount_paise: int = Field(default=0, ge=0, nullable=False)

    quotation: Quotation = Relationship(back_populates="items")


class Subscription(SQLModel, table=True):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint("quantity >= 1", name="chk_sub_qty_positive"),
        CheckConstraint("unit_price_paise >= 0", name="chk_sub_price_non_negative"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    subscription_number: str = Field(unique=True, index=True, nullable=False)
    customer_id: int = Field(foreign_key="customers.id", nullable=False)
    plan_id: int = Field(foreign_key="plans.id", nullable=False)
    quotation_id: Optional[int] = Field(default=None, foreign_key="quotations.id")
    status: SubscriptionStatus = Field(default=SubscriptionStatus.ACTIVE, nullable=False)
    quantity: int = Field(default=1, ge=1, nullable=False)
    unit_price_paise: int = Field(ge=0, nullable=False)
    currency: str = Field(default="INR", nullable=False)
    billing_interval: BillingInterval = Field(nullable=False)  # Enforced recurring
    start_date: datetime = Field(default_factory=get_utc_now, nullable=False)
    current_period_start: datetime = Field(nullable=False)
    current_period_end: datetime = Field(nullable=False)
    auto_renew: bool = Field(default=True, nullable=False)
    created_at: datetime = Field(default_factory=get_utc_now, nullable=False)

    customer: Customer = Relationship(back_populates="subscriptions")
    plan: Plan = Relationship(back_populates="subscriptions")
    invoices: List["Invoice"] = Relationship(back_populates="subscription")


# ===========================================================================
# 4. MEMBER 4: BILLING, INVOICES & PAYMENTS
# ===========================================================================
class Invoice(SQLModel, table=True):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint("subtotal_paise >= 0", name="chk_inv_subtotal_non_negative"),
        CheckConstraint("discount_paise >= 0", name="chk_inv_discount_non_negative"),
        CheckConstraint("tax_rate_basis_points_snapshot >= 0 AND tax_rate_basis_points_snapshot <= 10000", name="chk_inv_tax_bps_range"),
        CheckConstraint("tax_paise >= 0", name="chk_inv_tax_non_negative"),
        CheckConstraint("total_paise >= 0", name="chk_inv_total_non_negative"),
        CheckConstraint("amount_paid_paise >= 0", name="chk_inv_amount_paid_non_negative"),
        CheckConstraint("amount_due_paise >= 0", name="chk_inv_amount_due_non_negative"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    invoice_number: str = Field(unique=True, index=True, nullable=False)
    customer_id: int = Field(foreign_key="customers.id", nullable=False)
    subscription_id: Optional[int] = Field(default=None, foreign_key="subscriptions.id")  # Null for one-time purchases
    issue_date: datetime = Field(default_factory=get_utc_now, nullable=False)
    due_date: datetime = Field(nullable=False)
    paid_at: Optional[datetime] = Field(default=None)
    subtotal_paise: int = Field(default=0, ge=0, nullable=False)
    discount_code_snapshot: Optional[str] = Field(default=None)
    discount_paise: int = Field(default=0, ge=0, nullable=False)
    tax_name_snapshot: Optional[str] = Field(default=None)
    tax_rate_basis_points_snapshot: int = Field(default=0, ge=0, le=10000, nullable=False)
    tax_paise: int = Field(default=0, ge=0, nullable=False)
    total_paise: int = Field(default=0, ge=0, nullable=False)
    amount_paid_paise: int = Field(default=0, ge=0, nullable=False)
    amount_due_paise: int = Field(default=0, ge=0, nullable=False)
    currency: str = Field(default="INR", nullable=False)
    status: InvoiceStatus = Field(default=InvoiceStatus.OPEN, nullable=False)
    payment_status: PaymentStatus = Field(default=PaymentStatus.UNPAID, nullable=False)
    notes: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=get_utc_now, nullable=False)

    customer: Customer = Relationship(back_populates="invoices")
    subscription: Optional[Subscription] = Relationship(back_populates="invoices")
    items: List["InvoiceItem"] = Relationship(back_populates="invoice")
    payments: List["Payment"] = Relationship(back_populates="invoice")


class InvoiceItem(SQLModel, table=True):
    __tablename__ = "invoice_items"
    __table_args__ = (
        CheckConstraint("quantity >= 1", name="chk_inv_item_qty_positive"),
        CheckConstraint("unit_price_paise >= 0", name="chk_inv_item_unit_price_non_negative"),
        CheckConstraint("amount_paise >= 0", name="chk_inv_item_amount_non_negative"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    invoice_id: int = Field(foreign_key="invoices.id", nullable=False)
    plan_id: Optional[int] = Field(default=None, foreign_key="plans.id")
    description: str = Field(nullable=False)
    quantity: int = Field(default=1, ge=1, nullable=False)
    unit_price_paise: int = Field(default=0, ge=0, nullable=False)
    amount_paise: int = Field(default=0, ge=0, nullable=False)

    invoice: Invoice = Relationship(back_populates="items")


class Payment(SQLModel, table=True):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount_paise > 0", name="chk_payment_amount_positive"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    payment_number: str = Field(unique=True, index=True, nullable=False)
    invoice_id: int = Field(foreign_key="invoices.id", nullable=False)
    amount_paise: int = Field(gt=0, nullable=False)
    currency: str = Field(default="INR", nullable=False)
    payment_method: PaymentMethod = Field(default=PaymentMethod.UPI, nullable=False)
    transaction_reference: Optional[str] = Field(default=None, index=True)
    status: TransactionStatus = Field(default=TransactionStatus.PENDING, nullable=False)  # PENDING by default
    payment_date: datetime = Field(default_factory=get_utc_now, nullable=False)
    notes: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=get_utc_now, nullable=False)

    invoice: Invoice = Relationship(back_populates="payments")
