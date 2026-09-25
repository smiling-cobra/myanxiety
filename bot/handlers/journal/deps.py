"""Service singletons shared by the journal handlers.

Reach services through this module's attributes — `deps.llm_svc.extract_tags(...)`, never
`from .deps import llm_svc`. A value import binds the real service into the importing module,
where `patch('bot.handlers.journal.deps.llm_svc')` cannot reach it: the patch succeeds, the
handler keeps the real object, and the test passes while hitting a live Anthropic client.
Attribute access keeps one patch point for every handler.
"""
from services.account_service import AccountService
from services.analytics_service import AnalyticsService
from services.export import ExportService
from services.journal_service import JournalService
from services.llm_service import LlmService
from services.payment_service import PaymentService
from services.plan_service import PlanService
from services.usage_service import UsageService
from services.user_service import UserService

user_svc = UserService()
journal_svc = JournalService()
llm_svc = LlmService()
analytics_svc = AnalyticsService()
usage_svc = UsageService()
export_svc = ExportService()
account_svc = AccountService()
plan_svc = PlanService()
payment_svc = PaymentService()
