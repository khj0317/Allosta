import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api, type Booking } from '../../api';
import { useAuth } from '../../auth';
import { addDays, BOOKING_STATUS, fmtDate, fmtTime, parseLocal, today } from '../../format';
import { Badge, Card, Empty, ErrorBox, Spinner, useAsync } from '../../components/ui';

/** 상담사: 오늘의 상담 / 관리자: 전체 예약 조회 */
export function StaffSchedule() {
  const { user } = useAuth();
  const isAdmin = user?.role === 'ADMIN';
  const [date, setDate] = useState(today());
  const [counselorId, setCounselorId] = useState<number | undefined>();
  const counselors = useAsync(() => (isAdmin ? api.counselors() : Promise.resolve([])), [isAdmin]);
  const day = useAsync(() => api.staffBookings(date, date, counselorId), [date, counselorId]);
  // 시간이 지났는데 기록 제출·부재 처리가 안 된 상담(기간 제한 없음): 처리해야 고객이 요약을 받고 지표가 맞는다
  const pending = useAsync(() => api.overdueBookings(counselorId), [counselorId]);

  const list = day.data ?? [];
  const active = list.filter((b) => b.status !== 'CANCELLED');
  const unconfirmed = active.filter((b) => b.status === 'CONFIRMED' && !b.attendance_confirmed_at);

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">{isAdmin ? 'Bookings' : 'Today'}</p>
          <h1>{isAdmin ? '전체 예약' : '오늘의 상담'}</h1>
          <p className="sub">참석 미확인 고객은 상담 전에 미리 문자/전화로 확인하면 부재를 줄일 수 있어요.</p>
        </div>
        <div className="row">
          {isAdmin && (
            <select value={counselorId ?? ''} onChange={(e) => setCounselorId(e.target.value ? Number(e.target.value) : undefined)}>
              <option value="">전체 상담사</option>
              {counselors.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
          <div className="date-nav">
            <button className="btn btn-ghost btn-sm" onClick={() => setDate(addDays(date, -1))} aria-label="이전 날">‹</button>
            <input type="date" value={date} onChange={(e) => e.target.value && setDate(e.target.value)} />
            <button className="btn btn-ghost btn-sm" onClick={() => setDate(addDays(date, 1))} aria-label="다음 날">›</button>
            {date !== today() && <button className="btn btn-ghost btn-sm" onClick={() => setDate(today())}>오늘</button>}
          </div>
        </div>
      </div>

      {pending.data && pending.data.length > 0 && (
        <div className="alert alert-warn">
          <div>
            <strong>처리 안 된 지난 상담 {pending.data.length}건</strong> — 기록을 제출하거나 부재 처리해야 고객에게 요약이 전달되고 지표에
            반영됩니다.
          </div>
          <div className="chips">
            {pending.data.slice(0, 10).map((b) => (
              <Link key={b.id} to={`/staff/bookings/${b.id}`} className="chip">
                {fmtDate(b.start_at)} {fmtTime(b.start_at)} {b.customer_name}
                {isAdmin && ` · ${b.counselor_name}`}
              </Link>
            ))}
            {pending.data.length > 10 && <span className="small muted">외 {pending.data.length - 10}건</span>}
          </div>
        </div>
      )}

      <div className="kpis">
        <div className="kpi"><span>{fmtDate(date)} 상담</span><strong>{active.length}</strong></div>
        <div className="kpi"><span>참석 미확인</span><strong className={unconfirmed.length ? 'text-warn' : ''}>{unconfirmed.length}</strong></div>
        <div className="kpi"><span>완료</span><strong>{active.filter((b) => b.status === 'COMPLETED').length}</strong></div>
        <div className="kpi"><span>부재</span><strong>{active.filter((b) => b.status === 'NO_SHOW').length}</strong></div>
      </div>

      <ErrorBox error={day.error} />
      <Card>
        {day.loading && !day.data ? <Spinner /> : list.length === 0 ? <Empty>이 날 예약된 상담이 없습니다.</Empty> : <ScheduleList items={list} showCounselor={isAdmin} />}
      </Card>
    </>
  );
}

function ScheduleList({ items, showCounselor }: { items: Booking[]; showCounselor: boolean }) {
  const now = new Date();
  return (
    <ul className="list">
      {items.map((b) => {
        const started = parseLocal(b.start_at) <= now;
        return (
          <li key={b.id}>
            <Link to={`/staff/bookings/${b.id}`} className={`list-item ${b.status === 'CANCELLED' ? 'dim' : ''}`}>
              <div className="when">
                <div className="when-time big">{fmtTime(b.start_at)}</div>
              </div>
              <div className="grow">
                <div>
                  <strong>{b.customer_name}</strong>
                  {b.subject_relation !== 'SELF' && <span className="muted"> (피검자: {b.subject_name})</span>} · {b.service_label}
                </div>
                <div className="muted small">
                  {showCounselor && <>{b.counselor_name} 상담사 · </>}
                  {b.contact_phone}
                  {b.concern_tags.length > 0 && <> · {b.concern_tags.join(', ')}</>}
                </div>
                {b.pre_questions && <div className="small quote">“{b.pre_questions}”</div>}
              </div>
              <div className="right">
                <Badge tone={BOOKING_STATUS[b.status].tone}>{BOOKING_STATUS[b.status].label}</Badge>
                {b.status === 'CONFIRMED' &&
                  (b.attendance_confirmed_at ? <Badge tone="ok">참석 확인</Badge> : <Badge tone="warn">참석 미확인</Badge>)}
                {b.status === 'CONFIRMED' && started && <Badge tone="danger">기록 대기</Badge>}
                {b.call_attempts > 0 && b.status === 'CONFIRMED' && <span className="small muted">통화 시도 {b.call_attempts}회</span>}
              </div>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
