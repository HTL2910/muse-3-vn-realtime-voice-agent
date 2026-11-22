"""SME Self-Serve Integration Hub + Onboarding Wizard (approach_14, P1).

fix_missing_sme_onboarding_hub — the SME packaging layer. It does NOT sit
on the live call path; it gets a small business connected in a day:

- Adapter registry with ONE common interface for prebuilt connectors:
  Shopify, Haravan, Sapo (orders), Pancake (CRM/orders), KiotViet
  (POS/orders), Google Sheets / Excel import (orders + FAQ), and a
  generic REST/Webhook sample adapter. An SME starts with just 1-2
  adapters (orders + FAQ) and extends later.
- Every adapter provides: required config, health_check, a UI field
  mapping (external field -> canonical field), normalisation into the
  canonical order/FAQ schema, and test_query runnable inside the wizard.
  Live HTTP goes through an injected ``transport`` callable; without one
  the adapter runs in sandbox mode against built-in sample payloads, so
  the wizard is fully exercisable before real credentials exist.
- Data-quality gate: imported records are checked for missing/garbage
  data (missing order code / phone, duplicate order codes, bad phone
  format, negative totals, empty FAQ answers). Critical errors block
  go-live; warnings are surfaced to the SME before AI is enabled.
- Wizard: exactly 5 ordered steps — (1) telephony (cloud PBX / SIP
  trunk), (2) data source, (3) FAQ/policy import, (4) escalation rules +
  working hours, (5) test call + go-live. Steps cannot be skipped, and
  go_live re-validates everything (health, data quality, test call).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

# Rebased onto contracts v1.0.0 (fix_rebase_remaining_fullstack):
# escalation-rule reasons come from contracts' EscalationReason.
from src.contracts import EscalationReason

REQUIRED_ESCALATION_REASONS = (
    EscalationReason.SENSITIVE.value,
    EscalationReason.CUSTOMER_REQUEST.value,
)

CANONICAL_ORDER_FIELDS = ("order_code", "phone", "status", "total",
                          "customer_name", "created_at")
REQUIRED_ORDER_FIELDS = ("order_code", "phone", "status")


# --- Field mapping -------------------------------------------------------------
def apply_mapping(record: Dict[str, Any], mapping: Dict[str, str]) -> Dict[str, Any]:
    """mapping: external_field -> canonical_field."""
    out: Dict[str, Any] = {}
    for ext, canon in mapping.items():
        if ext in record and record[ext] not in (None, ""):
            out[canon] = record[ext]
    return out


def validate_mapping(mapping: Dict[str, str],
                     required=REQUIRED_ORDER_FIELDS) -> List[str]:
    mapped = set(mapping.values())
    return [f"unmapped_required_field:{f}" for f in required if f not in mapped]


# --- Data quality ------------------------------------------------------------------
_PHONE_RE = re.compile(r"^0\d{9}$")


def data_quality_report(records: List[Dict[str, Any]],
                        kind: str = "orders") -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    seen_codes = set()
    for i, r in enumerate(records):
        if kind == "orders":
            code = r.get("order_code")
            if not code:
                errors.append(f"record_{i}:missing_order_code")
            elif code in seen_codes:
                errors.append(f"record_{i}:duplicate_order_code:{code}")
            else:
                seen_codes.add(code)
            phone = str(r.get("phone") or "")
            if not phone:
                errors.append(f"record_{i}:missing_phone")
            elif not _PHONE_RE.match(phone):
                warnings.append(f"record_{i}:bad_phone_format:{phone}")
            total = r.get("total")
            if total is not None:
                try:
                    if float(total) < 0:
                        errors.append(f"record_{i}:negative_total")
                except (TypeError, ValueError):
                    warnings.append(f"record_{i}:total_not_numeric")
            if not r.get("status"):
                warnings.append(f"record_{i}:missing_status")
        else:  # faq
            if not (r.get("question") or "").strip():
                errors.append(f"record_{i}:empty_question")
            if not (r.get("answer") or "").strip():
                errors.append(f"record_{i}:empty_answer")
    return {"errors": errors, "warnings": warnings,
            "ok": not errors, "records": len(records)}


# --- Adapters ------------------------------------------------------------------------
@dataclass
class HealthResult:
    ok: bool
    adapter: str
    detail: str = ""
    missing_config: List[str] = field(default_factory=list)


@dataclass
class TestQueryResult:
    ok: bool
    adapter: str
    records: List[Dict[str, Any]] = field(default_factory=list)
    detail: str = ""


class BaseAdapter:
    name = "base"
    kind = "orders"                 # orders | faq | crm | pos | sheets
    required_config: tuple = ()
    default_mapping: Dict[str, str] = {}
    sample_records: List[Dict[str, Any]] = []

    def __init__(self, config: Optional[Dict[str, Any]] = None,
                 transport: Optional[Callable] = None,
                 mapping: Optional[Dict[str, str]] = None):
        self.config = dict(config or {})
        self.transport = transport
        self.mapping = dict(mapping or self.default_mapping)

    @property
    def sandbox(self) -> bool:
        return self.transport is None

    def missing_config(self) -> List[str]:
        return [k for k in self.required_config if not self.config.get(k)]

    def health_check(self) -> HealthResult:
        missing = self.missing_config()
        if missing:
            return HealthResult(False, self.name, "missing_config", missing)
        if self.transport is not None:
            try:
                ok = bool(self.transport("health", {}))
            except Exception as exc:  # a dead connector must read unhealthy
                return HealthResult(False, self.name, f"transport_error:{exc}")
            return HealthResult(ok, self.name, "live" if ok else "unreachable")
        return HealthResult(True, self.name, "sandbox")

    def _fetch_raw(self) -> List[Dict[str, Any]]:
        if self.transport is not None:
            return list(self.transport("query", {}) or [])
        return [dict(r) for r in self.sample_records]

    def test_query(self) -> TestQueryResult:
        health = self.health_check()
        if not health.ok:
            return TestQueryResult(False, self.name, [], health.detail)
        map_errors = validate_mapping(self.mapping) if self.kind in (
            "orders", "pos", "crm") else []
        if map_errors:
            return TestQueryResult(False, self.name, [], ";".join(map_errors))
        records = [apply_mapping(r, self.mapping) for r in self._fetch_raw()]
        return TestQueryResult(True, self.name, records,
                               "sandbox" if self.sandbox else "live")


_SAMPLE_ORDER = {"id": "DH100001", "phone": "0901234567",
                 "status": "shipping", "total": 350000,
                 "customer": "Anh Minh", "created": "2026-11-20"}


class ShopifyAdapter(BaseAdapter):
    name = "shopify"; kind = "orders"
    required_config = ("shop_domain", "access_token")
    default_mapping = {"id": "order_code", "phone": "phone",
                       "status": "status", "total": "total",
                       "customer": "customer_name", "created": "created_at"}
    sample_records = [_SAMPLE_ORDER]


class HaravanAdapter(BaseAdapter):
    name = "haravan"; kind = "orders"
    required_config = ("shop_domain", "access_token")
    default_mapping = {"order_number": "order_code", "phone": "phone",
                       "financial_status": "status", "total_price": "total",
                       "customer_name": "customer_name",
                       "created_at": "created_at"}
    sample_records = [{"order_number": "HR200001", "phone": "0912345678",
                       "financial_status": "paid", "total_price": 500000,
                       "customer_name": "Chị Hà", "created_at": "2026-11-20"}]


class SapoAdapter(BaseAdapter):
    name = "sapo"; kind = "orders"
    required_config = ("shop_domain", "api_key")
    default_mapping = {"code": "order_code", "phone": "phone",
                       "status": "status", "total": "total",
                       "customer": "customer_name", "created": "created_at"}
    sample_records = [{"code": "SP300001", "phone": "0923456789",
                       "status": "delivered", "total": 200000,
                       "customer": "Anh Tuấn", "created": "2026-11-19"}]


class PancakeAdapter(BaseAdapter):
    name = "pancake"; kind = "crm"
    required_config = ("shop_id", "api_key")
    default_mapping = {"order_id": "order_code", "customer_phone": "phone",
                       "status": "status", "total": "total",
                       "customer_name": "customer_name",
                       "inserted_at": "created_at"}
    sample_records = [{"order_id": "PK400001", "customer_phone": "0934567890",
                       "status": "confirmed", "total": 150000,
                       "customer_name": "Chị Lan", "inserted_at": "2026-11-21"}]


class KiotVietAdapter(BaseAdapter):
    name = "kiotviet"; kind = "pos"
    required_config = ("retailer", "client_id", "client_secret")
    default_mapping = {"code": "order_code", "customerPhone": "phone",
                       "status": "status", "total": "total",
                       "customerName": "customer_name",
                       "purchaseDate": "created_at"}
    sample_records = [{"code": "KV500001", "customerPhone": "0945678901",
                       "status": "completed", "total": 420000,
                       "customerName": "Anh Dũng", "purchaseDate": "2026-11-21"}]


class GoogleSheetsAdapter(BaseAdapter):
    """Google Sheets / Excel import: rows are supplied directly (the file
    has already been parsed to a list of dicts by the upload layer)."""
    name = "google_sheets"; kind = "sheets"
    required_config = ()
    default_mapping = {"Mã đơn": "order_code", "SĐT": "phone",
                       "Trạng thái": "status", "Tổng tiền": "total",
                       "Tên khách": "customer_name", "Ngày tạo": "created_at"}
    sample_records = [{"Mã đơn": "GS600001", "SĐT": "0956789012",
                       "Trạng thái": "shipping", "Tổng tiền": 99000,
                       "Tên khách": "Chị Mai", "Ngày tạo": "2026-11-22"}]

    def __init__(self, *a, rows: Optional[List[Dict[str, Any]]] = None, **kw):
        super().__init__(*a, **kw)
        self.rows = rows

    def _fetch_raw(self):
        return [dict(r) for r in (self.rows if self.rows is not None
                                  else self.sample_records)]


class RestWebhookAdapter(BaseAdapter):
    name = "rest_webhook"; kind = "orders"
    required_config = ("base_url",)
    default_mapping = dict(ShopifyAdapter.default_mapping)
    sample_records = [_SAMPLE_ORDER]


_ADAPTER_CLASSES = {c.name: c for c in (
    ShopifyAdapter, HaravanAdapter, SapoAdapter, PancakeAdapter,
    KiotVietAdapter, GoogleSheetsAdapter, RestWebhookAdapter)}


class AdapterRegistry:
    def __init__(self):
        self._classes = dict(_ADAPTER_CLASSES)

    def register(self, adapter_cls) -> None:
        self._classes[adapter_cls.name] = adapter_cls

    def list_adapters(self) -> List[Dict[str, str]]:
        return [{"name": c.name, "kind": c.kind,
                 "required_config": list(c.required_config)}
                for c in self._classes.values()]

    def create(self, name: str, config=None, transport=None,
               mapping=None, **kw) -> BaseAdapter:
        if name not in self._classes:
            raise ValueError(f"unknown_adapter:{name}")
        return self._classes[name](config=config, transport=transport,
                                   mapping=mapping, **kw)

    get = create


# --- Wizard ----------------------------------------------------------------------------
class WizardStep(str, Enum):
    TELEPHONY = "1_telephony"
    DATA_SOURCE = "2_data_source"
    KNOWLEDGE = "3_knowledge"
    ESCALATION_RULES = "4_escalation_rules"
    TEST_AND_GO_LIVE = "5_test_and_go_live"


STEP_ORDER = list(WizardStep)


@dataclass
class GoLiveResult:
    live: bool
    blocked_reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class OnboardingWizard:
    def __init__(self, tenant_id: str, registry: Optional[AdapterRegistry] = None):
        self.tenant_id = tenant_id
        self.registry = registry or AdapterRegistry()
        self.completed: List[WizardStep] = []
        self.telephony: Dict[str, Any] = {}
        self.adapters: List[BaseAdapter] = []
        self.order_records: List[Dict[str, Any]] = []
        self.faq_records: List[Dict[str, Any]] = []
        self.escalation_rules: Dict[str, Any] = {}
        self.working_hours: Dict[str, Any] = {}
        self.test_call_passed = False
        self.live = False

    @property
    def current_step(self) -> Optional[WizardStep]:
        for s in STEP_ORDER:
            if s not in self.completed:
                return s
        return None

    def progress(self) -> Dict[str, Any]:
        return {"completed": [s.value for s in self.completed],
                "current": self.current_step.value if self.current_step else None,
                "total_steps": len(STEP_ORDER)}

    def _require_step(self, step: WizardStep) -> None:
        if self.current_step is not step:
            raise ValueError(
                f"step_out_of_order:expected_{self.current_step},got_{step}")

    # Step 1
    def complete_telephony(self, provider: str, phone_number: str,
                           sip_trunk: str = "") -> None:
        self._require_step(WizardStep.TELEPHONY)
        if not provider or not phone_number:
            raise ValueError("telephony_requires_provider_and_number")
        self.telephony = {"provider": provider, "phone_number": phone_number,
                          "sip_trunk": sip_trunk}
        self.completed.append(WizardStep.TELEPHONY)

    # Step 2
    def connect_data_source(self, adapter_name: str, config=None,
                            transport=None, mapping=None, **kw) -> TestQueryResult:
        self._require_step(WizardStep.DATA_SOURCE)
        adapter = self.registry.create(adapter_name, config=config,
                                       transport=transport, mapping=mapping, **kw)
        result = adapter.test_query()
        if not result.ok:
            raise ValueError(f"data_source_test_failed:{result.detail}")
        self.adapters.append(adapter)
        if adapter.kind in ("orders", "pos", "crm", "sheets"):
            self.order_records.extend(result.records)
        self.completed.append(WizardStep.DATA_SOURCE)
        return result

    # Step 3
    def import_knowledge(self, faq_records: List[Dict[str, Any]]) -> Dict[str, Any]:
        self._require_step(WizardStep.KNOWLEDGE)
        report = data_quality_report(faq_records, kind="faq")
        if report["errors"]:
            raise ValueError(f"faq_data_errors:{report['errors']}")
        if not faq_records:
            raise ValueError("knowledge_requires_at_least_one_faq")
        self.faq_records = list(faq_records)
        self.completed.append(WizardStep.KNOWLEDGE)
        return report

    # Step 4
    def configure_escalation(self, rules: Dict[str, Any],
                             working_hours: Dict[str, Any]) -> None:
        self._require_step(WizardStep.ESCALATION_RULES)
        for reason in REQUIRED_ESCALATION_REASONS:
            if reason not in rules:
                raise ValueError(f"escalation_rule_missing:{reason}")
        if not working_hours.get("open") or not working_hours.get("close"):
            raise ValueError("working_hours_required")
        self.escalation_rules = dict(rules)
        self.working_hours = dict(working_hours)
        self.completed.append(WizardStep.ESCALATION_RULES)

    # Step 5
    def run_test_call(self) -> bool:
        """Simulated test call inside the wizard: an order lookup through
        the connected adapter + an FAQ hit must both succeed."""
        self._require_step(WizardStep.TEST_AND_GO_LIVE)
        ok_order = bool(self.order_records) and all(
            a.test_query().ok for a in self.adapters)
        ok_faq = bool(self.faq_records)
        self.test_call_passed = bool(ok_order and ok_faq)
        return self.test_call_passed

    def go_live(self) -> GoLiveResult:
        blocked: List[str] = []
        if self.current_step is not None and \
                self.current_step is not WizardStep.TEST_AND_GO_LIVE:
            blocked.append(f"wizard_incomplete:{self.current_step.value}")
        if not self.test_call_passed:
            blocked.append("test_call_not_passed")
        for a in self.adapters:
            if not a.health_check().ok:
                blocked.append(f"adapter_unhealthy:{a.name}")
        report = data_quality_report(self.order_records, kind="orders")
        if report["errors"]:
            blocked.append(f"order_data_errors:{report['errors']}")
        if blocked:
            return GoLiveResult(False, blocked, report["warnings"])
        self.completed.append(WizardStep.TEST_AND_GO_LIVE)
        self.live = True
        return GoLiveResult(True, [], report["warnings"])


# Short alias
SMEOnboardingHub = OnboardingWizard

__all__ = [
    "REQUIRED_ESCALATION_REASONS",
    "CANONICAL_ORDER_FIELDS", "REQUIRED_ORDER_FIELDS", "apply_mapping",
    "validate_mapping", "data_quality_report", "HealthResult",
    "TestQueryResult", "BaseAdapter", "ShopifyAdapter", "HaravanAdapter",
    "SapoAdapter", "PancakeAdapter", "KiotVietAdapter", "GoogleSheetsAdapter",
    "RestWebhookAdapter", "AdapterRegistry", "WizardStep", "STEP_ORDER",
    "GoLiveResult", "OnboardingWizard", "SMEOnboardingHub",
]
