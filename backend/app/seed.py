"""데모 데이터 생성: `python -m app.seed`

실행 시점(오늘)을 기준으로 과거 4주 상담 이력(완료/부재/취소 + 상담기록 + 주문)과
향후 3주 일정(예약/빈 슬롯/마감일)을 만든다. 대시보드·대기 신청·상담 기록 시나리오를 바로 시연할 수 있다.
"""
import random
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from .db import Base, SessionLocal, engine, now
from .models import (
    Booking,
    BookingStatus,
    ConsultationRecord,
    Counselor,
    Indicator,
    IndicatorStatus,
    InterestLevel,
    Notification,
    NotificationStatus,
    Order,
    OrderItem,
    Product,
    ProductRecommendation,
    RecordStatus,
    Relation,
    Role,
    ServiceType,
    Slot,
    Subject,
    TestResult,
    User,
)
from .security import hash_password
from .services import notification
from .services.booking import issue_attendance_token

PASSWORD = "demo1234"
rnd = random.Random(20261014)

# (카테고리, 지표명, 단위, 하한, 상한, 설명)
INDICATORS: dict[ServiceType, list[tuple]] = {
    ServiceType.METABOLIC: [
        ("당대사", "포도당 (Glucose)", "mg/dL", 70, 99, "공복 혈당 상태를 반영합니다. 높으면 인슐린 저항성 가능성을 확인합니다."),
        ("당대사", "젖산 (Lactate)", "mmol/L", 0.5, 2.2, "무산소 대사 정도를 나타냅니다. 피로·미토콘드리아 기능과 관련됩니다."),
        ("아미노산", "BCAA (류신·이소류신·발린)", "µmol/L", 350, 650, "높으면 인슐린 저항성, 낮으면 단백질 섭취 부족과 관련될 수 있습니다."),
        ("아미노산", "호모시스테인", "µmol/L", 5, 12, "비타민 B군 대사와 심혈관 위험도의 지표입니다."),
        ("지질대사", "중성지방", "mg/dL", 50, 150, "탄수화물·알코올 섭취와 밀접합니다."),
        ("지질대사", "유리지방산", "mmol/L", 0.1, 0.6, "지방 분해·연소 상태를 반영합니다."),
        ("에너지대사", "시트르산", "µmol/L", 80, 160, "TCA 회로(에너지 생성)의 핵심 중간대사체입니다."),
        ("에너지대사", "β-하이드록시부티르산", "mmol/L", 0.02, 0.27, "케톤체. 공복·저탄수 식단 시 상승합니다."),
        ("장내미생물 대사체", "TMAO", "µmol/L", 0.5, 6.0, "적색육·계란 섭취 후 장내 미생물이 만드는 대사체로 심혈관 위험과 연관됩니다."),
        ("장내미생물 대사체", "인돌-3-프로피온산", "µmol/L", 0.8, 3.5, "식이섬유 섭취와 장 건강을 반영하는 유익 대사체입니다."),
        ("항산화", "요산", "mg/dL", 3.5, 7.0, "퓨린 대사 산물. 높으면 통풍·대사증후군 위험을 확인합니다."),
        ("스트레스", "코르티솔 대사체", "nmol/L", 140, 690, "스트레스 호르몬 대사 상태입니다."),
    ],
    ServiceType.FOOD_SENSITIVITY: [
        (cat, f"{food} IgG4", "U/mL", None, 10, f"{food}에 대한 지연형 과민 반응 정도입니다. 높을수록 섭취 조절을 권장합니다.")
        for cat, food in [
            ("유제품", "우유"), ("유제품", "카제인"), ("난류", "계란 흰자"), ("곡류", "밀(글루텐)"),
            ("곡류", "메밀"), ("두류", "대두"), ("견과류", "땅콩"), ("해산물", "새우"),
            ("육류", "돼지고기"), ("채소", "토마토"), ("기타", "효모"), ("곡류", "쌀"),
        ]
    ],
    ServiceType.NUTRIENT_METAL: [
        ("비타민", "비타민 D (25-OH)", "ng/mL", 30, 100, "뼈 건강·면역에 중요합니다. 실내 생활이 많으면 부족하기 쉽습니다."),
        ("비타민", "비타민 B12", "pg/mL", 200, 900, "신경·적혈구 생성에 필요합니다."),
        ("비타민", "엽산", "ng/mL", 4, 20, "세포 분열과 호모시스테인 대사에 필요합니다."),
        ("미네랄", "마그네슘", "mg/dL", 1.8, 2.6, "근육 이완·수면·에너지 대사에 관여합니다."),
        ("미네랄", "아연", "µg/dL", 70, 120, "면역·피부·상처 회복에 필요합니다."),
        ("미네랄", "페리틴(철 저장)", "ng/mL", 30, 300, "철 저장량. 낮으면 피로·탈모와 관련될 수 있습니다."),
        ("미네랄", "셀레늄", "µg/L", 70, 150, "항산화 효소의 구성 성분입니다."),
        ("중금속", "납 (Pb)", "µg/dL", None, 5, "노후 배관·페인트 등으로 노출될 수 있습니다."),
        ("중금속", "수은 (Hg)", "µg/L", None, 5, "대형 어류 섭취와 관련이 큽니다."),
        ("중금속", "카드뮴 (Cd)", "µg/L", None, 1, "흡연·오염 토양 작물로 노출될 수 있습니다."),
        ("중금속", "비소 (As)", "µg/L", None, 10, "해조류·쌀 등에서 노출될 수 있습니다."),
        ("중금속", "알루미늄 (Al)", "µg/L", None, 10, "조리도구·제산제 등에서 노출될 수 있습니다."),
    ],
}

