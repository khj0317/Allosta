// ---------------------------------------------------------------- types (백엔드 schemas.py와 1:1)

export type Role = 'CUSTOMER' | 'COUNSELOR' | 'ADMIN';
export type ServiceType = 'METABOLIC' | 'FOOD_SENSITIVITY' | 'NUTRIENT_METAL';
export type Relation = 'SELF' | 'SPOUSE' | 'PARENT' | 'CHILD' | 'SIBLING' | 'OTHER';
export type BookingStatus = 'CONFIRMED' | 'CANCELLED' | 'COMPLETED' | 'NO_SHOW';
export type WaitlistStatus = 'WAITING' | 'OFFERED' | 'BOOKED' | 'EXPIRED' | 'CANCELLED';
export type InterestLevel = 'HIGH' | 'MEDIUM' | 'LOW' | 'NONE';
export type IndicatorStatus = 'LOW' | 'NORMAL' | 'HIGH' | 'CAUTION';

export interface User {
  id: number;
  email: string;
  name: string;
  phone: string;
  role: Role;
  counselor_id: number | null;
}

export interface ResultSummary {
  id: number;
  kit_code: string;
  service_type: ServiceType;
  service_label: string;
  reported_at: string;
  abnormal_count: number;
}

export interface Indicator {
  id: number;
  category: string;
  name: string;
  value: number;
  unit: string;
  ref_low: number | null;
  ref_high: number | null;
  status: IndicatorStatus;
  description: string;
}

export interface ResultDetail extends ResultSummary {
  overall_comment: string;
  subject_id: number | null;
  subject_name: string | null;
  indicators: Indicator[];
}

export interface Subject {
  id: number;
  name: string;
  birth_date: string | null;
  relation: Relation;
  phone_masked: string | null;
  /** 가족 본인 휴대폰 인증 완료 시각(본인은 가입 시각). 없으면 결과 연결·예약 불가 */
  consent_at: string | null;
  /** 인증번호 발송 후 확인 전이면 만료 시각 */
  verify_expires_at: string | null;
  results: ResultSummary[];
}

export interface Slot {
  id: number;
  counselor_id: number;
  counselor_name: string;
  start_at: string;
  end_at: string;
}

export interface StaffSlot extends Slot {
  status: 'OPEN' | 'BLOCKED';
  booking_id: number | null;
  booking_customer: string | null;
  hold_until: string | null;
}

export interface Booking {
  id: number;
  status: BookingStatus;
  start_at: string;
  end_at: string;
  counselor_id: number;
  counselor_name: string;
  customer_id: number;
  customer_name: string;
  subject_id: number;
  subject_name: string;
  subject_relation: Relation;
  result_id: number;
  service_type: ServiceType;
  service_label: string;
  contact_phone: string;
  pre_questions: string;
  concern_tags: string[];
  attendance_confirmed_at: string | null;
  call_attempts: number;
  cancel_reason: string | null;
  created_at: string;
  record_status: 'DRAFT' | 'SUBMITTED' | null;
  can_change: boolean;
}

export interface WaitlistEntry {
  id: number;
  subject_id: number;
  subject_name: string;
  result_id: number;
  service_type: ServiceType;
  desired_date: string;
  start_hour: number;
  end_hour: number;
  counselor_id: number | null;
  status: WaitlistStatus;
  offered_slot: Slot | null;
  /** 같은 결과지로 이미 잡아 둔 예약. 있으면 제안 수락 = 그 예약의 일정 변경 */
  current_booking: Slot | null;
  offer_expires_at: string | null;
  booking_id: number | null;
  created_at: string;
}

export interface Product {
  id: number;
  sku: string;
  name: string;
  category: string;
  price: number;
  related_services: ServiceType[];
}

export interface Recommendation {
  product_id: number;
  interest_level: InterestLevel;
  note: string;
  product?: Product;
}

export interface ConsultRecord {
  id: number;
  booking_id: number;
  status: 'DRAFT' | 'SUBMITTED';
  concern_tags: string[];
  discussed_indicator_ids: number[];
  summary: string;
  customer_message: string;
  lifestyle_advice: string;
  follow_up_needed: boolean;
  follow_up_date: string | null;
  submitted_at: string | null;
  updated_at: string;
  recommendations: Recommendation[];
}

export interface RecordInput {
  concern_tags: string[];
  discussed_indicator_ids: number[];
  summary: string;
  customer_message: string;
  lifestyle_advice: string;
  follow_up_needed: boolean;
  follow_up_date: string | null;
  recommendations: Recommendation[];
}

