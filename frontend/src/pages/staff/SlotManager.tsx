import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, type StaffSlot } from '../../api';
import { useAuth } from '../../auth';
import { addDays, fmtDate, fmtTime, parseLocal, today, weekday } from '../../format';
import { Card, ErrorBox, Spinner, useAction, useAsync } from '../../components/ui';

const mondayOf = (s: string) => {
  const d = parseLocal(s);
  return addDays(s, -((d.getDay() + 6) % 7));
};

/** 주간 슬롯 그리드 + 근무 템플릿 일괄 생성. 상담사는 본인, 관리자는 상담사를 골라 관리. */
export function SlotManager() {
  const { user } = useAuth();
  const isAdmin = user?.role === 'ADMIN';
  const counselors = useAsync(api.counselors);
  const [counselorId, setCounselorId] = useState<number | undefined>(isAdmin ? undefined : user?.counselor_id ?? undefined);
  const cid = counselorId ?? (isAdmin ? counselors.data?.[0]?.id : user?.counselor_id ?? undefined);
  const [week, setWeek] = useState(mondayOf(today()));
  const days = Array.from({ length: 5 }, (_, i) => addDays(week, i));
  const slots = useAsync(() => (cid ? api.staffSlots(week, addDays(week, 4), cid) : Promise.resolve([])), [week, cid]);
  const act = useAction();

  const { times, grid } = useMemo(() => {
    const grid = new Map<string, StaffSlot>();
    const times = new Set<string>();
    (slots.data ?? []).forEach((s) => {
      grid.set(s.start_at, s);
      times.add(fmtTime(s.start_at));
    });
    return { times: [...times].sort(), grid };
  }, [slots.data]);

  const counts = useMemo(() => {
    const l = slots.data ?? [];
    return {
      open: l.filter((s) => s.status === 'OPEN' && !s.booking_id).length,
      booked: l.filter((s) => s.booking_id).length,
      blocked: l.filter((s) => s.status === 'BLOCKED').length,
    };
  }, [slots.data]);

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">Schedule</p>
          <h1>{isAdmin ? '상담사 일정 관리' : '내 상담 일정'}</h1>
          <p className="sub">빈 칸을 눌러 닫거나 다시 열 수 있어요. 새로 연 시간은 대기 중인 고객에게 먼저 안내됩니다.</p>
        </div>
        <div className="row">
          {isAdmin && (
            <select value={cid ?? ''} onChange={(e) => setCounselorId(Number(e.target.value))}>
              {counselors.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
          <div className="date-nav">
            <button className="btn btn-ghost btn-sm" onClick={() => setWeek(addDays(week, -7))} aria-label="이전 주">‹</button>
            <span className="small">{fmtDate(week)} 주</span>
            <button className="btn btn-ghost btn-sm" onClick={() => setWeek(addDays(week, 7))} aria-label="다음 주">›</button>
          </div>
        </div>
      </div>

      <div className="kpis">
        <div className="kpi"><span>예약됨</span><strong>{counts.booked}</strong></div>
        <div className="kpi"><span>예약 가능</span><strong>{counts.open}</strong></div>
        <div className="kpi"><span>닫힘</span><strong>{counts.blocked}</strong></div>
      </div>

      <ErrorBox error={act.error || slots.error} />
      <div className="workspace">
        <Card>
          {slots.loading && !slots.data ? (
            <Spinner />
          ) : times.length === 0 ? (
            <p className="empty">이 주에는 생성된 상담 시간이 없습니다. 오른쪽에서 근무 시간을 일괄 생성하세요.</p>
          ) : (
            <div className="table-wrap">
              <table className="slot-grid">
                <thead>
                  <tr>
                    <th />
                    {days.map((d) => (
                      <th key={d} className={d === today() ? 'today' : ''}>
                        {parseLocal(d).getMonth() + 1}/{parseLocal(d).getDate()} ({weekday(d)})
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {times.map((t) => (
                    <tr key={t}>
                      <th>{t}</th>
                      {days.map((d) => {
                        const s = grid.get(`${d}T${t}:00`);
                        if (!s) return <td key={d} className="none" />;
                        const past = parseLocal(s.start_at) < new Date();
                        if (s.booking_id)
                          return (
                            <td key={d} className="booked">
                              <Link to={`/staff/bookings/${s.booking_id}`}>{s.booking_customer}</Link>
                            </td>
                          );
                        const held = s.hold_until && parseLocal(s.hold_until) > new Date();
                        return (
                          <td key={d} className={held ? 'held' : s.status === 'BLOCKED' ? 'blocked' : 'open'}>
                            <button
                              disabled={past || act.busy || !!held}
                              onClick={() => act.run(() => api.patchSlot(s.id, s.status === 'OPEN' ? 'BLOCKED' : 'OPEN')).then(slots.reload)}
                              title={held ? '대기자에게 제안 중' : s.status === 'OPEN' ? '클릭해서 닫기' : '클릭해서 열기'}
                            >
                              {held ? '대기자 제안 중' : past ? '–' : s.status === 'OPEN' ? '예약 가능' : '닫힘'}
                            </button>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <BulkCreate counselorId={cid} onDone={slots.reload} defaultFrom={week} />
      </div>
    </>
  );
}

function BulkCreate({ counselorId, onDone, defaultFrom }: { counselorId?: number; onDone: () => void; defaultFrom: string }) {
  const [from, setFrom] = useState(addDays(defaultFrom, 21));
  const [to, setTo] = useState(addDays(defaultFrom, 25));
  const [weekdays, setWeekdays] = useState([0, 1, 2, 3, 4]);
  const [start, setStart] = useState('10:00');
  const [end, setEnd] = useState('18:00');
  const [brk, setBrk] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);
  const act = useAction();
  return (
    <Card title="근무 시간 일괄 생성">
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          setMsg(null);
          act
            .run(() =>
              api.bulkSlots({
                counselor_id: counselorId,
                date_from: from,
                date_to: to,
                weekdays,
                start_time: start,
                end_time: end,
                break_start: brk ? '12:00' : null,
                break_end: brk ? '13:00' : null,
              }),
            )
            .then((r) => {
              setMsg(`${r.created}개 생성 (중복 ${r.skipped}개 제외)${r.waitlist_offers ? ` · 대기자 ${r.waitlist_offers}명에게 자리 안내` : ''}`);
              onDone();
            });
        }}
      >
        <div className="grid-2">
          <label>시작일<input type="date" min={today()} value={from} onChange={(e) => setFrom(e.target.value)} required /></label>
          <label>종료일<input type="date" min={from} value={to} onChange={(e) => setTo(e.target.value)} required /></label>
        </div>
        <div>
          <div className="label">요일</div>
          <div className="chips">
            {['월', '화', '수', '목', '금', '토', '일'].map((w, i) => (
              <button
                type="button"
                key={w}
                className={`chip chip-sm ${weekdays.includes(i) ? 'on' : ''}`}
                onClick={() => setWeekdays((v) => (v.includes(i) ? v.filter((x) => x !== i) : [...v, i]))}
              >
                {w}
              </button>
            ))}
          </div>
        </div>
        <div className="grid-2">
          <label>근무 시작<input type="time" step={1800} value={start} onChange={(e) => setStart(e.target.value)} /></label>
          <label>근무 종료<input type="time" step={1800} value={end} onChange={(e) => setEnd(e.target.value)} /></label>
        </div>
        <label className="check">
          <input type="checkbox" checked={brk} onChange={(e) => setBrk(e.target.checked)} /> 점심시간(12~13시) 제외
        </label>
        <ErrorBox error={act.error} />
        {msg && <div className="alert alert-ok">{msg}</div>}
        <button className="btn" disabled={act.busy || !counselorId}>30분 단위로 생성</button>
      </form>
    </Card>
  );
}