COMMENTS = {
    ServiceType.METABOLIC: "전반적인 에너지 대사는 양호하나, 일부 당·지질 대사 지표의 관리가 필요합니다.",
    ServiceType.FOOD_SENSITIVITY: "일부 식품에서 지연형 과민 반응이 관찰되었습니다. 해당 식품은 4~8주 제한 후 재평가를 권장합니다.",
    ServiceType.NUTRIENT_METAL: "일부 영양소 부족과 중금속 노출 지표가 확인되었습니다. 식습관 점검을 권장합니다.",
}

PRODUCTS = [
    ("SUP-OMEGA3", "알티지 오메가3", "SUPPLEMENT", 39000, ["METABOLIC"]),
    ("SUP-CHROM", "바나바·크롬 혈당케어", "SUPPLEMENT", 32000, ["METABOLIC"]),
    ("SUP-PROBIO", "프로바이오틱스 100억", "SUPPLEMENT", 35000, ["METABOLIC", "FOOD_SENSITIVITY"]),
    ("SUP-BCOMP", "활성형 비타민B 컴플렉스", "SUPPLEMENT", 29000, ["METABOLIC", "NUTRIENT_METAL"]),
    ("SUP-VITD", "비타민D3 2000IU", "SUPPLEMENT", 18000, ["NUTRIENT_METAL"]),
    ("SUP-MAG", "마그네슘 글리시네이트", "SUPPLEMENT", 24000, ["NUTRIENT_METAL", "METABOLIC"]),
    ("SUP-ZINC", "아연·셀레늄", "SUPPLEMENT", 19000, ["NUTRIENT_METAL"]),
    ("SUP-DETOX", "클로렐라 디톡스", "SUPPLEMENT", 42000, ["NUTRIENT_METAL"]),
    ("SUP-DIGEST", "소화효소 복합제", "SUPPLEMENT", 27000, ["FOOD_SENSITIVITY"]),
    ("FOOD-LOWGI", "저당 식단 도시락 2주", "FOOD", 129000, ["METABOLIC"]),
    ("FOOD-GF", "글루텐·유제품 프리 식단 2주", "FOOD", 139000, ["FOOD_SENSITIVITY"]),
    ("KIT-RETEST", "종합 대사 분석 재검사 키트", "TEST_KIT", 189000, ["METABOLIC"]),
    ("KIT-FOOD", "음식물 과민증 분석 키트", "TEST_KIT", 159000, ["FOOD_SENSITIVITY", "METABOLIC"]),
    ("KIT-NM", "영양·중금속 분석 키트", "TEST_KIT", 149000, ["NUTRIENT_METAL", "METABOLIC"]),
]

