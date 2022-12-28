"""add_email_constraints

Revision ID: 08da162c51bf
Revises: e43177bfe90b
Create Date: 2021-09-11 04:08:38.778281+00:00

"""  # noqa D400, D415
import sqlalchemy as sa
from alembic import op

# revision identifiers
# used by alembic
revision = "08da162c51bf"
down_revision = "e43177bfe90b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Perform actions."""
    op.create_unique_constraint("uq_student_email", "student", ["email"])
    op.alter_column("student", "email", nullable=False, type_=sa.String(128))


def downgrade() -> None:
    """Cancel the actions."""
    op.drop_constraint("uq_student_email", "student", type_="unique")
    op.alter_column("student", "email", nullable=True, type_=sa.String(128))
