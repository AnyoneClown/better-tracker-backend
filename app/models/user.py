from sqlalchemy import Boolean, CheckConstraint, String, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("length(email) <= 254", name="email_max_length"),
        UniqueConstraint("email", name="uq_users_email"),
    )

    email: Mapped[str] = mapped_column(String(254), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    google_subject: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=true(),
        nullable=False,
    )
