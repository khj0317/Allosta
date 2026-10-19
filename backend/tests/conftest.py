import os
import tempfile
from datetime import datetime, timedelta

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["SCHEDULER_INTERVAL_SECONDS"] = "0"
os.environ["DEMO_MODE"] = "true"  # 기본값은 꺼짐. 테스트는 인증번호를 응답으로 받기 위해 켠다
os.environ["FAMILY_CODE_RESEND_SECONDS"] = "0"  # 테스트에서는 재발송 간격 제한 없음

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine, now  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Counselor,
    Indicator,
    IndicatorStatus,
    Product,
    Relation,
    Role,
    ServiceType,
    Slot,
    Subject,
    TestResult,
    User,
)
from app.security import create_token, hash_password  # noqa: E402

_PW = hash_password("pw")  # 해시 비용이 커서 1회만 계산


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        yield s


@pytest.fixture()
def client(db):
    with TestClient(app) as c:
        yield c


class Factory:
    def __init__(self, db):
        self.db = db
        self.n = 0

    def _id(self):
        self.n += 1
        return self.n

    def user(self, role=Role.CUSTOMER, name="고객"):
        n = self._id()
        u = User(email=f"u{n}@t.kr", name=name, phone=f"010-1111-{n:04d}", role=role, password_hash=_PW)
        self.db.add(u)
        self.db.commit()
        return u

    def counselor(self, specialties=("METABOLIC",), name="상담사"):
        u = self.user(Role.COUNSELOR, name)
        c = Counselor(user=u, specialties=list(specialties))
        self.db.add(c)
        self.db.commit()
        return c

    def customer_with_result(self, service=ServiceType.METABOLIC, relation=Relation.SELF, consent=True):
        u = self.user()
        s = Subject(owner_id=u.id, name="피검자", relation=relation, consent_at=now() if consent else None)
        self.db.add(s)
        self.db.flush()
        r = TestResult(kit_code=f"K{self._id()}", subject_id=s.id, service_type=service, reported_at=now())
        r.indicators.append(Indicator(category="c", name="지표", value=1, unit="u", status=IndicatorStatus.HIGH))
        self.db.add(r)
        self.db.commit()
        return u, s, r

    def slot(self, counselor, start: datetime):
        s = Slot(counselor_id=counselor.id, start_at=start, end_at=start + timedelta(minutes=30))
        self.db.add(s)
        self.db.commit()
        return s

    def product(self, sku="P1", price=10000):
        p = Product(sku=sku, name=sku, category="SUPPLEMENT", price=price, related_services=["METABOLIC"])
        self.db.add(p)
        self.db.commit()
        return p


@pytest.fixture()
def f(db):
    return Factory(db)


def auth(user) -> dict:
    return {"Authorization": f"Bearer {create_token(user)}"}


def tomorrow_at(hour: int, minute: int = 0) -> datetime:
    return (now() + timedelta(days=1)).replace(hour=hour, minute=minute, second=0)
