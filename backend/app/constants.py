from .models import ServiceType

SERVICE_LABELS = {
    ServiceType.METABOLIC: "종합 대사 분석",
    ServiceType.FOOD_SENSITIVITY: "음식물 과민증 분석",
    ServiceType.NUTRIENT_METAL: "영양·중금속 건강 위험도 분석",
}

# 상담 관심사 표준 태그. 예약 시 고객이, 상담 후 상담사가 선택한다.
# 자유 텍스트 대신 코드화해야 "어떤 관심사가 전환으로 이어지는가"를 집계할 수 있다.
CONCERN_TAGS = [
    "혈당·당대사",
    "지질·콜레스테롤",
    "체중관리",
    "장건강·소화",
    "피로·에너지",
    "수면·스트레스",
    "음식 과민·알레르기",
    "영양 결핍",
    "중금속 노출",
    "피부",
    "면역",
    "기타",
]

RELATION_LABELS = {
    "SELF": "본인",
    "SPOUSE": "배우자",
    "PARENT": "부모",
    "CHILD": "자녀",
    "SIBLING": "형제자매",
    "OTHER": "기타",
}