TAGS_BY_SERVICE = {
    ServiceType.METABOLIC: ["혈당·당대사", "지질·콜레스테롤", "체중관리", "피로·에너지", "장건강·소화", "수면·스트레스"],
    ServiceType.FOOD_SENSITIVITY: ["음식 과민·알레르기", "장건강·소화", "피부", "피로·에너지"],
    ServiceType.NUTRIENT_METAL: ["영양 결핍", "중금속 노출", "피로·에너지", "면역", "수면·스트레스"],
}

LAST = list("김이박최정강조윤장임한오서신권황안송류홍")
# 실존 인물과 겹치지 않도록 순우리말 이름으로 구성한 가상 인물
FIRST = ["가온", "나래", "다솜", "라온", "마루", "바다", "아라", "하늬", "한결", "누리", "보람", "새봄",
         "슬기", "여름", "초롱", "하람", "미르", "윤슬", "온새", "해솔", "가람", "별하", "솔찬", "아름"]


_used_phones: set[str] = set()


def _phone() -> str:
    """겹치지 않는 가상 번호(휴대폰 1개 = 계정 1개 규칙)"""
    while True:
        p = f"010-{rnd.randint(2000, 9999)}-{rnd.randint(1000, 9999)}"
        if p not in _used_phones:
            _used_phones.add(p)
            return p


def _make_result(db: Session, kit_code: str, service: ServiceType, subject: Subject | None, reported: datetime,
                 abnormal_bias: float = 0.3) -> TestResult:
    # 검체 접수 때 등록된 검사자 정보(피검자가 있으면 그 사람으로 등록)
    r = TestResult(kit_code=kit_code, subject=subject, service_type=service, reported_at=reported,
                   overall_comment=COMMENTS[service], registered_name=subject.name if subject else None,
                   registered_birth_date=subject.birth_date if subject else None,
                   registered_phone=subject.phone if subject else None)
    for cat, name, unit, lo, hi, desc in INDICATORS[service]:
        roll = rnd.random()
        if lo is None:  # 상한만 있는 지표(과민 반응·중금속)
            value = round(rnd.uniform(hi * 1.1, hi * 3), 2) if roll < abnormal_bias else round(rnd.uniform(0, hi * 0.9), 2)
            status = IndicatorStatus.HIGH if value > hi * 2 else IndicatorStatus.CAUTION if value > hi else IndicatorStatus.NORMAL
        else:
            span = hi - lo
            if roll < abnormal_bias / 2:
                value = round(rnd.uniform(lo - span * 0.4, lo - span * 0.02), 2)
                status = IndicatorStatus.LOW
            elif roll < abnormal_bias:
                value = round(rnd.uniform(hi + span * 0.02, hi + span * 0.5), 2)
                status = IndicatorStatus.HIGH
            else:
                value = round(rnd.uniform(lo + span * 0.05, hi - span * 0.05), 2)
                status = IndicatorStatus.NORMAL
        r.indicators.append(Indicator(category=cat, name=name, value=max(value, 0), unit=unit, ref_low=lo,
                                      ref_high=hi, status=status, description=desc))
    db.add(r)
    return r


def _user(db: Session, email: str, name: str, role: Role, phone: str | None = None) -> User:
    if phone:
        _used_phones.add(phone)
    u = User(email=email, name=name, role=role, phone=phone or _phone(), password_hash=hash_password(PASSWORD),
             phone_verified_at=now())
    db.add(u)
    return u


