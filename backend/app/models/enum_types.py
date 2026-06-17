"""Portable SQLAlchemy enum helpers."""

from __future__ import annotations

import enum

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


class EnumValueType(TypeDecorator):
    """Persist enum values while accepting legacy enum names on read."""

    impl = String
    cache_ok = True

    def __init__(self, enum_cls: type[enum.Enum]):
        self.enum_cls = enum_cls
        length = max(len(str(member.value)) for member in enum_cls)
        super().__init__(length=length)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, self.enum_cls):
            return value.value
        if isinstance(value, str):
            member = self._member_for(value)
            return member.value if member is not None else value
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        member = self._member_for(value)
        return member if member is not None else value

    def _member_for(self, value: str):
        for member in self.enum_cls:
            if value == member.value or value == member.name:
                return member
        return None


def value_enum(enum_cls: type[enum.Enum]) -> EnumValueType:
    return EnumValueType(enum_cls)
