"""외부 시스템 연동: 자사몰 주문 웹훅.

상담 전환율을 수동 집계하지 않도록 커머스 주문을 수집한다.
external_order_id를 멱등 키로 사용해 웹훅 재전송 시 중복 적재를 막는다.
"""
from datetime import datetime

from fastapi import APIRouter, Depends

from ..db import KST
from ..errors import AppError
from ..models import Order, OrderItem, Product, User
from ..schemas import OrderIn
from ..security import DbSession, verify_integration_key


def _to_kst_naive(dt: datetime) -> datetime:
    return dt.astimezone(KST).replace(tzinfo=None) if dt.tzinfo else dt


router = APIRouter(prefix="/api/integrations", tags=["integrations"], dependencies=[Depends(verify_integration_key)])


@router.post("/orders")
def ingest_order(body: OrderIn, db: DbSession):
    existing = db.query(Order).filter_by(external_order_id=body.external_order_id).one_or_none()
    if existing:
        return {"id": existing.id, "duplicate": True}
    user = db.query(User).filter_by(email=body.customer_email.lower()).one_or_none()
    if user is None:
        # 비회원 주문 등은 상담 귀속 불가 → 수집하지 않음(202로 응답해 재전송 방지)
        return {"id": None, "skipped": "UNKNOWN_CUSTOMER"}
    skus = {i.sku for i in body.items}
    products = {p.sku: p for p in db.query(Product).filter(Product.sku.in_(skus))}
    if missing := skus - products.keys():
        raise AppError(400, "UNKNOWN_SKU", f"알 수 없는 SKU: {', '.join(sorted(missing))}")
    order = Order(
        external_order_id=body.external_order_id,
        customer_id=user.id,
        ordered_at=_to_kst_naive(body.ordered_at),
        total_amount=sum(i.unit_price * i.quantity for i in body.items),
        items=[
            OrderItem(product_id=products[i.sku].id, quantity=i.quantity, unit_price=i.unit_price) for i in body.items
        ],
    )
    db.add(order)
    db.commit()
    return {"id": order.id, "duplicate": False}
