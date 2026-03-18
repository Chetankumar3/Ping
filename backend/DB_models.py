from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

class User(Base):
    __tablename__ =  "User"
    Id: Mapped[int] = mapped_column(primary_key=True)
    Name: Mapped[str] = mapped_column(String(20), index=True)
    MobileNumber: Mapped[str] = mapped_column(String(15))
    Email: Mapped[Optional[str]] = mapped_column(String(30))

class Group(Base):
    __tablename__ =  "Group"
    Id: Mapped[int] = mapped_column(primary_key=True)
    Name: Mapped[str] = mapped_column(String(30), index=True)
    Description: Mapped[Optional[str]] = mapped_column(String(100))

class MapTable(Base):
    __tablename__ =  "map_table"

    Id: Mapped[int] = mapped_column(primary_key=True)
    UserId: Mapped[int] = mapped_column(ForeignKey("User.Id"), index=True)
    GroupId: Mapped[int] = mapped_column(ForeignKey("Group.Id"), index=True)