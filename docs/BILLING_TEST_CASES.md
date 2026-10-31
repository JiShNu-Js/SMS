# Brightloop Subscription Management System
# Billing, Invoices & Payments Test Cases

**Author / Responsibility:** Member 4 — Billing, Invoices and Payments  
**Project:** Brightloop Subscription Management System  
**Document:** `docs/BILLING_TEST_CASES.md`  
**Status:** Ready for Review  

---

## Document Overview

This document specifies the end-to-end test suite and business validation rules for the Billing, Invoices, and Payments subsystem of the Brightloop Subscription Management System. It serves as the primary verification contract for automatic billing runs, invoice lifecycle management, payment processing, calculations, and concurrent edge scenarios.

---

### 1. Automatic Billing Tests

#### Test Case B01: Generate invoice for an active subscription due for billing
- **Test ID:** B01
- **Test Description:** Verify that an active subscription whose next billing date is on or before the current billing run date generates a new invoice for the due billing period.
- **Preconditions:**
  - Customer exists with complete billing profile.
  - Subscription is in `Active` status.
  - Subscription billing cycle is monthly/annual, and `next_billing_date` is less than or equal to current execution date (e.g., today's date).
  - No invoice exists yet for this subscription for the upcoming billing cycle period.
- **Test Input:**
  - Subscription ID: `SUB-1001`
  - Customer ID: `CUST-501`
  - Plan Rate: ₹2,000.00
  - Billing Run Date: `2026-11-01`
  - Billing Period: `2026-11-01` to `2026-11-30`
- **Steps:**
  1. Trigger the automatic billing process for date `2026-11-01`.
  2. Query the billing system for generated invoices associated with `SUB-1001`.
  3. Verify the generated invoice details, status, and subscription linkage.
- **Expected Result:**
  - A new invoice is generated for `SUB-1001`.
  - Invoice status is set to `Draft` (or `Confirmed` according to billing run auto-confirmation policy).
  - Invoice billing period matches `2026-11-01` to `2026-11-30`.
  - Subscription's next billing date advances to the next period (`2026-12-01`).
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case B02: Skip subscriptions that are not due
- **Test ID:** B02
- **Test Description:** Verify that subscriptions whose next billing date is in the future are skipped during the automatic billing run.
- **Preconditions:**
  - Subscription is in `Active` status.
  - Subscription `next_billing_date` is in the future relative to the billing run date (e.g., `2026-12-15` when billing run is executed on `2026-11-01`).
- **Test Input:**
  - Subscription ID: `SUB-1002`
  - Next Billing Date: `2026-12-15`
  - Billing Run Date: `2026-11-01`
- **Steps:**
  1. Execute the automatic billing run for date `2026-11-01`.
  2. Inspect the billing run logs and invoice output records.
- **Expected Result:**
  - Subscription `SUB-1002` is evaluated and skipped.
  - No invoice is generated for `SUB-1002`.
  - Subscription `next_billing_date` remains unchanged (`2026-12-15`).
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case B03: Skip closed subscriptions
- **Test ID:** B03
- **Test Description:** Verify that subscriptions that are cancelled, terminated, or closed are not billed, even if their historical or recorded billing date falls on or before the execution date.
- **Preconditions:**
  - Subscription status is set to `Closed` (or `Cancelled`).
  - Recorded billing date is on or before the current execution date.
- **Test Input:**
  - Subscription ID: `SUB-1003`
  - Subscription Status: `Closed`
  - Billing Run Date: `2026-11-01`
- **Steps:**
  1. Execute the automatic billing run for date `2026-11-01`.
  2. Check invoice table/records for any newly created invoice associated with `SUB-1003`.
- **Expected Result:**
  - Subscription `SUB-1003` is excluded from billing generation.
  - Zero invoices are created for `SUB-1003`.
  - Billing run log indicates subscription was ignored due to closed status.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case B04: Prevent duplicate invoices for the same subscription and billing period
- **Test ID:** B04
- **Test Description:** Verify that the system prevents creating more than one invoice for the exact same subscription covering the same billing period.
- **Preconditions:**
  - Subscription `SUB-1004` is active.
  - An invoice already exists for `SUB-1004` covering the period `2026-11-01` to `2026-11-30`.
- **Test Input:**
  - Subscription ID: `SUB-1004`
  - Target Period: `2026-11-01` to `2026-11-30`
  - Billing Run Date: `2026-11-01`
- **Steps:**
  1. Initiate a billing cycle execution targeting `SUB-1004` for period `2026-11-01` to `2026-11-30`.
  2. Check system validation response and invoice database count for `SUB-1004`.
- **Expected Result:**
  - The billing engine detects an existing invoice for the subscription and period.
  - Invoice generation is aborted for this subscription without throwing an unhandled exception.
  - Exactly one invoice remains associated with `SUB-1004` for `2026-11-01` to `2026-11-30`.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case B05: Generate separate invoices for multiple eligible subscriptions
- **Test ID:** B05
- **Test Description:** Verify that an automated billing run processes multiple eligible active subscriptions independently, creating distinct invoices for each.
- **Preconditions:**
  - Three active subscriptions exist (`SUB-2001`, `SUB-2002`, `SUB-2003`), each due for billing on or before `2026-11-01`.
  - No prior invoices exist for these subscriptions for the current period.
- **Test Input:**
  - Batch of subscriptions:
    - `SUB-2001` (Customer: `CUST-101`, Plan Amount: ₹1,500.00)
    - `SUB-2002` (Customer: `CUST-102`, Plan Amount: ₹2,500.00)
    - `SUB-2003` (Customer: `CUST-103`, Plan Amount: ₹4,000.00)
  - Execution Date: `2026-11-01`
- **Steps:**
  1. Execute the batch automated billing process.
  2. Inspect the generated invoices and check the subscription-to-invoice mapping.
- **Expected Result:**
  - Exactly 3 separate invoices are created.
  - Each invoice contains its respective customer details, plan amounts, and unique invoice identifiers.
  - Each subscription's next billing date is properly updated.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case B06: Running billing repeatedly must not create duplicate invoices
- **Test ID:** B06
- **Test Description:** Verify billing idempotency: running the automated billing routine multiple times consecutively on the same date produces invoices only on the first run and skips already-billed subscriptions on subsequent runs.
- **Preconditions:**
  - Multiple subscriptions (`SUB-3001`, `SUB-3002`) are due on `2026-11-01`.
- **Test Input:**
  - First run timestamp: `2026-11-01 08:00:00`
  - Second run timestamp: `2026-11-01 08:30:00`
  - Third run timestamp: `2026-11-01 09:00:00`
- **Steps:**
  1. Run automated billing at 08:00:00. Record created invoice IDs and count.
  2. Run automated billing again at 08:30:00 without altering subscription state.
  3. Run automated billing again at 09:00:00.
  4. Compare total invoice records before and after runs 2 and 3.
- **Expected Result:**
  - First run generates invoices for `SUB-3001` and `SUB-3002`.
  - Runs 2 and 3 identify that invoices already exist for the period and skip generation.
  - Total invoice count does not increase after runs 2 and 3.
  - Zero duplicate invoices are created.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

### 2. Invoice Management Tests

#### Test Case I01: Generate unique invoice numbers
- **Test ID:** I01
- **Test Description:** Verify that each newly created invoice receives a unique, sequential, non-colliding invoice number formatted according to standard `INV-YYYY-0001`.
- **Preconditions:**
  - Current calendar year is 2026.
  - Initial system invoice sequence is known (or at 0 for the year).
- **Test Input:**
  - Request to create 3 consecutive invoices.
- **Steps:**
  1. Create first invoice.
  2. Create second invoice.
  3. Create third invoice.
  4. Inspect generated invoice numbers.
- **Expected Result:**
  - Invoices are assigned sequential identifiers following the format `INV-YYYY-XXXX` (e.g., `INV-2026-0001`, `INV-2026-0002`, `INV-2026-0003`).
  - No two invoices share the same invoice number.
  - Padding is consistently 4 digits (e.g., `0001` through `9999`).
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case I02: Confirm a draft invoice
- **Test ID:** I02
- **Test Description:** Verify that an invoice in `Draft` status can be successfully confirmed, changing its status to `Confirmed` and locking it for payment acceptance.
- **Preconditions:**
  - Invoice `INV-2026-0010` exists in `Draft` status.
- **Test Input:**
  - Target Invoice Number: `INV-2026-0010`
  - Action: `Confirm`
- **Steps:**
  1. Retrieve invoice `INV-2026-0010` and verify current status is `Draft`.
  2. Issue confirmation command/request on `INV-2026-0010`.
  3. Re-fetch invoice details.
- **Expected Result:**
  - Invoice status transitions from `Draft` to `Confirmed`.
  - Confirmation timestamp and audit metadata are recorded.
  - Invoice is now eligible to receive payments.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case I03: Cancel a draft invoice
- **Test ID:** I03
- **Test Description:** Verify that an invoice in `Draft` status can be cancelled, transitioning its status to `Cancelled`.
- **Preconditions:**
  - Invoice `INV-2026-0011` exists in `Draft` status.
  - No payments have been attempted or recorded.
- **Test Input:**
  - Target Invoice Number: `INV-2026-0011`
  - Action: `Cancel`
  - Cancellation Reason: "Customer requested plan change prior to confirmation"
- **Steps:**
  1. Retrieve invoice `INV-2026-0011` in `Draft` status.
  2. Execute cancellation action with cancellation reason.
  3. Verify updated invoice record.
- **Expected Result:**
  - Invoice status changes to `Cancelled`.
  - Invoice balance becomes void.
  - Invoice cannot transition to `Confirmed` or `Paid`.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case I04: Cancel a confirmed invoice
- **Test ID:** I04
- **Test Description:** Verify that an unpaid invoice in `Confirmed` status can be cancelled prior to payment settlement.
- **Preconditions:**
  - Invoice `INV-2026-0012` exists in `Confirmed` status.
  - Payment status is unpaid.
- **Test Input:**
  - Target Invoice Number: `INV-2026-0012`
  - Action: `Cancel`
  - Reason: "Subscription paused before billing due date"
- **Steps:**
  1. Check invoice `INV-2026-0012` status is `Confirmed`.
  2. Execute cancellation action.
  3. Verify invoice status.
- **Expected Result:**
  - Invoice status transitions from `Confirmed` to `Cancelled`.
  - Cancellation is logged with user and timestamp.
  - Invoice is closed for subsequent payment attempts.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case I05: Reject payment for cancelled invoices
- **Test ID:** I05
- **Test Description:** Verify that the system strictly blocks payment attempts submitted against an invoice that is in `Cancelled` status.
- **Preconditions:**
  - Invoice `INV-2026-0013` has status `Cancelled`.
  - Total amount was ₹2,124.00.
- **Test Input:**
  - Invoice Number: `INV-2026-0013`
  - Payment Amount: ₹2,124.00
  - Payment Method: `UPI`
  - Transaction Reference: `UPI-TEST-12345`
- **Steps:**
  1. Submit a payment processing request of ₹2,124.00 for `INV-2026-0013`.
  2. Observe system response and invoice status.
- **Expected Result:**
  - Payment submission is rejected with validation error: "Cannot accept payment for a cancelled invoice."
  - No payment record is committed.
  - Invoice remains in `Cancelled` status.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case I06: Display a printable invoice
- **Test ID:** I06
- **Test Description:** Verify that a printable invoice view renders complete and accurate invoice information, including header, invoice number, customer details, line items, discounts, taxes, and total.
- **Preconditions:**
  - Invoice `INV-2026-0014` exists in `Confirmed` status.
  - Customer name, address, tax details, itemized lines, discount, and tax exist on the invoice.
- **Test Input:**
  - Invoice Number: `INV-2026-0014`
  - View Request: Printable view / Print preview format
- **Steps:**
  1. Request printable view for invoice `INV-2026-0014`.
  2. Verify all structural fields:
     - Header: Brightloop branding and company details
     - Invoice Number: `INV-2026-0014`
     - Invoice Dates: Issue date and due date
     - Customer Details: Name, billing address
     - Line items table with description, unit price, quantity, net amount
     - Calculated summary: Subtotal, Discount, Tax, Total Payable
     - Payment instructions / status
- **Expected Result:**
  - Printable layout renders cleanly without missing data or broken styling.
  - Financial figures match stored decimal totals exactly.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case I07: Record invoice sending activity
- **Test ID:** I07
- **Test Description:** Verify that dispatching an invoice to a customer (e.g., via email or notification) records an audit trail entry documenting recipient, timestamp, and status.
- **Preconditions:**
  - Invoice `INV-2026-0015` is in `Confirmed` status.
  - Customer email address is configured.
- **Test Input:**
  - Invoice Number: `INV-2026-0015`
  - Recipient: `customer@example.com`
  - Action: `Send Invoice`
- **Steps:**
  1. Trigger "Send Invoice" action for `INV-2026-0015`.
  2. Check activity log / communication history for `INV-2026-0015`.
- **Expected Result:**
  - Activity record is created containing:
    - Activity type: `INVOICE_SENT`
    - Recipient: `customer@example.com`
    - Timestamp of dispatch
    - Dispatched status: `Success`
  - Invoice audit log reflects the transmission.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

### 3. Payment Validation Tests

#### Test Case P01: Successful full cash payment
- **Test ID:** P01
- **Test Description:** Verify successful processing and recording of an exact-match cash payment for a confirmed invoice.
- **Preconditions:**
  - Invoice `INV-2026-0020` is in `Confirmed` status.
  - Total amount due is ₹2,124.00.
- **Test Input:**
  - Invoice Number: `INV-2026-0020`
  - Payment Method: `Cash`
  - Payment Amount: ₹2,124.00
  - Reference / Receipt Number: `CASH-REC-001`
- **Steps:**
  1. Submit payment of ₹2,124.00 with method `Cash`.
  2. Verify transaction result and invoice status.
- **Expected Result:**
  - Payment is accepted and recorded successfully.
  - Invoice status changes from `Confirmed` to `Paid`.
  - Amount paid equals ₹2,124.00; balance due becomes ₹0.00.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case P02: Successful full UPI payment
- **Test ID:** P02
- **Test Description:** Verify successful processing of an exact-match UPI payment for a confirmed invoice.
- **Preconditions:**
  - Invoice `INV-2026-0021` is in `Confirmed` status.
  - Total amount due is ₹2,124.00.
- **Test Input:**
  - Invoice Number: `INV-2026-0021`
  - Payment Method: `UPI`
  - Payment Amount: ₹2,124.00
  - UPI Transaction ID / VPA: `upi_ref_20261101_889900`
- **Steps:**
  1. Submit UPI payment of ₹2,124.00 with transaction ID `upi_ref_20261101_889900`.
  2. Verify transaction response and updated invoice state.
- **Expected Result:**
  - Payment is confirmed.
  - Invoice status transitions to `Paid`.
  - Payment method is recorded as `UPI` with the reference string.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case P03: Successful full bank transfer payment
- **Test ID:** P03
- **Test Description:** Verify successful processing of an exact-match bank transfer payment (NEFT/RTGS/IMPS) for a confirmed invoice.
- **Preconditions:**
  - Invoice `INV-2026-0022` is in `Confirmed` status.
  - Total amount due is ₹2,124.00.
- **Test Input:**
  - Invoice Number: `INV-2026-0022`
  - Payment Method: `Bank Transfer`
  - Payment Amount: ₹2,124.00
  - Bank Reference / UTR: `UTR-HDFC-9911882233`
- **Steps:**
  1. Submit bank transfer payment entry of ₹2,124.00 with UTR `UTR-HDFC-9911882233`.
  2. Inspect response and invoice status.
- **Expected Result:**
  - Payment is approved and recorded.
  - Invoice status transitions to `Paid`.
  - Payment method is marked as `Bank Transfer` with reference stored.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case P04: Reject underpayment
- **Test ID:** P04
- **Test Description:** Verify that submitting any payment amount less than the full invoice balance is strictly rejected under the full-payment-only business rule.
- **Preconditions:**
  - Invoice `INV-2026-0023` is in `Confirmed` status.
  - Total amount due is ₹2,124.00.
- **Test Input:**
  - Invoice Number: `INV-2026-0023`
  - Payment Method: `UPI`
  - Payment Amount: ₹2,000.00 (underpayment by ₹124.00)
- **Steps:**
  1. Submit payment of ₹2,000.00 against `INV-2026-0023`.
  2. Capture validation error message and check invoice status.
- **Expected Result:**
  - Payment is rejected with error: "Partial payment is not supported. Full payment of ₹2,124.00 is required."
  - No payment is credited.
  - Invoice status remains `Confirmed` (unpaid).
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case P05: Reject overpayment
- **Test ID:** P05
- **Test Description:** Verify that submitting a payment amount greater than the invoice total is rejected.
- **Preconditions:**
  - Invoice `INV-2026-0024` is in `Confirmed` status.
  - Total amount due is ₹2,124.00.
- **Test Input:**
  - Invoice Number: `INV-2026-0024`
  - Payment Method: `Cash`
  - Payment Amount: ₹2,500.00 (overpayment by ₹376.00)
- **Steps:**
  1. Submit payment of ₹2,500.00 for `INV-2026-0024`.
  2. Capture validation response.
- **Expected Result:**
  - Payment is rejected with error: "Payment amount exceeds invoice total. Exact amount of ₹2,124.00 is required."
  - Invoice status remains `Confirmed`.
  - No payment record is created.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case P06: Reject payment for an already-paid invoice
- **Test ID:** P06
- **Test Description:** Verify that once an invoice is marked as `Paid`, any subsequent payment submission is rejected.
- **Preconditions:**
  - Invoice `INV-2026-0025` is already in `Paid` status.
  - Balance due is ₹0.00.
- **Test Input:**
  - Invoice Number: `INV-2026-0025`
  - Payment Method: `UPI`
  - Payment Amount: ₹2,124.00
- **Steps:**
  1. Confirm invoice status is `Paid`.
  2. Attempt to submit a second payment of ₹2,124.00.
- **Expected Result:**
  - Payment is rejected with error: "Invoice is already paid."
  - No second payment entry is registered.
  - Invoice status remains `Paid` without balance modification.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case P07: Reject payment for a cancelled invoice
- **Test ID:** P07
- **Test Description:** Verify that payment processing rejects payments for an invoice in `Cancelled` status across all payment methods.
- **Preconditions:**
  - Invoice `INV-2026-0026` has status `Cancelled`.
- **Test Input:**
  - Invoice Number: `INV-2026-0026`
  - Payment Method: `Bank Transfer`
  - Payment Amount: ₹2,124.00
- **Steps:**
  1. Submit bank transfer payment for `INV-2026-0026`.
  2. Check system validation response.
- **Expected Result:**
  - Payment is rejected with error: "Cannot process payment on a cancelled invoice."
  - Invoice remains `Cancelled`.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case P08: Reject invalid or negative payment amounts
- **Test ID:** P08
- **Test Description:** Verify that non-positive, zero, negative, or malformed numeric payment values are rejected during validation.
- **Preconditions:**
  - Invoice `INV-2026-0027` is in `Confirmed` status (total ₹2,124.00).
- **Test Input:**
  - Test run 1: Amount = `0.00`
  - Test run 2: Amount = `-2124.00`
  - Test run 3: Amount = `NaN` or non-numeric string
- **Steps:**
  1. Submit payment for `INV-2026-0027` with amount ₹0.00.
  2. Submit payment for `INV-2026-0027` with amount -₹2,124.00.
  3. Submit payment with invalid non-numeric amount.
- **Expected Result:**
  - All invalid inputs are rejected with validation errors (e.g., "Payment amount must be greater than zero").
  - No payments are applied.
  - Invoice status remains `Confirmed`.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

### 4. Invoice Calculation Tests

#### Calculation Rules & Formulas

All monetary calculations must be executed using fixed-point / decimal arithmetic to avoid floating-point binary inaccuracies.

1. **Subtotal ($S$):** Sum of line items ($Qty \times Unit Price$).
2. **Discount Amount ($D$):**
   - *Percentage Discount ($P\%$):* $D = S \times (P / 100)$
   - *Fixed Discount ($F$):* $D = F$ (Maximum discount capping behavior where $D = \min(F, S)$ is optional, pending confirmation from Member 2 — discount rules owner)
3. **Taxable Amount ($T$):** $T = S - D$
4. **Tax Amount ($X$):** $X = T \times (TaxRate / 100)$
5. **Final Invoice Total:** $Total = T + X = (S - D) + X$
6. **Rounding Rule:** All intermediary discount amounts, tax amounts, and the final total are rounded to two decimal places using standard half-up financial rounding (`Decimal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)`).

---

> [!IMPORTANT]
> **Domain Ownership & Tax/Discount Assumptions Requiring Confirmation:**
> 
> **Module Ownership:**
> - **Member 2** owns **Products, Plans, Taxes and Discounts**.
> - **Member 3** owns **Subscriptions and Customers**.
> 
> As the owner of Products, Plans, Taxes and Discounts, **Member 2** must confirm:
> 1. **Whether product and plan prices are tax-exclusive or tax-inclusive.** *(Current working assumption: Tax-exclusive pricing, where taxes are added on top of the net taxable base.)*
> 2. **Whether discounts are applied before tax calculation.** *(Current working assumption: Tax-after-discount, where discounts reduce the base subtotal before tax is applied: $\text{Taxable Amount} = \text{Subtotal} - \text{Discount}$.)*
> 3. **How tax rates are selected and applied.** *(Current working assumption: Standard 18% rate, pending final specification on tax slabs, categories, or customer-location-based rules.)*
> 
> *Formal confirmation from Member 2 is required to ensure calculation consistency across product definitions, subscription billing, and invoice rendering.*

---

#### Reference Calculation Example

| Calculation Component | Formula / Derivation | Amount |
| :--- | :--- | :--- |
| **Subtotal** | Base Subscription Plan Rate | **₹2,000.00** |
| **Discount** | 10% of Subtotal | **10%** |
| **Discount Amount** | $₹2,000.00 \times 0.10$ | **₹200.00** |
| **Taxable Amount** | $₹2,000.00 - ₹200.00$ | **₹1,800.00** |
| **Tax Rate** | Standard GST / Tax Rate | **18%** |
| **Tax Amount** | 18% of ₹1,800.00 ($₹1,800.00 \times 0.18$) | **₹324.00** |
| **Final Invoice Total** | Taxable Amount + Tax Amount ($₹1,800.00 + ₹324.00$) | **₹2,124.00** |

---

#### Test Case C01: Standard calculation with percentage discount (Reference Example)
- **Test ID:** C01
- **Test Description:** Validate invoice total calculation with standard 10% discount and 18% tax on a ₹2,000.00 subtotal.
- **Preconditions:**
  - System tax engine configured with 18% standard tax rate.
  - Tax-exclusive pricing and tax-after-discount rules apply.
- **Test Input:**
  - Line Items: 1x Professional Plan at ₹2,000.00
  - Subtotal: ₹2,000.00
  - Discount Type: Percentage (`10%`)
  - Tax Rate: `18%`
- **Steps:**
  1. Create invoice with specified line items, 10% discount, and 18% tax.
  2. Calculate subtotal, discount amount, taxable amount, tax amount, and total.
- **Expected Result:**
  - Subtotal: ₹2,000.00
  - Discount amount: ₹200.00
  - Taxable amount: ₹1,800.00
  - Tax amount: ₹324.00
  - Final invoice total: ₹2,124.00
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case C02: Calculation with fixed discount
- **Test ID:** C02
- **Test Description:** Validate invoice calculation using a fixed rupee discount amount.
- **Preconditions:**
  - System tax rate is 18%.
- **Test Input:**
  - Subtotal: ₹1,500.00
  - Discount Type: Fixed
  - Discount Amount: ₹250.00
  - Tax Rate: `18%`
- **Steps:**
  1. Calculate taxable amount: $1,500.00 - 250.00 = 1,250.00$.
  2. Calculate tax amount: $1,250.00 \times 0.18 = 225.00$.
  3. Calculate final invoice total: $1,250.00 + 225.00 = 1,475.00$.
- **Expected Result:**
  - Subtotal: ₹1,500.00
  - Discount amount: ₹250.00
  - Taxable amount: ₹1,250.00
  - Tax amount: ₹225.00
  - Final invoice total: ₹1,475.00
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case C03: Calculation with zero discount
- **Test ID:** C03
- **Test Description:** Validate calculation when no discount is applied to the invoice.
- **Preconditions:**
  - System tax rate is 18%.
- **Test Input:**
  - Subtotal: ₹1,000.00
  - Discount Amount: ₹0.00
  - Tax Rate: `18%`
- **Steps:**
  1. Calculate taxable amount: $1,000.00 - 0.00 = 1,000.00$.
  2. Calculate tax: $1,000.00 \times 0.18 = 180.00$.
  3. Calculate total: $1,000.00 + 180.00 = 1,180.00$.
- **Expected Result:**
  - Subtotal: ₹1,000.00
  - Discount amount: ₹0.00
  - Taxable amount: ₹1,000.00
  - Tax amount: ₹180.00
  - Final invoice total: ₹1,180.00
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case C04: Rounding to two decimal places with fractional values
- **Test ID:** C04
- **Test Description:** Validate precise rounding to two decimal places when line items, discounts, or tax computations produce fractional paise (more than 2 decimal places).
- **Preconditions:**
  - Decimal rounding configured to `ROUND_HALF_UP` to two decimal places.
- **Test Input:**
  - Line Items: 1 item at ₹149.99
  - Discount: 15%
  - Tax Rate: 18%
- **Steps:**
  1. Compute raw discount: $149.99 \times 0.15 = 22.4985 \rightarrow$ rounded to ₹22.50.
  2. Compute taxable amount: $149.99 - 22.50 = 127.49$.
  3. Compute raw tax: $127.49 \times 0.18 = 22.9482 \rightarrow$ rounded to ₹22.95.
  4. Compute final total: $127.49 + 22.95 = 150.44$.
- **Expected Result:**
  - Subtotal: ₹149.99
  - Discount: ₹22.50
  - Taxable amount: ₹127.49
  - Tax amount: ₹22.95
  - Final total: ₹150.44
  - No floating-point rounding errors or precision leaks.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case C05: Maximum discount capping (OPTIONAL — Pending confirmation from Member 2 — discount rules owner)
- **Test ID:** C05
- **Test Description:** *(OPTIONAL — Pending confirmation from Member 2 — discount rules owner)* Validate behavior when a fixed promotional discount exceeds the invoice subtotal. Note that maximum discount capping is not an agreed business requirement yet and is subject to policy decision by Member 2 (e.g., whether discounts are capped at 100% of subtotal, or whether discounts exceeding subtotal are rejected).
- **Preconditions:**
  - Optional rule under review: Discount capping policy is confirmed and enabled by Member 2.
  - Subtotal is ₹500.00.
  - A fixed promotional discount of ₹600.00 is attempted.
- **Test Input:**
  - Subtotal: ₹500.00
  - Fixed Discount: ₹600.00
  - Tax Rate: 18%
- **Steps:**
  1. Evaluate discount cap rule under consideration: $\min(500.00, 600.00) = 500.00$.
  2. Calculate taxable amount: $500.00 - 500.00 = 0.00$.
  3. Calculate tax: $0.00 \times 0.18 = 0.00$.
  4. Calculate final total: $0.00$.
- **Expected Result:**
  - If capping policy is confirmed by Member 2: Discount amount is capped at ₹500.00, taxable amount is ₹0.00, tax amount is ₹0.00, and final invoice total is ₹0.00 (invoice total cannot be negative).
  - If rejection policy is adopted instead by Member 2: System rejects the discount with a validation error indicating discount exceeds subtotal.
  - *Final expected outcome pending confirmation from Member 2 — discount rules owner.*
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

### 5. Business Rules

The Brightloop Billing, Invoices, and Payments subsystem operates under strict financial business rules:

1. **Full Payments Only:** Partial payments are prohibited. An invoice must be paid in full in a single transaction. Underpayments are rejected, and overpayments are rejected.
2. **Supported Payment Methods:** Only three payment methods are supported:
   - `Cash`
   - `UPI`
   - `Bank Transfer`
   Any other payment method string must be rejected.
3. **Standard Invoice Numbering:**
   - Format: `INV-YYYY-XXXX` (e.g., `INV-2026-0001`).
   - `YYYY` represents the four-digit calendar year of issue.
   - `XXXX` represents a zero-padded 4-digit sequential integer reset annually.
   - Invoice numbers are immutable once generated.
4. **Invoice Lifecycle Statuses:**
   - `Draft`: Initial created state; can be modified or confirmed.
   - `Confirmed`: Finalized invoice issued to customer; awaiting payment.
   - `Paid`: Full payment received and verified. Immutable state.
   - `Cancelled`: Invoice voided; cannot accept payments or transition to any other status.
5. **Invoice Status State Transitions:**
   - Allowed transitions:
     - `Draft` $\rightarrow$ `Confirmed`
     - `Draft` $\rightarrow$ `Cancelled`
     - `Confirmed` $\rightarrow$ `Paid`
     - `Confirmed` $\rightarrow$ `Cancelled`
   - Disallowed transitions:
     - `Paid` $\rightarrow$ any other status (terminal state)
     - `Cancelled` $\rightarrow$ any other status (terminal state)
     - `Draft` $\rightarrow$ `Paid` (must be confirmed before payment)
6. **Billing Period Idempotency:** Duplicate invoices for the same subscription and the same billing period (`period_start` to `period_end`) must never be created.
7. **Strict Payment Guardrails:**
   - Never accept payments for `Cancelled` invoices.
   - Never accept payments for already `Paid` invoices.
   - A failed or unconfirmed payment transaction must **never** mark an invoice as `Paid`.
8. **Decimal Precision & Monetary Arithmetic:**
   - All currency values must use fixed-point decimal arithmetic (`Decimal`), never binary IEEE-754 floating-point numbers (`float`).
   - Rounding mode is standard half-up (`ROUND_HALF_UP`) to exactly 2 decimal places.

---

### 6. Test Case Format

Every test case in this test suite conforms to the following standard template:

- **Test ID:** Unique alphanumeric identifier (e.g., `B01` for billing, `I01` for invoice, `P01` for payment, `C01` for calculation, `E01` for edge case).
- **Test Description:** Concise statement of the functional scenario and purpose of the test.
- **Preconditions:** Required system and data state prior to test execution.
- **Test Input:** Explicit data values, payloads, and parameters supplied to the test.
- **Steps:** Numbered, sequential actions executed during the test.
- **Expected Result:** Deterministic outcome, state changes, returned values, and side-effects.
- **Pass/Fail Status:** Placeholder `[ ] PASS  [ ] FAIL` to record execution outcomes in test runs.

---

### 7. Additional Edge Cases

#### Test Case E01: Two billing operations running simultaneously
- **Test ID:** E01
- **Test Description:** Verify that concurrent execution of two automated billing jobs does not produce duplicate invoices or race condition anomalies.
- **Preconditions:**
  - Multiple subscriptions are due for billing on `2026-11-01`.
  - Database row-level locking or distributed lock mechanism is active.
- **Test Input:**
  - Process A triggers automated billing for `2026-11-01` at `T0`.
  - Process B triggers automated billing for `2026-11-01` at `T0 + 50ms`.
- **Steps:**
  1. Launch Process A and Process B concurrently against the same subscription set.
  2. Wait for both processes to complete.
  3. Query invoice records grouped by subscription and billing cycle.
- **Expected Result:**
  - Database locking prevents duplicate generation.
  - Exactly one invoice is created per eligible subscription.
  - Process B skips subscriptions already locked or processed by Process A.
  - Zero duplicate invoice records exist.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case E02: Duplicate payment submissions (Idempotency)
- **Test ID:** E02
- **Test Description:** Verify that rapid, duplicate submissions of the exact same payment request (e.g., user double-clicking "Pay Now" or duplicate webhook dispatch) do not double-process or double-credit the invoice.
- **Preconditions:**
  - Invoice `INV-2026-0030` is in `Confirmed` status (amount ₹2,124.00).
- **Test Input:**
  - Request 1: Pay ₹2,124.00 via UPI with reference `UPI-DUP-778899`.
  - Request 2: Pay ₹2,124.00 via UPI with reference `UPI-DUP-778899` (submitted within 100ms of Request 1).
- **Steps:**
  1. Transmit Request 1 and Request 2 concurrently or in immediate succession.
  2. Inspect response codes and recorded payment entries.
- **Expected Result:**
  - Exactly one payment transaction succeeds.
  - Second request is rejected as duplicate or returns idempotent success without double ledger crediting.
  - Invoice balance becomes ₹0.00 and status is `Paid`.
  - Exactly one payment record exists for `INV-2026-0030`.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case E03: Invoice number collision
- **Test ID:** E03
- **Test Description:** Verify that concurrent invoice generation requests do not result in duplicate invoice number collisions.
- **Preconditions:**
  - Current sequence is at `INV-2026-0099`.
- **Test Input:**
  - Two parallel threads generate invoices at the exact same millisecond.
- **Steps:**
  1. Trigger simultaneous invoice generation across two independent threads.
  2. Capture generated invoice numbers.
- **Expected Result:**
  - Thread 1 generates `INV-2026-0100`.
  - Thread 2 generates `INV-2026-0101` (or vice-versa).
  - Database unique constraint on invoice number guarantees no collision.
  - Both invoices are saved with distinct sequence numbers.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case E04: Database transaction failure
- **Test ID:** E04
- **Test Description:** Verify transactional atomicity: if an error occurs during invoice generation or payment processing, the entire transaction rolls back cleanly without leaving orphan or corrupt records.
- **Preconditions:**
  - Invoice `INV-2026-0035` is in `Confirmed` status.
- **Test Input:**
  - Payment of ₹2,124.00 submitted.
  - Simulated database failure (e.g., constraint error or network disconnect) right after inserting payment record but before updating invoice status.
- **Steps:**
  1. Trigger payment processing with an injected database fault on the invoice status update step.
  2. Verify database transaction rollback.
  3. Inspect invoice and payment table state.
- **Expected Result:**
  - Transaction rolls back completely.
  - No partial payment record is persisted.
  - Invoice remains in `Confirmed` status (unpaid).
  - System logs an error and returns a clean transaction failure notification.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case E05: Missing customer information
- **Test ID:** E05
- **Test Description:** Verify that billing generation handles active subscriptions where customer record is incomplete (e.g., missing customer name or billing address) by logging an error and skipping rather than crashing the billing batch.
- **Preconditions:**
  - Subscription `SUB-4001` is active and due for billing.
  - Associated customer record has missing or null billing details.
- **Test Input:**
  - Subscription ID: `SUB-4001`
  - Incomplete customer record: `CUST-999`
  - Billing Run Date: `2026-11-01`
- **Steps:**
  1. Run automated billing batch including `SUB-4001` and valid subscriptions.
  2. Check billing run logs and invoice output.
- **Expected Result:**
  - Billing run catches missing customer profile validation error.
  - `SUB-4001` is flagged with error: "Missing required customer billing information."
  - Entire batch run does not crash; other valid subscriptions in the batch process successfully.
  - No corrupt invoice is generated for `SUB-4001`.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case E06: Invalid billing period
- **Test ID:** E06
- **Test Description:** Verify that invoice generation rejects invalid billing periods (e.g., start date greater than end date, inverted dates, or overlapping period dates).
- **Preconditions:**
  - Subscription exists and invoice creation is invoked.
- **Test Input:**
  - Start Date: `2026-11-30`
  - End Date: `2026-11-01` (End date precedes Start date)
- **Steps:**
  1. Attempt to generate an invoice with start date `2026-11-30` and end date `2026-11-01`.
  2. Inspect validation response.
- **Expected Result:**
  - Validation fails with error: "Invalid billing period: period start date must precede period end date."
  - Invoice creation is aborted.
  - No database record is inserted.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`

---

#### Test Case E07: Multi-item fractional rounding discrepancies
- **Test ID:** E07
- **Test Description:** Verify that an invoice containing multiple line items with fractional tax values accumulates line-item amounts and taxes correctly without cumulative rounding discrepancies.
- **Preconditions:**
  - Multiple line items with unit prices producing repeating or fractional decimal taxes.
- **Test Input:**
  - Line Item 1: 3 units @ ₹33.33 = ₹99.99
  - Line Item 2: 7 units @ ₹14.28 = ₹99.96
  - Line Item 3: 1 unit @ ₹100.05 = ₹100.05
  - Discount: 0%
  - Tax Rate: 18%
- **Steps:**
  1. Calculate subtotal: $99.99 + 99.96 + 100.05 = 300.00$.
  2. Calculate tax on taxable amount: $300.00 \times 0.18 = 54.00$.
  3. Calculate final invoice total: $300.00 + 54.00 = 354.00$.
  4. Compare total with individual line-item rounded tax sums to ensure system-wide consistency.
- **Expected Result:**
  - Subtotal: ₹300.00
  - Taxable Amount: ₹300.00
  - Total Tax: ₹54.00
  - Final Total: ₹354.00
  - Line item sum equals invoice total exactly with no 1-paise variance.
- **Pass/Fail Status:** `[ ] PASS  [ ] FAIL`
