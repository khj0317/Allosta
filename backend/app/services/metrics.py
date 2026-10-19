"""운영 지표 집계.

전환 정의(설계 문서 3.6 참고)
- 상담 전환: 상담 완료 후 attribution_days(기본 30일) 이내에, 해당 상담에서 '추천된 제품'을 구매한 경우.
- 한 주문 품목이 여러 상담에 해당하면 구매 직전의 가장 최근 상담 1건에만 귀속(last-touch).
- 보조 지표로 '추천 여부와 무관한 구매 전환'도 함께 제공한다.

MVP는 조회 시점에 계산(on-the-fly). 데이터가 커지면 일 단위 집계 테이블(daily_counselor_metrics)로 전환한다.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..config import settings
from ..db import now
from ..models import (
    Booking,
    BookingStatus,
    ConsultationRecord,
    Counselor,
    InterestLevel,
    Order,
    Product,
    RecordStatus,
    Slot,
    WaitlistEntry,
    WaitlistStatus,
)


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def dashboard(db: Session, date_from: date, date_to: date) -> dict:
    t = now()
    start = datetime.combine(date_from, time.min)
    end = datetime.combine(date_to + timedelta(days=1), time.min)
    window = timedelta(days=settings.attribution_days)

    bookings = db.scalars(
        select(Booking)
        .join(Slot, Slot.id == Booking.slot_id)
        .where(Slot.start_at >= start, Slot.start_at < end)
        .options(
            joinedload(Booking.slot),
            joinedload(Booking.record).selectinload(ConsultationRecord.recommendations),
        )
    ).unique().all()

    customer_ids = {b.customer_id for b in bookings}
    orders = (
        db.scalars(
            select(Order)
            .where(Order.customer_id.in_(customer_ids), Order.ordered_at >= start, Order.ordered_at < end + window)
            .options(selectinload(Order.items))
        ).all()
        if customer_ids
        else []
    )

    # 고객별 완료 상담(시간순)
    completed = [b for b in bookings if b.status == BookingStatus.COMPLETED and b.completed_at]
    by_customer: dict[int, list[Booking]] = defaultdict(list)
    for b in sorted(completed, key=lambda b: b.completed_at):
        by_customer[b.customer_id].append(b)

    converted_rec: set[int] = set()  # 추천 제품 구매로 전환된 상담
    converted_any: set[int] = set()  # 아무 제품이나 구매한 상담
    attributed_revenue: dict[int, int] = defaultdict(int)
    purchased_products: Counter[int] = Counter()

    for order in orders:
        prior = [b for b in by_customer.get(order.customer_id, []) if b.completed_at <= order.ordered_at <= b.completed_at + window]
        if not prior:
            continue
        converted_any.update(b.id for b in prior)
        for item in order.items:
            # 이 품목을 추천했던 가장 최근 상담에 귀속
            for b in reversed(prior):
                rec_ids = {r.product_id for r in (b.record.recommendations if b.record else [])}
                if item.product_id in rec_ids:
                    converted_rec.add(b.id)
                    attributed_revenue[b.id] += item.unit_price * item.quantity
                    purchased_products[item.product_id] += item.quantity
                    break

    def summarize(items: list[Booking]) -> dict:
        total = len(items)
        cancelled = sum(b.status == BookingStatus.CANCELLED for b in items)
        done = [b for b in items if b.status == BookingStatus.COMPLETED]
        no_show = sum(b.status == BookingStatus.NO_SHOW for b in items)
        held = len(done) + no_show
        with_rec = [b for b in done if b.record and b.record.recommendations]
        non_cancelled = [b for b in items if b.status != BookingStatus.CANCELLED]
        return {
            "total_bookings": total,
            "cancelled": cancelled,
            "completed": len(done),
            "no_show": no_show,
            # 확정 상태라도 시간이 지났으면 '예정'이 아니라 처리 누락(기록·부재 미처리)
            "upcoming": sum(b.status == BookingStatus.CONFIRMED and b.slot.end_at > t for b in items),
            "overdue": sum(b.status == BookingStatus.CONFIRMED and b.slot.end_at <= t for b in items),
            "cancel_rate": _rate(cancelled, total),
            "no_show_rate": _rate(no_show, held),
            "attendance_confirm_rate": _rate(
                sum(b.attendance_confirmed_at is not None for b in non_cancelled), len(non_cancelled)
            ),
            "record_submit_rate": _rate(
                sum(bool(b.record and b.record.status == RecordStatus.SUBMITTED) for b in done), len(done)
            ),
            "recommendation_rate": _rate(len(with_rec), len(done)),
            "conversion_rate": _rate(sum(b.id in converted_rec for b in done), len(done)),
            "any_purchase_rate": _rate(sum(b.id in converted_any for b in done), len(done)),
            "attributed_revenue": sum(attributed_revenue[b.id] for b in done),
        }

    counselors = {
        c.id: c for c in db.scalars(select(Counselor).options(joinedload(Counselor.user))).all()
    }
    per_counselor = []
    grouped: dict[int, list[Booking]] = defaultdict(list)
    for b in bookings:
        grouped[b.counselor_id].append(b)
    for cid, c in counselors.items():
        per_counselor.append({"counselor_id": cid, "name": c.user.name, **summarize(grouped.get(cid, []))})

    # 추천 제품 성과
    rec_counter: Counter[int] = Counter()
    high_interest: Counter[int] = Counter()
    tag_counter: Counter[str] = Counter()
    tag_converted: Counter[str] = Counter()
    for b in completed:
        if not b.record:
            continue
        for r in b.record.recommendations:
            rec_counter[r.product_id] += 1
            if r.interest_level == InterestLevel.HIGH:
                high_interest[r.product_id] += 1
        for tag in b.record.concern_tags:
            tag_counter[tag] += 1
            if b.id in converted_rec:
                tag_converted[tag] += 1

    products = {p.id: p for p in db.scalars(select(Product)).all()}
    top_products = [
        {
            "product_id": pid,
            "name": products[pid].name,
            "recommended": cnt,
            "high_interest": high_interest[pid],
            "purchased_qty": purchased_products[pid],
        }
        for pid, cnt in rec_counter.most_common(8)
    ]
    top_concerns = [
        {"tag": tag, "count": cnt, "conversion_rate": _rate(tag_converted[tag], cnt)}
        for tag, cnt in tag_counter.most_common(8)
    ]

    daily: dict[str, dict[str, int]] = {}
    d = date_from
    while d <= date_to:
        daily[d.isoformat()] = {"booked": 0, "completed": 0, "no_show": 0, "cancelled": 0}
        d += timedelta(days=1)
    for b in bookings:
        key = b.slot.start_at.date().isoformat()
        daily[key]["booked"] += 1
        if b.status == BookingStatus.COMPLETED:
            daily[key]["completed"] += 1
        elif b.status == BookingStatus.NO_SHOW:
            daily[key]["no_show"] += 1
        elif b.status == BookingStatus.CANCELLED:
            daily[key]["cancelled"] += 1

    wl = db.scalars(
        select(WaitlistEntry).where(WaitlistEntry.desired_date >= date_from, WaitlistEntry.desired_date <= date_to)
    ).all()
    waitlist = {
        "total": len(wl),
        "booked": sum(w.status == WaitlistStatus.BOOKED for w in wl),
        "waiting": sum(w.status in (WaitlistStatus.WAITING, WaitlistStatus.OFFERED) for w in wl),
        "expired": sum(w.status == WaitlistStatus.EXPIRED for w in wl),
    }
    waitlist["recovery_rate"] = _rate(waitlist["booked"], waitlist["total"])

    # 슬롯 가동률: 기간 내 오픈 슬롯 중 예약(취소 제외)된 비율
    slot_total = db.query(Slot).filter(Slot.start_at >= start, Slot.start_at < end, Slot.status == "OPEN").count()
    used = sum(b.status != BookingStatus.CANCELLED for b in bookings)

    # 단계별 이탈 흐름: 시간이 이미 지난 예약만(앞으로 있을 예약을 넣으면 완료가 적게 보임).
    # 단계는 서로 포함 관계 → 각 단계에서 얼마나 빠지는지가 곧 '어디서 새는지'다.
    ended = [b for b in bookings if b.slot.end_at <= t]
    kept = [b for b in ended if b.status != BookingStatus.CANCELLED]
    done_ = [b for b in kept if b.status == BookingStatus.COMPLETED]
    recommended = [b for b in done_ if b.record and b.record.recommendations]
    bought = [b for b in recommended if b.id in converted_rec]
    funnel = [
        {"key": "booked", "label": "예약", "count": len(ended), "drop": None},
        {"key": "kept", "label": "취소 없이 상담일 도래", "count": len(kept),
         "drop": {"label": "취소", "count": len(ended) - len(kept)}},
        {"key": "completed", "label": "상담 완료", "count": len(done_),
         "drop": {"label": "부재 · 처리 누락",
                  "count": len(kept) - len(done_)}},
        {"key": "recommended", "label": "제품 추천", "count": len(recommended),
         "drop": {"label": "추천 없음", "count": len(done_) - len(recommended)}},
        {"key": "purchased", "label": "추천 제품 구매", "count": len(bought),
         "drop": {"label": f"{settings.attribution_days}일 내 미구매", "count": len(recommended) - len(bought)}},
    ]
    # 리마인더 효과: 참석 확인 여부에 따른 부재율
    held_ = [b for b in kept if b.status in (BookingStatus.COMPLETED, BookingStatus.NO_SHOW)]
    confirmed = [b for b in held_ if b.attendance_confirmed_at]
    unconfirmed = [b for b in held_ if not b.attendance_confirmed_at]
    attendance_effect = {
        "confirmed_no_show_rate": _rate(sum(b.status == BookingStatus.NO_SHOW for b in confirmed), len(confirmed)),
        "unconfirmed_no_show_rate": _rate(sum(b.status == BookingStatus.NO_SHOW for b in unconfirmed), len(unconfirmed)),
        "confirmed": len(confirmed),
        "unconfirmed": len(unconfirmed),
    }

    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "attribution_days": settings.attribution_days,
        "summary": {**summarize(bookings), "slot_utilization": _rate(used, slot_total)},
        "per_counselor": per_counselor,
        "top_products": top_products,
        "top_concerns": top_concerns,
        "daily": [{"date": k, **v} for k, v in daily.items()],
        "waitlist": waitlist,
        "funnel": funnel,
        "attendance_effect": attendance_effect,
    }
