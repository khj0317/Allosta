import { Link, useSearchParams } from 'react-router-dom';
import { api, type Booking, type WaitlistEntry } from '../../api';
import { BOOKING_STATUS, fmtDate, fmtDateTime, fmtTime, parseLocal, WAITLIST_STATUS } from '../../format';
import { Badge, Card, Empty, ErrorBox, Spinner, useAction, useAsync } from '../../components/ui';

export function MyBookings() {
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') === 'waitlist' ? 'waitlist' : 'bookings';
  const bookings = useAsync(api.myBookings);
  const waitlist = useAsync(api.myWaitlist);
  const offers = waitlist.data?.filter((w) => w.status === 'OFFERED') ?? [];

  const upcoming = bookings.data?.filter((b) => b.status === 'CONFIRMED').reverse() ?? [];
  const past = bookings.data?.filter((b) => b.status !== 'CONFIRMED') ?? [];

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">My Bookings</p>
          <h1>예약 내역</h1>
        </div>
        <Link to="/my/book" className="btn">새 상담 예약</Link>
      </div>

      {offers.map((o) => (
        <OfferBanner key={o.id} entry={o} onChanged={() => { waitlist.reload(); bookings.reload(); }} />
      ))}

      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'bookings'} className={tab === 'bookings' ? 'on' : ''} onClick={() => setParams({})}>
          상담 예약
        </button>
        <button role="tab" aria-selected={tab === 'waitlist'} className={tab === 'waitlist' ? 'on' : ''} onClick={() => setParams({ tab: 'waitlist' })}>
          대기 신청 {waitlist.data && waitlist.data.filter((w) => w.status === 'WAITING').length > 0 && `(${waitlist.data.filter((w) => w.status === 'WAITING').length})`}
        </button>
      </div>

      {tab === 'bookings' ? (
        <>
          <ErrorBox error={bookings.error} />
          {!bookings.data ? (
            <Spinner />
          ) : (
            <div className="stack">
              <Card title={`예정된 상담 ${upcoming.length}건`}>
                {upcoming.length === 0 ? <Empty>예정된 상담이 없습니다.</Empty> : <BookingList items={upcoming} />}
              </Card>
              <Card title="지난 상담">
                {past.length === 0 ? <Empty>지난 상담이 없습니다.</Empty> : <BookingList items={past} />}
              </Card>
            </div>
          )}
        </>
      ) : (
        <WaitlistList entries={waitlist.data} onChanged={waitlist.reload} />
      )}
    </>
  );
}

function BookingList({ items }: { items: Booking[] }) {
  return (
    <ul className="list">
      {items.map((b) => (
        <li key={b.id}>
          <Link to={`/my/bookings/${b.id}`} className="list-item">
            <div className="when">
              <div className="when-date">{fmtDate(b.start_at)}</div>
              <div className="when-time">{fmtTime(b.start_at)}</div>
            </div>
            <div className="grow">
              <div>
                <strong>{b.subject_name}</strong> · {b.service_label}
              </div>
              <div className="muted small">{b.counselor_name} 상담사 · {b.contact_phone}</div>
            </div>
            <div className="right">
              <Badge tone={BOOKING_STATUS[b.status].tone}>{BOOKING_STATUS[b.status].label}</Badge>
              {b.status === 'CONFIRMED' && !b.attendance_confirmed_at && <Badge tone="warn">참석 확인 필요</Badge>}
              {b.record_status === 'SUBMITTED' && <Badge tone="ok">상담 요약 도착</Badge>}
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function OfferBanner({ entry, onChanged }: { entry: WaitlistEntry; onChanged: () => void }) {
  const act = useAction();
  if (!entry.offered_slot) return null;
  const mins = entry.offer_expires_at ? Math.max(0, Math.round((parseLocal(entry.offer_expires_at).getTime() - Date.now()) / 60000)) : 0;
  return (
    <div className="alert alert-offer">
      <div>
        <strong>기다리시던 시간에 자리가 났어요!</strong>
        <div>
          {fmtDateTime(entry.offered_slot.start_at)} · {entry.offered_slot.counselor_name} 상담사 · {entry.subject_name}님 결과 상담
        </div>
        {entry.current_booking && (
          <div className="small">
            확정하면 지금 잡혀 있는 {fmtDateTime(entry.current_booking.start_at)} 예약이 이 시간으로 변경됩니다.
          </div>
        )}
        <div className="small">{mins}분 안에 확정하지 않으면 다음 대기자에게 넘어갑니다.</div>
        <ErrorBox error={act.error} />
      </div>
      <div className="row-actions">
        <button className="btn btn-ghost btn-sm" disabled={act.busy} onClick={() => act.run(() => api.declineOffer(entry.id)).then(onChanged)}>
          이 시간은 어려워요
        </button>
        <button className="btn btn-sm" disabled={act.busy} onClick={() => act.run(() => api.acceptOffer(entry.id)).then(onChanged)}>
          {entry.current_booking ? '이 시간으로 변경' : '예약 확정'}
        </button>
      </div>
    </div>
  );
}

function WaitlistList({ entries, onChanged }: { entries: WaitlistEntry[] | null; onChanged: () => void }) {
  const act = useAction();
  if (!entries) return <Spinner />;
  return (
    <Card>
      <ErrorBox error={act.error} />
      {entries.length === 0 ? (
        <Empty>대기 신청 내역이 없습니다. 원하는 날짜가 마감이면 예약 화면에서 대기 신청할 수 있어요.</Empty>
      ) : (
        <ul className="list">
          {entries.map((w) => (
            <li key={w.id} className="list-item">
              <div className="when">
                <div className="when-date">{fmtDate(w.desired_date)}</div>
                <div className="when-time">{w.start_hour}~{w.end_hour}시</div>
              </div>
              <div className="grow">
                <strong>{w.subject_name}</strong>님 결과 상담
                <div className="muted small">
                  신청 {fmtDateTime(w.created_at)}
                  {w.current_booking && <> · 현재 예약 {fmtDateTime(w.current_booking.start_at)} (자리가 나면 변경)</>}
                </div>
              </div>
              <div className="right">
                <Badge tone={WAITLIST_STATUS[w.status].tone}>{WAITLIST_STATUS[w.status].label}</Badge>
                {w.booking_id && <Link to={`/my/bookings/${w.booking_id}`} className="small">예약 보기</Link>}
                {(w.status === 'WAITING' || w.status === 'OFFERED') && (
                  <button className="btn btn-ghost btn-sm" disabled={act.busy} onClick={() => act.run(() => api.cancelWaitlist(w.id)).then(onChanged)}>
                    대기 취소
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