export interface CustomerRecord {
  customer_message: string;
  lifestyle_advice: string;
  follow_up_needed: boolean;
  follow_up_date: string | null;
  discussed_indicators: Indicator[];
  recommended_products: Product[];
  submitted_at: string | null;
}

export interface CounselorBookingDetail {
  booking: Booking;
  result: ResultDetail;
  customer_phone: string;
  past_bookings: Booking[];
  record: ConsultRecord | null;
}

export interface Notification {
  id: number;
  type: string;
  title: string;
  body: string;
  booking_id: number | null;
  waitlist_id: number | null;
  sent_at: string | null;
  read_at: string | null;
}

export interface Meta {
  service_types: { value: ServiceType; label: string }[];
  concern_tags: string[];
  relations: { value: Relation; label: string }[];
  demo_mode: boolean;
}

export interface FamilyCode {
  subject: Subject;
  demo_code: string | null;
}

export interface SignupInput {
  email: string;
  password: string;
  name: string;
  phone: string;
  birth_date: string;
  privacy_consent: boolean;
}

export interface CounselorInfo {
  id: number;
  name: string;
  specialties: ServiceType[];
  bio: string;
  active: boolean;
}

export interface Summary {
  total_bookings: number;
  cancelled: number;
  completed: number;
  no_show: number;
  upcoming: number;
  cancel_rate: number | null;
  no_show_rate: number | null;
  attendance_confirm_rate: number | null;
  record_submit_rate: number | null;
  recommendation_rate: number | null;
  conversion_rate: number | null;
  any_purchase_rate: number | null;
  attributed_revenue: number;
  slot_utilization?: number | null;
}

export interface Dashboard {
  period: { from: string; to: string };
  attribution_days: number;
  summary: Summary;
  per_counselor: (Summary & { counselor_id: number; name: string })[];
  top_products: { product_id: number; name: string; recommended: number; high_interest: number; purchased_qty: number }[];
  top_concerns: { tag: string; count: number; conversion_rate: number | null }[];
  daily: { date: string; booked: number; completed: number; no_show: number; cancelled: number }[];
  waitlist: { total: number; booked: number; waiting: number; expired: number; recovery_rate: number | null };
}

// ---------------------------------------------------------------- client

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public extra: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

const TOKEN_KEY = 'allostar.token';

export const tokenStore = {
  get: () => {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set: (t: string | null) => {
    try {
      if (t) localStorage.setItem(TOKEN_KEY, t);
      else localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* 저장소 차단 환경: 세션 내 메모리로만 동작 */
    }
  },
};

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (res.status === 401 && token) {
    tokenStore.set(null);
    window.location.href = '/login';
  }
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data?.detail;
    if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
      const { code, message, ...extra } = detail;
      throw new ApiError(res.status, code, message, extra);
    }
    // FastAPI 입력 검증 오류(422)
    const msg = Array.isArray(detail) ? detail.map((d: { msg: string }) => d.msg).join(', ') : String(detail ?? res.statusText);
    throw new ApiError(res.status, 'ERROR', msg);
  }
  return data as T;
}

