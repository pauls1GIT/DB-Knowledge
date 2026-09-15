from .entities import ArticleStatus, ArticleVersion, ReviewDecision


class DomainRuleViolation(ValueError):
    pass


def validate_review_for_publication(decision: ReviewDecision) -> None:
    if decision != ReviewDecision.APPROVE:
        raise DomainRuleViolation("Publication requires APPROVE.")


def ensure_can_embed(version: ArticleVersion) -> None:
    if version.status != ArticleStatus.PUBLISHED:
        raise DomainRuleViolation("Only published article versions may be embedded.")
