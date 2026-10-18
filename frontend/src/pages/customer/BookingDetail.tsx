import { useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../../api';
import { BOOKING_STATUS, fmtDate, fmtDateTime, RELATION, won } from '../../format';
import { IndicatorTable } from '../../components/IndicatorTable';
import { Badge, Card, ErrorBox, Modal, Spinner, useAction, useAsync } from '../../components/ui';

export function BookingDetail() {
  const id = Number(useParams().id);
  const [params] = useSearchParams();
  const nav = useNavigate();
  const { data: b, error, reload } = useAsync(() => api.booking(id), [id]);
  const record = useAsync(() => api.customerRecord(id), [id]);
  const act = useAction();
  const [cancelling, setCancelling] = useState(false);

  if (error) return <ErrorBox error={error} />;
  if (!b) return <Spinner />;

  return (
    <>
      <div className="page-head">
        <div>
          <Link to="/my/bookings" className="back">← 예약 내역</Link>
          <p className="eyebrow">Booking</p>
          <h1>
            {fmtDateTime(b.start_at)} 상담 <Badge tone={BOOKING_STATUS[b.status].tone}>{BOOKING_STATUS[b.status].label}</Badge>
          </h1>
        </div>
      </div>
      {params.get('created') && b.status === 'CONFIRMED' && (
        <div className="alert alert-ok">예약이 확정되었습니다. 확인 문자를 보내드렸고, 상담 전날과 1시간 전에 다시 알려드릴게요.</div>
      )}
      <ErrorBox error={act.error} />

      {b.status === 'CONFIRMED' && (
        <Card className={b.attendance_confirmed_at ? '' : 'card-attn'}>
          {b.attendance_confirmed_at ? (
            <p>
              <strong>참석 확인 완료.</strong> {fmtDateTime(b.start_at)}에 <strong>{b.contact_phone}</strong>로 전화드립니다.
            </p>
          ) : (
            <div className="attn">
              <div>
                <strong>상담 시간에 통화 가능하신가요?</strong>
                <p className="small muted">
                  {b.contact_phone}로 전화드립니다. 참석을 확인해주시면 상담사가 미리 결과를 검토하고 기다립니다. 어려우시면 미리
                  변경해주세요.
                </p>
              </div>
              <button className="btn" disabled={act.busy} onClick={() => act.run(() => api.confirmAttendance(b.id)).then(reload)}>
                네, 통화 가능합니다
              </button>
            </div>
          )}
        </Card>
      )}

      <div className="grid-2">
        <Card title="예약 정보">
          <dl className="kv">
            <dt>일시</dt>
            <dd>{fmtDateTime(b.start_at)} (30분)</dd>
            <dt>상담사</dt>
            <dd>{b.counselor_name}</dd>
            <dt>피검자</dt>
            <dd>{b.subject_name} ({RELATION[b.subject_relation]})</dd>
            <dt>분석</dt>
            <dd><Link to={`/my/results/${b.result_id}`}>{b.service_label}</Link></dd>
            <dt>연락처</dt>
            <dd>{b.contact_phone}</dd>
            {b.concern_tags.length > 0 && (
              <>
                <dt>관심 주제</dt>
                <dd>{b.concern_tags.join(', ')}</dd>
              </>
            )}
            {b.pre_questions && (
              <>
                <dt>사전 질문</dt>
                <dd className="pre">{b.pre_questions}</dd>
              </>
            )}
            {b.cancel_reason && (
              <>
                <dt>취소 사유</dt>
                <dd>{b.cancel_reason}</dd>
              </>
            )}
          </dl>
          {b.status === 'CONFIRMED' && (
            <div className="row-actions">
              {b.can_change ? (
                <>
                  <button className="btn btn-ghost" onClick={() => nav(`/my/book?reschedule=${b.id}`)}>일정 변경</button>
                  <button className="btn btn-ghost btn-danger" onClick={() => setCancelling(true)}>예약 취소</button>
                </>
              ) : (
                <p className="hint">상담 3시간 전 이후에는 고객센터(1588-0000)로 연락해주세요.</p>
              )}
            </div>
          )}
        </Card>

        {record.data ? (
          <Card title="상담 요약">
            <p className="pre">{record.data.customer_message}</p>
            {record.data.lifestyle_advice && (
              <>
                <h3>생활 습관 가이드</h3>
                <p className="pre">{record.data.lifestyle_advice}</p>
              </>
            )}
            {record.data.recommended_products.length > 0 && (
              <>
                <h3>상담사 추천</h3>
                <ul className="product-list">
                  {record.data.recommended_products.map((p) => (
                    <li key={p.id}>
                      <span>{p.name}</span>
                      <span className="muted">{won(p.price)}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {record.data.follow_up_needed && record.data.follow_up_date && (
              <div className="alert alert-info">{fmtDate(record.data.follow_up_date)} 무렵 재상담·재검사를 권해드려요.</div>
            )}
          </Card>
        ) : (
          b.status === 'COMPLETED' && <Card title="상담 요약"><p className="muted">상담사가 요약을 정리하고 있어요.</p></Card>
        )}
      </div>

      {record.data && record.data.discussed_indicators.length > 0 && (
        <Card title="상담에서 함께 살펴본 지표">
          <IndicatorTable indicators={record.data.discussed_indicators} />
        </Card>
      )}

      {cancelling && (
        <CancelModal
          onClose={() => setCancelling(false)}
          onConfirm={(reason) =>
            act.run(() => api.cancelBooking(b.id, reason)).then(() => {
              setCancelling(false);
              reload();
            })
          }
          busy={act.busy}
        />
      )}
    </>
  );
}

function CancelModal({ onClose, onConfirm, busy }: { onClose: () => void; onConfirm: (r: string) => void; busy: boolean }) {
  const [reason, setReason] = useState('개인 일정');
  return (
    <Modal title="예약을 취소할까요?" onClose={onClose}>
      <div className="form">
        <p className="muted small">취소하신 시간은 대기 중인 다른 고객에게 안내됩니다. 시간만 바꾸시려면 '일정 변경'을 이용해주세요.</p>
        <label>
          취소 사유
          <select value={reason} onChange={(e) => setReason(e.target.value)}>
            {['개인 일정', '결과 설명이 더 이상 필요 없음', '다른 채널로 문의 해결', '기타'].map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        <button className="btn btn-danger" disabled={busy} onClick={() => onConfirm(reason)}>예약 취소</button>
      </div>
    </Modal>
  );
}
