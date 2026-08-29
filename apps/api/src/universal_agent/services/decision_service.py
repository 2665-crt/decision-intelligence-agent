from dataclasses import dataclass, field
from uuid import UUID

SENSITIVE_DOMAINS = {"medical", "legal", "financial", "chemical", "construction safety"}

@dataclass(frozen=True)
class EvidenceItem:
    level: str
    artifact_id: UUID | None
    summary: str

@dataclass(frozen=True)
class RiskItem:
    description: str
    evidence: list[EvidenceItem]
    human_review_required: bool

@dataclass(frozen=True)
class Option:
    name: str
    expected_benefit: float
    implementation_cost: float
    potential_harm: float
    uncertainty: float
    assumptions: list[str] = field(default_factory=list)
    validation_metric: str = "待定义"
    hard_constraints_met: bool = True

@dataclass(frozen=True)
class DecisionReport:
    domain: str
    evidence: list[EvidenceItem]
    risks: list[RiskItem]
    options: list[Option]
    suggestions: list[str]

def requires_human_review(domain: str, user_marked_critical: bool = False) -> bool:
    return user_marked_critical or domain.casefold() in SENSITIVE_DOMAINS

def rank_options(options: list[Option]) -> list[Option]:
    return sorted(options, key=lambda item: (not item.hard_constraints_met, item.potential_harm, item.implementation_cost, -item.expected_benefit, item.uncertainty))

def build_decision_report(*, evidence: list[EvidenceItem], domain: str, user_marked_critical: bool = False, options: list[Option] | None = None) -> DecisionReport:
    if not evidence:
        raise ValueError("risk items require evidence")
    risk = RiskItem("需要结合数据证据复核的风险信号", evidence, requires_human_review(domain, user_marked_critical))
    return DecisionReport(domain, evidence, [risk], rank_options(options or []), ["待验证建议：先由负责人核对数据口径与风险条件，再决定是否执行方案。"])