def seed(db: Session) -> None:
    t = now()
    today = t.date()

    _user(db, "admin@allostar.kr", "운영관리자", Role.ADMIN, "010-1000-0001")
    counselor_defs = [
        # 상담사도 실존 인물과 겹치지 않는 가상 인물(고전 소설 인물)
        ("counselor1@allostar.kr", "이몽룡", ["METABOLIC", "NUTRIENT_METAL"], "임상영양사 · 대사질환 상담 8년"),
        ("counselor2@allostar.kr", "심청", ["FOOD_SENSITIVITY", "METABOLIC"], "약사 · 장건강/식이 상담 전문"),
        ("counselor3@allostar.kr", "콩쥐", ["NUTRIENT_METAL", "FOOD_SENSITIVITY"], "영양사 · 영양·중금속 관리 상담"),
    ]
    counselors = []
    for email, name, spec, bio in counselor_defs:
        u = _user(db, email, name, Role.COUNSELOR)
        c = Counselor(user=u, specialties=spec, bio=bio)
        db.add(c)
        counselors.append(c)

    products = []
    for sku, name, cat, price, rel in PRODUCTS:
        p = Product(sku=sku, name=name, category=cat, price=price, related_services=rel)
        db.add(p)
        products.append(p)
    db.flush()

    # ---- 데모 고객(가상 인물 홍길동): 본인 결과 2종 + 어머니(휴대폰 인증 완료) + 아버지(인증 전, 키트 미연결)
    demo = _user(db, "customer@allostar.kr", "홍길동", Role.CUSTOMER, "010-1234-5678")
    db.flush()
    me = Subject(owner_id=demo.id, name="홍길동", birth_date=date(1990, 3, 1), relation=Relation.SELF,
                 phone=demo.phone, consent_at=t)
    mom = Subject(owner_id=demo.id, name="성춘향", birth_date=date(1962, 9, 3), relation=Relation.PARENT,
                  phone="010-2345-6789", consent_at=t)
    dad = Subject(owner_id=demo.id, name="홍판서", birth_date=date(1960, 1, 22), relation=Relation.PARENT,
                  phone="010-3456-7890")
    db.add_all([me, mom, dad])
    demo_meta = _make_result(db, "AL-MB-2026-0001", ServiceType.METABOLIC, me, t - timedelta(days=40), 0.4)
    demo_food = _make_result(db, "AL-FS-2026-0002", ServiceType.FOOD_SENSITIVITY, me, t - timedelta(days=6), 0.35)
    _make_result(db, "AL-NM-2026-0003", ServiceType.NUTRIENT_METAL, mom, t - timedelta(days=4), 0.45)
    # 아버지 키트: 검체 접수 때 아버지 정보로 등록됐지만 계정에는 아직 연결 전 → 인증 후 '키트 연결' 시연용
    dad_kit = _make_result(db, "AL-DEMO-00", ServiceType.METABOLIC, None, t - timedelta(days=2), 0.45)
    dad_kit.registered_name, dad_kit.registered_birth_date, dad_kit.registered_phone = dad.name, dad.birth_date, dad.phone

    # ---- 회원가입 후 바로 연결해 볼 수 있는 데모 키트(미연결). /api/demo/kits 로 안내된다.
    for i, service in enumerate([ServiceType.METABOLIC, ServiceType.FOOD_SENSITIVITY, ServiceType.NUTRIENT_METAL] * 4, 1):
        _make_result(db, f"AL-DEMO-{i:02d}", service, None, t - timedelta(days=rnd.randint(1, 7)), 0.4)

    # ---- 일반 고객 60명
    customers: list[tuple[User, Subject, list[TestResult]]] = []
    kit_no = 100
    for i in range(60):
        name = rnd.choice(LAST) + rnd.choice(FIRST)
        u = _user(db, f"user{i + 1:02d}@example.com", name, Role.CUSTOMER)
        db.flush()
        s = Subject(owner_id=u.id, name=name, relation=Relation.SELF, consent_at=t, phone=u.phone,
                    birth_date=date(rnd.randint(1955, 2000), rnd.randint(1, 12), rnd.randint(1, 28)))
        db.add(s)
        results = []
        for service in rnd.sample(list(ServiceType), k=rnd.choice([1, 1, 2])):
            kit_no += 1
            prefix = {"METABOLIC": "MB", "FOOD_SENSITIVITY": "FS", "NUTRIENT_METAL": "NM"}[service.value]
            results.append(_make_result(db, f"AL-{prefix}-2026-{kit_no:04d}", service, s, t - timedelta(days=rnd.randint(30, 60))))
        customers.append((u, s, results))
    db.flush()

    # ---- 슬롯: 지난 4주 ~ 향후 3주, 평일 10:00~18:00(점심 12~13시 제외), 30분 단위
    slots_by_day: dict[date, list[Slot]] = {}
    d = today - timedelta(days=28)
    while d <= today + timedelta(days=21):
        if d.weekday() < 5:
            for c in counselors:
                cur = datetime.combine(d, time(10))
                while cur < datetime.combine(d, time(18)):
                    if not (12 <= cur.hour < 13):
                        s = Slot(counselor=c, start_at=cur, end_at=cur + timedelta(minutes=30))
                        db.add(s)
                        slots_by_day.setdefault(d, []).append(s)
                    cur += timedelta(minutes=30)
        d += timedelta(days=1)
    db.flush()

    used_slots: set[int] = set()

    def book(customer: User, subject: Subject, result: TestResult, slot: Slot, status: BookingStatus, **kw) -> Booking:
        b = Booking(slot=slot, counselor_id=slot.counselor_id, customer_id=customer.id, subject_id=subject.id,
                    result_id=result.id, contact_phone=kw.pop("contact_phone", customer.phone), status=status,
                    created_at=min(slot.start_at - timedelta(days=rnd.randint(1, 10)), t), **kw)
        db.add(b)
        used_slots.add(id(slot))
        return b

    def pick_for(slot: Slot):
        counselor = next(c for c in counselors if c.id == slot.counselor_id)
        cands = [(u, s, r) for u, s, rs in customers for r in rs if r.service_type.value in counselor.specialties]
        return rnd.choice(cands)

    # ---- 과거 상담 이력
    completed: list[Booking] = []
    for day, day_slots in sorted(slots_by_day.items()):
        if day > today:
            continue
        for slot in day_slots:
            if slot.start_at >= t - timedelta(minutes=30) or rnd.random() > 0.38:
                continue
            u, s, r = pick_for(slot)
            roll = rnd.random()
            status = BookingStatus.COMPLETED if roll < 0.76 else BookingStatus.NO_SHOW if roll < 0.86 else BookingStatus.CANCELLED
            confirmed = rnd.random() < (0.85 if status == BookingStatus.COMPLETED else 0.2)
            b = book(u, s, r, slot, status,
                     concern_tags=rnd.sample(TAGS_BY_SERVICE[r.service_type], k=rnd.randint(1, 2)),
                     attendance_confirmed_at=slot.start_at - timedelta(hours=rnd.randint(2, 20)) if confirmed else None,
                     call_attempts=rnd.randint(2, 3) if status == BookingStatus.NO_SHOW else 1)
            if status == BookingStatus.CANCELLED:
                b.cancelled_at = slot.start_at - timedelta(hours=rnd.randint(4, 48))
                b.cancel_reason = rnd.choice(["개인 일정", "일정 변경", None])
            if status == BookingStatus.COMPLETED:
                b.completed_at = slot.end_at
                completed.append(b)
    db.flush()

    # 상담 기록 + 추천 + 구매
    order_no = 0
    for b in completed:
        r = db.get(TestResult, b.result_id)
        abnormal = [i for i in r.indicators if i.status != IndicatorStatus.NORMAL]
        rec = ConsultationRecord(
            booking_id=b.id, counselor_id=b.counselor_id, status=RecordStatus.SUBMITTED,
            concern_tags=b.concern_tags, discussed_indicator_ids=[i.id for i in abnormal[:4]],
            summary=f"{', '.join(i.name for i in abnormal[:3]) or '전반 지표'} 중심 상담. 식습관 및 생활습관 확인.",
            customer_message="결과지에서 관리가 필요한 지표와 식습관 개선 방향을 안내드렸습니다.",
            lifestyle_advice="정제 탄수화물 줄이기, 주 3회 30분 유산소 운동, 수분 섭취 늘리기",
            follow_up_needed=rnd.random() < 0.3, submitted_at=b.completed_at + timedelta(minutes=rnd.randint(5, 90)),
            created_at=b.completed_at, updated_at=b.completed_at,
        )
        related = [p for p in products if r.service_type.value in p.related_services]
        for p in rnd.sample(related, k=min(len(related), rnd.choice([0, 1, 2, 2, 3]))):
            level = rnd.choices(list(InterestLevel), weights=[35, 35, 20, 10])[0]
            rec.recommendations.append(ProductRecommendation(product_id=p.id, interest_level=level))
            buy_p = {InterestLevel.HIGH: 0.6, InterestLevel.MEDIUM: 0.3, InterestLevel.LOW: 0.08, InterestLevel.NONE: 0.02}[level]
            ordered_at = b.completed_at + timedelta(days=rnd.randint(0, 14), hours=rnd.randint(1, 10))
            if rnd.random() < buy_p and ordered_at < t:
                order_no += 1
                db.add(Order(external_order_id=f"MALL-{order_no:05d}", customer_id=b.customer_id, ordered_at=ordered_at,
                             total_amount=p.price, items=[OrderItem(product_id=p.id, quantity=1, unit_price=p.price)]))
        db.add(rec)
    # 상담과 무관한 일반 구매(비교군)
    for u, _, _ in rnd.sample(customers, 12):
        p = rnd.choice(products)
        order_no += 1
        db.add(Order(external_order_id=f"MALL-{order_no:05d}", customer_id=u.id,
                     ordered_at=t - timedelta(days=rnd.randint(1, 27)), total_amount=p.price,
                     items=[OrderItem(product_id=p.id, quantity=1, unit_price=p.price)]))

    # ---- 데모 고객 이력: 종합 대사 결과 상담 완료(기록 있음) + 음식물 과민증 상담 예정
    c1, c2, c3 = counselors
    past_day = max(d for d in slots_by_day if d < today - timedelta(days=6))
    past_slot = next(s for s in slots_by_day[past_day] if s.counselor_id == c1.id and id(s) not in used_slots)
    demo_done = book(demo, me, demo_meta, past_slot, BookingStatus.COMPLETED, concern_tags=["혈당·당대사", "체중관리"],
                     pre_questions="공복혈당이 높게 나왔는데 어떤 음식을 줄여야 할까요?",
                     attendance_confirmed_at=past_slot.start_at - timedelta(hours=5), call_attempts=1)
    demo_done.completed_at = past_slot.end_at
    db.flush()
    abnormal = [i for i in demo_meta.indicators if i.status != IndicatorStatus.NORMAL]
    demo_rec = ConsultationRecord(
        booking_id=demo_done.id, counselor_id=c1.id, status=RecordStatus.SUBMITTED,
        concern_tags=["혈당·당대사", "체중관리"], discussed_indicator_ids=[i.id for i in abnormal[:3]],
        summary="공복혈당·BCAA 상승. 야식/단 음료 섭취 잦음. 체중 감량 의지 높음. 혈당케어 제품 관심 큼.",
        customer_message="혈당과 관련된 지표가 기준보다 높게 나타났습니다. 저녁 8시 이후 간식과 단 음료를 줄이시고, "
                         "식사 순서를 채소 → 단백질 → 탄수화물 순으로 바꿔보세요. 3개월 후 재검사로 변화를 확인하시길 권합니다.",
        lifestyle_advice="식후 10분 걷기, 주 3회 근력운동, 단 음료 대신 탄산수",
        follow_up_needed=True, follow_up_date=today + timedelta(days=80),
        submitted_at=past_slot.end_at + timedelta(minutes=20), created_at=past_slot.end_at, updated_at=past_slot.end_at,
    )
    by_sku = {p.sku: p for p in products}
    demo_rec.recommendations += [
        ProductRecommendation(product_id=by_sku["SUP-CHROM"].id, interest_level=InterestLevel.HIGH, note="식전 1정"),
        ProductRecommendation(product_id=by_sku["FOOD-LOWGI"].id, interest_level=InterestLevel.MEDIUM),
        ProductRecommendation(product_id=by_sku["KIT-RETEST"].id, interest_level=InterestLevel.LOW, note="3개월 후"),
    ]
    db.add(demo_rec)
    db.add(Order(external_order_id="MALL-DEMO-1", customer_id=demo.id, ordered_at=past_slot.end_at + timedelta(days=2),
                 total_amount=by_sku["SUP-CHROM"].price,
                 items=[OrderItem(product_id=by_sku["SUP-CHROM"].id, quantity=1, unit_price=by_sku["SUP-CHROM"].price)]))

    # ---- 향후 일정
    future_days = sorted(d for d in slots_by_day if d >= today)
    weekdays_ahead = [d for d in future_days if d > today]
    full_day = weekdays_ahead[1]  # 이틀 뒤 평일: 전 상담사 마감(대기 신청 시연용)
    demo_future_day = weekdays_ahead[2]
    future_bookings: list[Booking] = []

    demo_slot = next(s for s in slots_by_day[demo_future_day] if s.counselor_id == c2.id and s.start_at.hour == 14)
    demo_upcoming = book(demo, me, demo_food, demo_slot, BookingStatus.CONFIRMED, concern_tags=["음식 과민·알레르기", "장건강·소화"],
                         pre_questions="우유랑 밀이 높게 나왔는데 완전히 끊어야 하나요?")
    future_bookings.append(demo_upcoming)

    for day in future_days:
        for slot in slots_by_day[day]:
            if id(slot) in used_slots or slot.start_at <= t:
                continue
            p_book = 1.0 if day == full_day else 0.55 if day == today else max(0.15, 0.5 - 0.03 * (day - today).days)
            if rnd.random() > p_book:
                continue
            # 결과지당 진행 예정 예약 1건 + 고객 동일 시간 중복 금지 정책을 지키는 고객을 고른다
            for _ in range(20):
                u, s, r = pick_for(slot)
                if not any(b.result_id == r.id or (b.customer_id == u.id and b.slot.start_at == slot.start_at)
                           for b in future_bookings):
                    break
            else:
                continue
            confirmed = slot.start_at - t < timedelta(days=1) and rnd.random() < 0.6
            future_bookings.append(book(u, s, r, slot, BookingStatus.CONFIRMED,
                                        concern_tags=rnd.sample(TAGS_BY_SERVICE[r.service_type], k=1),
                                        pre_questions=rnd.choice(["", "", "수치가 높게 나온 항목이 걱정됩니다.", "영양제 추천 받고 싶어요."]),
                                        attendance_confirmed_at=t - timedelta(hours=1) if confirmed else None))

    # 오늘 이미 시작한 상담 1건: 상담사(이몽룡)가 기록을 작성하는 시연용
    today_past = [s for s in slots_by_day.get(today, []) if s.counselor_id == c1.id and s.start_at < t - timedelta(minutes=30)
                  and id(s) not in used_slots]
    if today_past:
        u, s, r = next((u, s, r) for u, s, rs in customers for r in rs if r.service_type == ServiceType.METABOLIC)
        book(u, s, r, today_past[-1], BookingStatus.CONFIRMED, concern_tags=["피로·에너지"],
             pre_questions="요즘 오후만 되면 너무 피곤합니다.", attendance_confirmed_at=today_past[-1].start_at - timedelta(hours=3),
             call_attempts=1)
    db.flush()

    for b in future_bookings:
        token = issue_attendance_token(b)
        db.flush()
        db.refresh(b)
        notification.schedule_for_new_booking(db, b, token)
    db.flush()
    # 시드 시점 이전 알림은 이미 발송된 것으로 처리(콘솔 SMS 폭주 방지)
    for n in db.query(Notification).filter(Notification.scheduled_at <= now()):
        n.status, n.sent_at = NotificationStatus.SENT, n.scheduled_at
    db.commit()


def main() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
        print(f"seeded: users={db.query(User).count()} slots={db.query(Slot).count()} "
              f"bookings={db.query(Booking).count()} orders={db.query(Order).count()}")
    print(f"demo accounts (password: {PASSWORD}): customer@allostar.kr / counselor1@allostar.kr / admin@allostar.kr")


if __name__ == "__main__":
    main()
