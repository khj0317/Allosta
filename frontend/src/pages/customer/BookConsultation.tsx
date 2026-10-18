import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api, ApiError, type Slot } from '../../api';
import { useAuth } from '../../auth';
import { fmtDate, fmtDateTime, fmtTime, parseLocal, RELATION, today, weekday } from '../../format';
import { Card, Empty, ErrorBox, Spinner, useAction, useAsync } from '../../components/ui';

/**
 * 상담 예약 / 일정 변경 공용 화면.
 * - ?reschedule=<bookingId> 이면 결과지는 고정, 새 슬롯 선택 시 변경 API 호출
 * - 원하는 날짜가 마감이면 같은 화면에서 '대기 신청'으로 바로 전환(이탈 방지)
 */
export function BookConsultation() {
  const { user } = useAuth();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const rescheduleId = params.get('reschedule') ? Number(params.get('reschedule')) : null;

  const { data: subjects } = useAsync(api.subjects);
  const { data: meta } = useAsync(api.meta);
  const { data: original } = useAsync(
    () => (rescheduleId ? api.booking(rescheduleId) : Promise.resolve(null)),
    [rescheduleId],
  );

  const [subjectId, setSubjectId] = useState<number | null>(Number(params.get('subject')) || null);
  const [resultId, setResultId] = useState<number | null>(Number(params.get('result')) || null);
  useEffect(() => {
    if (original) {
      setSubjectId(original.subject_id);
      setResultId(original.result_id);
    }
  }, [original]);

  const subject = subjects?.find((s) => s.id === subjectId) ?? null;
  const result = subject?.results.find((r) => r.id === resultId) ?? null;
  const needsConsent = subject && subject.relation !== 'SELF' && !subject.consent_at;

  const [date, setDate] = useState<string | null>(null);
  const [slot, setSlot] = useState<Slot | null>(null);
  const [phone, setPhone] = useState(user?.phone ?? '');
  const [tags, setTags] = useState<string[]>([]);
  const [questions, setQuestions] = useState('');
  const [alternatives, setAlternatives] = useState<Slot[] | null>(null);
  const [showWaitlist, setShowWaitlist] = useState(false);
  const act = useAction();

  const calendar = useAsync(
    () => (result ? api.calendar(result.service_type, today(), 21) : Promise.resolve([])),
    [result?.service_type],
  );
  const slots = useAsync(
    () => (result && date ? api.availableSlots(result.service_type, date, date) : Promise.resolve([] as Slot[])),
    [result?.service_type, date],
  );

  // 같은 시각에 여러 상담사가 가능하면 묶어서 보여준다(고객에겐 '시간'이 1순위)
  const byTime = useMemo(() => {
    const m = new Map<string, Slot[]>();
    (slots.data ?? []).forEach((s) => m.set(s.start_at, [...(m.get(s.start_at) ?? []), s]));
    return [...m.entries()];
  }, [slots.data]);

  const submit = async () => {
    if (!slot || !subject || !result) return;
    setAlternatives(null);
    try {
      const b = await act.run(() =>
        rescheduleId
          ? api.reschedule(rescheduleId, slot.id)
          : api.createBooking({
              slot_id: slot.id,
              subject_id: subject.id,
              result_id: result.id,
              contact_phone: phone,
              pre_questions: questions,
              concern_tags: tags,
            }),
      );
      nav(`/my/bookings/${b.id}?created=1`);
    } catch (e) {
      if (e instanceof ApiError && e.code === 'SLOT_TAKEN') {
        setAlternatives((e.extra.alternatives as Slot[]) ?? []);
        setSlot(null);
        slots.reload();
        calendar.reload();
      }
    }
  };

  if (!subjects || !meta) return <Spinner />;

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">Booking</p>
          <h1>{rescheduleId ? '상담 일정 변경' : '상담 예약'}</h1>
          <p className="sub">상담은 약 30분간 전문 상담사가 입력하신 번호로 전화를 드리는 방식으로 진행됩니다.</p>
        </div>
      </div>

      {original && (
        <div className="alert alert-info">
          현재 예약: <strong>{fmtDateTime(original.start_at)}</strong> · {original.counselor_name} 상담사 — 새 시간을 선택하면 기존 예약은
          자동 취소됩니다.
        </div>
      )}

      <div className="book-grid">
        <div className="stack">
          <Card title={<><span className="step-no">01</span> 상담받을 결과지</>}>
            {rescheduleId ? (
              <p>
                {original?.subject_name} · {original?.service_label}
              </p>
            ) : (
              <div className="choice-list">
                {subjects.flatMap((s) =>
                  s.results.map((r) => (
                    <label key={r.id} className={`choice ${resultId === r.id ? 'on' : ''}`}>
                      <input
                        type="radio"
                        name="result"
                        checked={resultId === r.id}
                        onChange={() => {
                          setSubjectId(s.id);
                          setResultId(r.id);
                          setDate(null);
                          setSlot(null);
                        }}
                      />
                      <span>
                        <strong>{s.name}</strong> <span className="tag">{RELATION[s.relation]}</span>
                        <br />
                        <span className="small">{r.service_label} · {fmtDate(r.reported_at)}</span>
                      </span>
                    </label>
                  )),
                )}
              </div>
            )}
            {needsConsent && (
              <div className="alert alert-warn">
                {subject.name}님 본인의 휴대폰 인증이 필요합니다. <Link to="/my">내 검사 결과</Link>에서 인증을 마친 뒤 예약해주세요.
              </div>
            )}
          </Card>

          {result && !needsConsent && (
            <Card title={<><span className="step-no">02</span> 날짜</>} actions={<span className="muted small">숫자는 남은 상담 수</span>}>
              {calendar.loading && !calendar.data ? (
                <Spinner />
              ) : (
                <div className="date-strip">
                  {calendar.data?.map((d) => {
                    const weekend = ['토', '일'].includes(weekday(d.date));
                    const full = d.available === 0;
                    return (
                      <button
                        key={d.date}
                        className={`date-cell ${date === d.date ? 'on' : ''} ${full ? 'full' : ''}`}
                        onClick={() => {
                          setDate(d.date);
                          setSlot(null);
                          setAlternatives(null);
                          setShowWaitlist(full && !weekend);
                        }}
                        disabled={weekend}
                      >
                        <span className="dc-wd">{weekday(d.date)}</span>
                        <span className="dc-day">{parseLocal(d.date).getDate()}</span>
                        <span className="dc-cnt">{weekend ? '휴무' : full ? '마감' : d.available}</span>
                      </button>
                    );
                  })}
                </div>
              )}
            </Card>
          )}

          {result && date && !needsConsent && (
            <Card
              title={<><span className="step-no">03</span> 시간 · {fmtDate(date)}</>}
              actions={
                <button className="btn btn-ghost btn-sm" onClick={() => setShowWaitlist((v) => !v)}>
                  원하는 시간이 없나요? 대기 신청
                </button>
              }
            >
              {alternatives && (
                <div className="alert alert-warn">
                  <div>
                    <strong>방금 다른 고객이 먼저 예약했어요.</strong> 가까운 다른 시간을 추천드려요.
                  </div>
                  <div className="chips">
                    {alternatives.length === 0 && <span>추천 가능한 시간이 없습니다. 대기 신청을 이용해주세요.</span>}
                    {alternatives.map((a) => (
                      <button
                        key={a.id}
                        className="chip"
                        onClick={() => {
                          setDate(a.start_at.slice(0, 10));
                          setSlot(a);
                          setAlternatives(null);
                        }}
                      >
                        {fmtDateTime(a.start_at)} · {a.counselor_name}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {slots.loading ? (
                <Spinner />
              ) : byTime.length === 0 ? (
                <Empty>이 날짜는 예약이 모두 찼습니다. 대기 신청을 하시면 자리가 날 때 바로 알려드려요.</Empty>
              ) : (
                <div className="time-grid">
                  {byTime.map(([start, list]) => (
                    <div key={start} className="time-row">
                      <div className="time-label">{fmtTime(start)}</div>
                      <div className="chips">
                        {list.map((s) => (
                          <button
                            key={s.id}
                            className={`chip ${slot?.id === s.id ? 'on' : ''}`}
                            onClick={() => setSlot(s)}
                          >
                            {s.counselor_name} 상담사
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {showWaitlist && result && subject && (
                <WaitlistForm
                  subjectId={subject.id}
                  resultId={result.id}
                  date={date}
                  phone={original?.contact_phone ?? phone}
                  rescheduling={!!original}
                  onDone={() => nav('/my/bookings?tab=waitlist')}
                />
              )}
            </Card>
          )}
        </div>

        <aside className="stack sticky">
          <Card title={rescheduleId ? '변경 내용' : <><span className="step-no">04</span> 상담 정보</>}>
            <dl className="kv">
              <dt>피검자</dt>
              <dd>{subject ? `${subject.name} (${RELATION[subject.relation]})` : '–'}</dd>
              <dt>분석</dt>
              <dd>{result?.service_label ?? '–'}</dd>
              <dt>일시</dt>
              <dd>{slot ? fmtDateTime(slot.start_at) : '–'}</dd>
              <dt>상담사</dt>
              <dd>{slot?.counselor_name ?? '–'}</dd>
            </dl>
            {!rescheduleId && (
              <div className="form">
                <label>
                  상담 전화 받을 번호
                  <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="010-0000-0000" />
                  <span className="hint">가족 결과 상담이라면 실제 통화하실 분의 번호를 입력해주세요.</span>
                </label>
                <div>
                  <div className="label">궁금한 주제 (선택)</div>
                  <div className="chips">
                    {meta.concern_tags.map((t) => (
                      <button
                        type="button"
                        key={t}
                        className={`chip chip-sm ${tags.includes(t) ? 'on' : ''}`}
                        onClick={() => setTags((v) => (v.includes(t) ? v.filter((x) => x !== t) : [...v, t]))}
                      >
                        {t}
                      </button>
                    ))}
                  </div>
                </div>
                <label>
                  사전 질문 (선택)
                  <textarea
                    rows={3}
                    value={questions}
                    onChange={(e) => setQuestions(e.target.value)}
                    placeholder="상담사가 미리 확인하고 준비해요. 예) 공복혈당이 높은데 어떤 음식을 줄여야 하나요?"
                  />
                </label>
              </div>
            )}
            <ErrorBox error={act.error instanceof ApiError && act.error.code === 'SLOT_TAKEN' ? null : act.error} />
            <button className="btn btn-block" disabled={!slot || act.busy} onClick={submit}>
              {act.busy ? '처리 중…' : rescheduleId ? '이 시간으로 변경' : '예약 확정'}
            </button>
            <p className="hint">상담 3시간 전까지 온라인으로 변경·취소할 수 있어요. 전날과 1시간 전에 알림을 보내드려요.</p>
          </Card>
        </aside>
      </div>
    </>
  );
}

function WaitlistForm({
  subjectId,
  resultId,
  date,
  phone,
  rescheduling,
  onDone,
}: {
  subjectId: number;
  resultId: number;
  date: string;
  phone: string;
  rescheduling: boolean;
  onDone: () => void;
}) {
  const [start, setStart] = useState(10);
  const [end, setEnd] = useState(18);
  const act = useAction();
  const hours = Array.from({ length: 10 }, (_, i) => 9 + i);
  return (
    <div className="waitlist-box">
      <h3>대기 신청 · {fmtDate(date)}</h3>
      <p className="small muted">
        희망 시간대에 취소나 추가 일정으로 자리가 생기면 신청 순서대로 알림을 보내드려요. 알림 후 30분 안에 확정하시면 예약됩니다.
        {rescheduling && ' 지금 예약은 그대로 유지되고, 확정하는 순간 새 시간으로 옮겨집니다.'}
      </p>
      <div className="row">
        <label>
          부터
          <select value={start} onChange={(e) => setStart(Number(e.target.value))}>
            {hours.map((h) => <option key={h} value={h}>{h}:00</option>)}
          </select>
        </label>
        <label>
          까지
          <select value={end} onChange={(e) => setEnd(Number(e.target.value))}>
            {hours.map((h) => <option key={h + 1} value={h + 1}>{h + 1}:00</option>)}
          </select>
        </label>
        <button
          className="btn"
          disabled={act.busy || end <= start}
          onClick={() =>
            act
              .run(() =>
                api.joinWaitlist({
                  subject_id: subjectId,
                  result_id: resultId,
                  desired_date: date,
                  start_hour: start,
                  end_hour: end,
                  contact_phone: phone,
                  pre_questions: '',
                }),
              )
              .then(onDone)
          }
        >
          대기 신청
        </button>
      </div>
      <ErrorBox error={act.error} />
    </div>
  );
}
