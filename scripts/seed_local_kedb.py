from uuid import uuid4

from kedb.domain import (
    ArticleStatus,
    ArticleVersion,
    HumanReview,
    KnownError,
    ReviewDecision,
)
from kedb.infrastructure.lakebase.database import Database
from kedb.infrastructure.lakebase.repositories import SqlRepositories


db = Database("sqlite:///kedb-local.db")
db.create_all()

with db.sessions() as session:
    repo = SqlRepositories(session)

    known_error = KnownError(
        title="Database connection timeout to Oracle (ORA-12170)"
    )
    repo.add_known_error(known_error)

    review = HumanReview(
        workflow_id=uuid4(),
        decision=ReviewDecision.APPROVE,
        reviewer="local-test",
        feedback="Seeded for local Resolve Ticket testing.",
    )
    repo.add_review(review)

    version = ArticleVersion(
        known_error_id=known_error.id,
        version_number=1,
        title="Database connection timeout to Oracle (ORA-12170)",
        problem="Application fails to connect to Oracle and returns ORA-12170 connection timeout.",
        root_cause="Database connection timeout to Oracle.",
        solution=(
            "Updated the Oracle connection string, verified listener availability, "
            "and restarted the application service. Connectivity was restored."
        ),
        status=ArticleStatus.PUBLISHED,
        review_id=review.id,
    )

    repo.add_version(version)
    repo.set_current(known_error.id, version.id)

    session.commit()

print("Oracle Known Error seeded successfully.")