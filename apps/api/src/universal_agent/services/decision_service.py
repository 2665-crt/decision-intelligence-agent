from dataclasses import dataclass, field
from uuid import UUID


EVIDENCE_LEVELS = frozenset({"A", "B", "C", "D"})
SENSITIVE_DOMAINS = {"medical", "legal", "financial", "chemical", "construction safety"}


@dataclass(frozen=True)
class EvidenceItem:
    level: str
    artifact_id: UUID | None
    summary: str

    def __post_init__(self) -> None:
        if self.level not in EVIDENCE_LEVELS:
            raise ValueError(f"unsupported evidence level: {self.level}")
        if not self.summary.strip():
            raise ValueError("evidence summary is required")


@dataclass(frozen=True)
class RiskItem:
    description: str
    probability: str
    impact: str
    severity: str
    controllability: str
    evidence: list[EvidenceItem]
    uncertainty: str
    mitigation: list[str]
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

    @property
    def evidence_by_level(self) -> dict[str, list[EvidenceItem]]:
        return {
            level: [item for item in self.evidence if item.level == level]
            for level in ("A", "B", "C", "D")
        }


def requires_human_review(domain: str, user_marked_critical: bool = False) -> bool:
    return user_marked_critical or domain.casefold() in SENSITIVE_DOMAINS


def rank_options(options: list[Option]) -> list[Option]:
    return sorted(
        options,
        key=lambda item: (
            not item.hard_constraints_met,
            item.potential_harm,
            item.implementation_cost,
            -item.expected_benefit,
            item.uncertainty,
        ),
    )


def _default_options() -> list[Option]:
    return [
        Option(
            name="先验证后小范围试点",
            expected_benefit=0.65,
            implementation_cost=0.35,
            potential_harm=0.2,
            uncertainty=0.3,
            assumptions=["关键数据口径已由负责人确认", "试点范围可隔离且可回退"],
            validation_metric="试点核心指标相对基线改善且未触发停止条件",
        ),
        Option(
            name="维持现状并加强监测",
            expected_benefit=0.25,
            implementation_cost=0.15,
            potential_harm=0.35,
            uncertainty=0.4,
            assumptions=["短期内风险暴露可接受"],
            validation_metric="风险指标不突破预设阈值",
        ),
    ]


def build_decision_report(
    *,
    evidence: list[EvidenceItem],
    domain: str,
    user_marked_critical: bool = False,
    options: list[Option] | None = None,
) -> DecisionReport:
    if not evidence:
        raise ValueError("risk items require evidence")
    review_required = requires_human_review(domain, user_marked_critical)
    risk_evidence = [item for item in evidence if item.level in {"A", "B", "C"}] or evidence
    risk = RiskItem(
        description="数据质量、异常信号或预测偏差可能影响目标达成",
        probability="medium",
        impact="high" if review_required else "medium",
        severity="high" if review_required else "medium",
        controllability="medium",
        evidence=risk_evidence,
        uncertainty="风险等级基于当前数据与通用规则，缺少领域阈值时不能视为专业定论。",
        mitigation=[
            "核对原始数据口径、缺失值和异常记录",
            "先设置可回退的小范围试点与停止条件",
            "由责任人复核高影响结论后再执行",
        ],
        human_review_required=review_required,
    )
    suggestions = ["先由负责人核对数据口径与风险条件，再决定是否执行排名靠前的方案。"]
    return DecisionReport(
        domain=domain,
        evidence=evidence,
        risks=[risk],
        options=rank_options(options if options is not None else _default_options()),
        suggestions=suggestions,
    )
