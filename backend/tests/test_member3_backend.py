import os
import unittest
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine, select

# Set in-memory SQLite database for isolated test execution
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.models import (
    Customer,
    CustomerStatus,
    Product,
    ProductType,
    Plan,
    BillingInterval,
    Quotation,
    QuotationStatus,
    Subscription,
    SubscriptionStatus,
    get_utc_now,
)
from app.db import get_session
from app.routers.subscriptions import router as subscriptions_router


from sqlalchemy.pool import StaticPool

class Member3BackendTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Configure isolated in-memory engine with StaticPool so all sessions share the memory DB
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(cls.engine)

        cls.app = FastAPI(title="Brightloop Test App")
        cls.app.include_router(subscriptions_router, prefix="/api")

        def override_get_session():
            with Session(cls.engine) as session:
                yield session

        cls.app.dependency_overrides[get_session] = override_get_session
        cls.client = TestClient(cls.app)

        # Seed sample product and plans
        with Session(cls.engine) as session:
            product = Product(
                name="Cloud SaaS Platform",
                code="PROD-CLOUD",
                type=ProductType.RECURRING,
                is_active=True,
            )
            session.add(product)
            session.commit()
            session.refresh(product)

            plan1 = Plan(
                product_id=product.id,
                name="Growth Plan",
                code="PLAN-GROWTH",
                price_paise=299900,  # ₹2,999.00
                currency="INR",
                billing_interval=BillingInterval.MONTHLY,
                trial_period_days=0,
                is_active=True,
            )
            plan2 = Plan(
                product_id=product.id,
                name="Annual Enterprise",
                code="PLAN-ENTERPRISE",
                price_paise=2999900,  # ₹29,999.00
                currency="INR",
                billing_interval=BillingInterval.YEARLY,
                trial_period_days=14,
                is_active=True,
            )
            session.add_all([plan1, plan2])
            session.commit()
            session.refresh(plan1)
            session.refresh(plan2)

            cls.plan_growth_id = plan1.id
            cls.plan_enterprise_id = plan2.id

    # =========================================================================
    # 1. CUSTOMER MANAGEMENT TESTS
    # =========================================================================
    def test_01_create_customer(self):
        payload = {
            "name": "Acme Innovations Pvt Ltd",
            "email": "contact@acme.in",
            "phone": "+91 9876543210",
            "company_name": "Acme Corp",
            "gstin": "32AAAAA0000A1Z5",
            "billing_address": "MG Road, Kochi",
            "city": "Kochi",
            "state": "Kerala",
            "postal_code": "682001",
            "country": "India",
            "currency": "INR",
        }
        res = self.client.post("/api/customers", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["name"], payload["name"])
        self.assertEqual(data["email"], payload["email"])
        self.assertEqual(data["status"], "active")
        self.assertIn("id", data)
        self.__class__.customer_acme_id = data["id"]

    def test_02_duplicate_customer_email_rejected(self):
        payload = {
            "name": "Duplicate Acme",
            "email": "contact@acme.in",  # same email
        }
        res = self.client.post("/api/customers", json=payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("already exists", res.json()["detail"])

    def test_03_list_customers_with_search(self):
        # Create second customer
        self.client.post(
            "/api/customers",
            json={"name": "Beta Technologies", "email": "admin@betatech.com", "company_name": "Beta Inc"},
        )
        res = self.client.get("/api/customers?search=Acme")
        self.assertEqual(res.status_code, 200)
        items = res.json()
        self.assertGreaterEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "Acme Innovations Pvt Ltd")

    def test_04_update_customer(self):
        res = self.client.put(
            f"/api/customers/{self.customer_acme_id}",
            json={"phone": "+91 9999999999", "company_name": "Acme Global"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["phone"], "+91 9999999999")
        self.assertEqual(data["company_name"], "Acme Global")

    # =========================================================================
    # 2. QUOTATIONS TESTS
    # =========================================================================
    def test_05_create_quotation(self):
        payload = {
            "customer_id": self.customer_acme_id,
            "expiry_days": 14,
            "discount_paise": 49900,  # ₹499.00 discount
            "tax_rate_basis_points_snapshot": 1800,  # 18.00% GST
            "notes": "Custom introductory offer for Acme Global",
            "items": [
                {
                    "description": "Growth Plan Subscription",
                    "quantity": 1,
                    "unit_price_paise": 299900,
                    "plan_id": self.plan_growth_id,
                },
                {
                    "description": "Dedicated Onboarding Assistance",
                    "quantity": 1,
                    "unit_price_paise": 50000,
                    "plan_id": None,
                },
            ],
        }
        res = self.client.post("/api/quotations", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertTrue(data["quotation_number"].startswith("QT-"))
        self.assertEqual(data["status"], "draft")
        self.assertEqual(len(data["items"]), 2)

        # Verify Financial Calculation:
        # Subtotal: 299900 + 50000 = 349900
        # Discount: 49900
        # Taxable: 349900 - 49900 = 300000
        # Tax (18%): (300000 * 1800 + 5000) // 10000 = 54000
        # Total: 300000 + 54000 = 354000
        self.assertEqual(data["subtotal_paise"], 349900)
        self.assertEqual(data["discount_paise"], 49900)
        self.assertEqual(data["tax_paise"], 54000)
        self.assertEqual(data["total_paise"], 354000)
        self.__class__.quotation_acme_id = data["id"]

    def test_06_send_and_accept_quotation(self):
        # 1. Send quotation (Draft -> Sent)
        res_send = self.client.post(f"/api/quotations/{self.quotation_acme_id}/send")
        self.assertEqual(res_send.status_code, 200)
        self.assertTrue(res_send.json()["success"])

        # 2. Accept quotation (Sent -> Accepted) with auto-creation of subscription
        res_accept = self.client.post(f"/api/quotations/{self.quotation_acme_id}/accept?auto_create_subscription=true")
        self.assertEqual(res_accept.status_code, 200)
        data = res_accept.json()
        self.assertTrue(data["success"])
        self.assertIn("subscription_number", data["data"])
        self.assertTrue(data["data"]["subscription_number"].startswith("SUB-"))

    # =========================================================================
    # 3. SUBSCRIPTIONS TESTS
    # =========================================================================
    def test_07_direct_subscription_creation(self):
        payload = {
            "customer_id": self.customer_acme_id,
            "plan_id": self.plan_enterprise_id,
            "quantity": 2,
            "billing_interval": "yearly",
            "auto_renew": True,
        }
        res = self.client.post("/api/subscriptions", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertTrue(data["subscription_number"].startswith("SUB-"))
        self.assertEqual(data["customer_name"], "Acme Innovations Pvt Ltd")
        self.assertEqual(data["plan_name"], "Annual Enterprise")
        self.assertEqual(data["quantity"], 2)
        self.assertEqual(data["billing_interval"], "yearly")
        self.assertIn("normalized_mrr_paise", data)
        self.__class__.sub_enterprise_id = data["id"]

    def test_08_subscription_lifecycle_pause_resume_cancel(self):
        sub_id = self.sub_enterprise_id

        # 1. Pause
        res_pause = self.client.post(f"/api/subscriptions/{sub_id}/pause")
        self.assertEqual(res_pause.status_code, 200)
        check_pause = self.client.get(f"/api/subscriptions/{sub_id}").json()
        self.assertEqual(check_pause["status"], "paused")

        # 2. Resume
        res_resume = self.client.post(f"/api/subscriptions/{sub_id}/resume")
        self.assertEqual(res_resume.status_code, 200)
        check_resume = self.client.get(f"/api/subscriptions/{sub_id}").json()
        self.assertEqual(check_resume["status"], "active")

        # 3. Cancel
        res_cancel = self.client.post(f"/api/subscriptions/{sub_id}/cancel")
        self.assertEqual(res_cancel.status_code, 200)
        check_cancel = self.client.get(f"/api/subscriptions/{sub_id}").json()
        self.assertEqual(check_cancel["status"], "canceled")
        self.assertFalse(check_cancel["auto_renew"])

    # =========================================================================
    # 4. CUSTOMER PORTAL & TENANCY ISOLATION TESTS
    # =========================================================================
    def test_09_portal_profile_and_scoping(self):
        # Query portal profile using X-Customer-Id header
        headers = {"X-Customer-Id": str(self.customer_acme_id)}
        res = self.client.get("/api/portal/profile", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["customer"]["id"], self.customer_acme_id)
        self.assertGreaterEqual(len(data["active_subscriptions"]) + len(data["open_quotations"]), 1)

    def test_10_portal_tenancy_isolation(self):
        # Create Customer B
        res_b = self.client.post(
            "/api/customers",
            json={"name": "Customer B Corp", "email": "user@bcorp.io"},
        )
        customer_b_id = res_b.json()["id"]

        # Customer B attempts to inspect Customer A's subscription
        headers_b = {"X-Customer-Id": str(customer_b_id)}
        res_leak = self.client.get(f"/api/portal/subscriptions/{self.sub_enterprise_id}", headers=headers_b)
        # Must return 404 (or 403) to prevent leaking Customer A's existence or data
        self.assertEqual(res_leak.status_code, 404)


if __name__ == "__main__":
    unittest.main()