const qs = (params: Record<string, string | number | undefined | null>) =>
  '?' +
  Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`)
    .join('&');

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string; user: User }>('POST', '/api/auth/login', { email, password }),
  signup: (body: SignupInput) => request<{ access_token: string; user: User }>('POST', '/api/auth/signup', body),
  me: () => request<User>('GET', '/api/auth/me'),
  demoSession: (role: Role) => request<{ access_token: string; user: User }>('POST', '/api/demo/session', { role }),
  demoKits: (subjectId: number) =>
    request<{ kit_code: string; service_label: string; registered: boolean }[]>('GET', `/api/demo/kits?subject_id=${subjectId}`),
  meta: () => request<Meta>('GET', '/api/meta'),
  products: () => request<Product[]>('GET', '/api/products'),
  counselors: () => request<CounselorInfo[]>('GET', '/api/counselors'),

  subjects: () => request<Subject[]>('GET', '/api/subjects'),
  /** 가족 등록 → 가족 본인 휴대폰으로 인증번호 발송. demo_code는 데모 모드에서만 채워진다 */
  addFamily: (body: { name: string; relation: Relation; birth_date: string; phone: string }) =>
    request<FamilyCode>('POST', '/api/subjects', body),
  resendFamilyCode: (id: number) => request<FamilyCode>('POST', `/api/subjects/${id}/verification`),
  verifyFamily: (id: number, code: string) => request<Subject>('POST', `/api/subjects/${id}/verify`, { code }),
  removeFamily: (id: number) => request<null>('DELETE', `/api/subjects/${id}`),
  claimKit: (id: number, kit_code: string) => request<Subject>('POST', `/api/subjects/${id}/claim-kit`, { kit_code }),
  result: (id: number) => request<ResultDetail>('GET', `/api/results/${id}`),

  calendar: (service_type: ServiceType, date_from: string, days = 28) =>
    request<{ date: string; available: number }[]>('GET', '/api/slots/calendar' + qs({ service_type, date_from, days })),
  availableSlots: (service_type: ServiceType, date_from: string, date_to?: string) =>
    request<Slot[]>('GET', '/api/slots/available' + qs({ service_type, date_from, date_to })),

  createBooking: (body: {
    slot_id: number;
    subject_id: number;
    result_id: number;
    contact_phone: string;
    pre_questions: string;
    concern_tags: string[];
  }) => request<Booking>('POST', '/api/bookings', body),
  myBookings: () => request<Booking[]>('GET', '/api/bookings/me'),
  booking: (id: number) => request<Booking>('GET', `/api/bookings/${id}`),
  cancelBooking: (id: number, reason: string) => request<Booking>('POST', `/api/bookings/${id}/cancel`, { reason }),
  reschedule: (id: number, slot_id: number) => request<Booking>('POST', `/api/bookings/${id}/reschedule`, { slot_id }),
  confirmAttendance: (id: number) => request<Booking>('POST', `/api/bookings/${id}/confirm-attendance`),
  customerRecord: (id: number) => request<CustomerRecord | null>('GET', `/api/bookings/${id}/record`),

  joinWaitlist: (body: {
    subject_id: number;
    result_id: number;
    desired_date: string;
    start_hour: number;
    end_hour: number;
    contact_phone: string;
    pre_questions: string;
  }) => request<WaitlistEntry>('POST', '/api/waitlist', body),
  myWaitlist: () => request<WaitlistEntry[]>('GET', '/api/waitlist/me'),
  acceptOffer: (id: number) => request<Booking>('POST', `/api/waitlist/${id}/accept`),
  declineOffer: (id: number) => request<WaitlistEntry>('POST', `/api/waitlist/${id}/decline`),
  cancelWaitlist: (id: number) => request<WaitlistEntry>('POST', `/api/waitlist/${id}/cancel`),

  notifications: () => request<Notification[]>('GET', '/api/notifications/me'),
  readNotification: (id: number) => request<Notification>('POST', `/api/notifications/${id}/read`),

  staffBookings: (date_from: string, date_to: string, counselor_id?: number) =>
    request<Booking[]>('GET', '/api/staff/bookings' + qs({ date_from, date_to, counselor_id })),
  staffBooking: (id: number) => request<CounselorBookingDetail>('GET', `/api/staff/bookings/${id}`),
  callAttempt: (id: number) => request<Booking>('POST', `/api/staff/bookings/${id}/call-attempt`),
  noShow: (id: number) => request<Booking>('POST', `/api/staff/bookings/${id}/no-show`),
  staffCancel: (id: number, reason: string) => request<Booking>('POST', `/api/staff/bookings/${id}/cancel`, { reason }),
  saveRecord: (id: number, body: RecordInput) => request<ConsultRecord>('PUT', `/api/staff/bookings/${id}/record`, body),
  submitRecord: (id: number, body: RecordInput) =>
    request<ConsultRecord>('POST', `/api/staff/bookings/${id}/record/submit`, body),

  staffSlots: (date_from: string, date_to: string, counselor_id?: number) =>
    request<StaffSlot[]>('GET', '/api/staff/slots' + qs({ date_from, date_to, counselor_id })),
  bulkSlots: (body: {
    counselor_id?: number;
    date_from: string;
    date_to: string;
    weekdays: number[];
    start_time: string;
    end_time: string;
    break_start: string | null;
    break_end: string | null;
  }) => request<{ created: number; skipped: number; waitlist_offers: number }>('POST', '/api/staff/slots/bulk', body),
  patchSlot: (id: number, status: 'OPEN' | 'BLOCKED') => request<StaffSlot>('PATCH', `/api/staff/slots/${id}`, { status }),

  dashboard: (date_from: string, date_to: string) =>
    request<Dashboard>('GET', '/api/admin/dashboard' + qs({ date_from, date_to })),
};
