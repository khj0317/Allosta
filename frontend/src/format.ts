import type { BookingStatus, IndicatorStatus, InterestLevel, Relation, WaitlistStatus } from './api';

const WD = ['일', '월', '화', '수', '목', '금', '토'];

/** 백엔드는 KST naive ISO 문자열을 준다. 브라우저 TZ와 무관하게 그대로 해석한다. */
export function parseLocal(iso: string): Date {
  const [d, t = '00:00:00'] = iso.split('T');
  const [y, m, day] = d.split('-').map(Number);
  const [hh, mm, ss] = t.split(':').map((x) => parseInt(x, 10));
  return new Date(y, m - 1, day, hh || 0, mm || 0, ss || 0);
}

export const pad = (n: number) => String(n).padStart(2, '0');
export const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const today = () => ymd(new Date());
export const addDays = (s: string, n: number) => {
  const d = parseLocal(s);
  d.setDate(d.getDate() + n);
  return ymd(d);
};

export const fmtDate = (iso: string) => {
  const d = parseLocal(iso);
  return `${d.getMonth() + 1}월 ${d.getDate()}일 (${WD[d.getDay()]})`;
};
export const fmtTime = (iso: string) => {
  const d = parseLocal(iso);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
};
export const fmtDateTime = (iso: string) => `${fmtDate(iso)} ${fmtTime(iso)}`;
export const weekday = (s: string) => WD[parseLocal(s).getDay()];

export const pct = (v: number | null | undefined) => (v === null || v === undefined ? '–' : `${(v * 100).toFixed(1)}%`);
export const won = (v: number) => `${v.toLocaleString('ko-KR')}원`;

export const BOOKING_STATUS: Record<BookingStatus, { label: string; tone: string }> = {
  CONFIRMED: { label: '예약 확정', tone: 'info' },
  COMPLETED: { label: '상담 완료', tone: 'ok' },
  CANCELLED: { label: '취소', tone: 'muted' },
  NO_SHOW: { label: '부재(미연결)', tone: 'danger' },
};

export const WAITLIST_STATUS: Record<WaitlistStatus, { label: string; tone: string }> = {
  WAITING: { label: '대기 중', tone: 'info' },
  OFFERED: { label: '자리 제안 도착', tone: 'warn' },
  BOOKED: { label: '예약 전환', tone: 'ok' },
  EXPIRED: { label: '만료', tone: 'muted' },
  CANCELLED: { label: '대기 취소', tone: 'muted' },
};

export const INDICATOR_STATUS: Record<IndicatorStatus, { label: string; tone: string }> = {
  NORMAL: { label: '정상', tone: 'ok' },
  LOW: { label: '낮음', tone: 'info' },
  HIGH: { label: '높음', tone: 'danger' },
  CAUTION: { label: '주의', tone: 'warn' },
};

export const INTEREST: Record<InterestLevel, string> = {
  HIGH: '높음',
  MEDIUM: '보통',
  LOW: '낮음',
  NONE: '관심 없음',
};

export const RELATION: Record<Relation, string> = {
  SELF: '본인',
  SPOUSE: '배우자',
  PARENT: '부모',
  CHILD: '자녀',
  SIBLING: '형제자매',
  OTHER: '기타',
};
