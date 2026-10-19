import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, type InterestLevel, type RecordInput } from '../../api';
import { useAuth } from '../../auth';
import { BOOKING_STATUS, fmtDate, fmtDateTime, INTEREST, parseLocal, RELATION, won } from '../../format';
import { IndicatorTable } from '../../components/IndicatorTable';
import { Badge, Card, ErrorBox, Spinner, useAction, useAsync } from '../../components/ui';

const FIELD_LABEL: Record<string, string> = {
  concern_tags: '관심사 태그',
  discussed_indicator_ids: '논의 지표',
  summary: '내부 요약',
  customer_message: '고객 안내 메시지',
  lifestyle_advice: '생활습관 가이드',
  follow_up_needed: '후속 조치',
  follow_up_date: '후속 일정',
  recommendations: '추천 제품',
};

const EMPTY: RecordInput = {
  concern_tags: [],
  discussed_indicator_ids: [],
  summary: '',
  customer_message: '',
  lifestyle_advice: '',
  follow_up_needed: false,
  follow_up_date: null,
  recommendations: [],
};

/**
 * 상담사 상담 화면: 왼쪽 = 고객/결과지 맥락, 오른쪽 = 구조화된 상담 기록 폼.
 * 통화하면서 바로 기록하도록 한 화면에 둔다.
 */
export function ConsultWorkspace() {
  const id = Number(useParams().id);
  const { user } = useAuth();
  const isCounselor = user?.role === 'COUNSELOR';
  const detail = useAsync(() => api.staffBooking(id), [id]);
  const { data: meta } = useAsync(api.meta);
  const { data: products } = useAsync(api.products);
  const [form, setForm] = useState<RecordInput>(EMPTY);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [editReason, setEditReason] = useState('');
  const [onlyAbnormal, setOnlyAbnormal] = useState(true);
  const act = useAction();

  const d = detail.data;
  useEffect(() => {
    if (!d) return;
    const r = d.record;
    setForm(
      r
        ? {
            concern_tags: r.concern_tags,
            discussed_indicator_ids: r.discussed_indicator_ids,
            summary: r.summary,
            customer_message: r.customer_message,
            lifestyle_advice: r.lifestyle_advice,
            follow_up_needed: r.follow_up_needed,
            follow_up_date: r.follow_up_date,
            recommendations: r.recommendations.map(({ product_id, interest_level, note }) => ({ product_id, interest_level, note })),
          }
        : { ...EMPTY, concern_tags: d.booking.concern_tags },
    );
    setSavedAt(r?.updated_at ?? null);
  }, [d]);

  // 결과지 종류와 관련된 제품을 위로
  const sortedProducts = useMemo(() => {
    if (!products || !d) return [];
    return [...products].sort(
      (a, b) => Number(b.related_services.includes(d.result.service_type)) - Number(a.related_services.includes(d.result.service_type)),
    );
  }, [products, d]);

  if (detail.error) return <ErrorBox error={detail.error} />;
  if (!d || !meta || !products) return <Spinner />;

  const b = d.booking;
  const started = parseLocal(b.start_at) <= new Date();
  const submitted = d.record?.status === 'SUBMITTED';
  // 제출(고객 공유)된 기록은 정해진 기간까지만, 사유를 남기고 고칠 수 있다
  const locked = submitted && !!d.record_editable_until && parseLocal(d.record_editable_until) < new Date();
  const editable = isCounselor && (b.status === 'CONFIRMED' || b.status === 'COMPLETED') && !locked;
  const set = <K extends keyof RecordInput>(k: K, v: RecordInput[K]) => setForm((f) => ({ ...f, [k]: v }));
  const toggle = <T,>(arr: T[], v: T) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
  const productName = (pid: number) => products.find((p) => p.id === pid)?.name ?? pid;

  const doAction = (fn: () => Promise<unknown>) => act.run(fn).then(() => detail.reload());

  return (
    <>
      <div className="page-head">
        <div>
          <Link to={isCounselor ? '/staff' : '/admin/bookings'} className="back">← 목록</Link>
          <p className="eyebrow">Consultation</p>
          <h1>
            {b.customer_name}님 상담 <Badge tone={BOOKING_STATUS[b.status].tone}>{BOOKING_STATUS[b.status].label}</Badge>
          </h1>
          <p className="sub">
            {fmtDateTime(b.start_at)} · {b.counselor_name} 상담사 · 통화 번호 <strong>{b.contact_phone}</strong>
            {b.contact_phone !== d.customer_phone && <> (계정 번호 {d.customer_phone})</>}
          </p>
        </div>
        {b.status === 'CONFIRMED' && (
          <div className="row">
            {b.attendance_confirmed_at ? <Badge tone="ok">고객 참석 확인</Badge> : <Badge tone="warn">참석 미확인</Badge>}
            <button className="btn btn-ghost btn-sm" disabled={act.busy} onClick={() => doAction(() => api.callAttempt(b.id))}>
              통화 시도 기록 · {b.call_attempts}회
            </button>
            {started && (
              <button
                className="btn btn-ghost btn-sm btn-danger"
                disabled={act.busy}
                onClick={() => confirm('고객과 연결되지 않아 부재 처리할까요?') && doAction(() => api.noShow(b.id))}
              >
                부재 처리
              </button>
            )}
            {!isCounselor && (
              <button
                className="btn btn-ghost btn-sm btn-danger"
                disabled={act.busy}
                onClick={() => {
                  const reason = prompt('취소 사유(고객에게 안내됩니다)');
                  if (reason) doAction(() => api.staffCancel(b.id, reason));
                }}
              >
                운영 취소
              </button>
            )}
          </div>
        )}
      </div>
      <ErrorBox error={act.error} />

      <div className="workspace">
        <div className="stack">
          <Card title="상담 요청 내용">
            <dl className="kv">
              <dt>피검자</dt>
              <dd>
                {b.subject_name} ({RELATION[b.subject_relation]}){b.subject_relation !== 'SELF' && <span className="muted"> · 계정 소유자 {b.customer_name}</span>}
              </dd>
              <dt>관심 주제</dt>
              <dd>{b.concern_tags.join(', ') || '–'}</dd>
              <dt>사전 질문</dt>
              <dd className="pre">{b.pre_questions || '–'}</dd>
            </dl>
          </Card>
          <Card
            title={`${d.result.service_label} · ${fmtDate(d.result.reported_at)}`}
            actions={
              <label className="check small">
                <input type="checkbox" checked={onlyAbnormal} onChange={(e) => setOnlyAbnormal(e.target.checked)} />
                확인 필요 지표만
              </label>
            }
          >
            <p className="small muted">{d.result.overall_comment}</p>
            <IndicatorTable
              indicators={d.result.indicators}
              onlyAbnormal={onlyAbnormal}
              selectable={editable}
              selected={form.discussed_indicator_ids}
              onToggle={(iid) => set('discussed_indicator_ids', toggle(form.discussed_indicator_ids, iid))}
            />
            {editable && <p className="hint">체크한 지표는 '상담에서 살펴본 지표'로 고객에게 공유됩니다.</p>}
          </Card>
          {d.past_bookings.length > 0 && (
            <Card title="이전 상담 이력">
              <ul className="list">
                {d.past_bookings.map((p) => (
                  <li key={p.id} className="list-item">
                    <div className="grow">
                      {fmtDate(p.start_at)} · {p.counselor_name} · {p.service_label}
                    </div>
                    <div className="muted small">{p.concern_tags.join(', ')}</div>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>

        <div className="stack sticky">
          <Card
            title="상담 기록"
            actions={
              submitted ? <Badge tone="ok">제출 완료</Badge> : savedAt ? <span className="small muted">임시저장 {fmtDateTime(savedAt)}</span> : null
            }
          >
            {!isCounselor && !d.record && <p className="muted">아직 작성된 기록이 없습니다.</p>}
            {(isCounselor || d.record) && (
              <fieldset className="form" disabled={!editable}>
                <div>
                  <div className="label">관심사 태그 *</div>
                  <div className="chips">
                    {meta.concern_tags.map((t) => (
                      <button
                        type="button"
                        key={t}
                        className={`chip chip-sm ${form.concern_tags.includes(t) ? 'on' : ''}`}
                        onClick={() => set('concern_tags', toggle(form.concern_tags, t))}
                      >
                        {t}
                      </button>
                    ))}
                  </div>
                </div>
                <label>
                  상담 요약 (내부용) *
                  <textarea rows={4} value={form.summary} onChange={(e) => set('summary', e.target.value)} placeholder="주요 상담 내용, 고객 상태·생활습관, 특이사항" />
                </label>
                <label>
                  고객 안내 메시지
                  <textarea rows={4} value={form.customer_message} onChange={(e) => set('customer_message', e.target.value)} placeholder="고객에게 공유되는 상담 요약입니다." />
                </label>
                <label>
                  생활습관 가이드
                  <textarea rows={2} value={form.lifestyle_advice} onChange={(e) => set('lifestyle_advice', e.target.value)} />
                </label>

                <div>
                  <div className="label">추천 제품 · 고객 관심도</div>
                  {form.recommendations.length === 0 && <p className="hint">추천한 제품이 있다면 추가해주세요. 관심도는 전환 분석에 사용됩니다.</p>}
                  {form.recommendations.map((r, i) => (
                    <div key={r.product_id} className="rec-row">
                      <span className="grow">{productName(r.product_id)}</span>
                      <div className="seg" role="radiogroup" aria-label="관심도">
                        {(['HIGH', 'MEDIUM', 'LOW', 'NONE'] as InterestLevel[]).map((lv) => (
                          <button
                            type="button"
                            key={lv}
                            className={r.interest_level === lv ? 'on' : ''}
                            onClick={() => set('recommendations', form.recommendations.map((x, j) => (j === i ? { ...x, interest_level: lv } : x)))}
                          >
                            {INTEREST[lv]}
                          </button>
                        ))}
                      </div>
                      <button type="button" className="link-btn" onClick={() => set('recommendations', form.recommendations.filter((_, j) => j !== i))}>
                        삭제
                      </button>
                    </div>
                  ))}
                  <select
                    value=""
                    onChange={(e) => {
                      const pid = Number(e.target.value);
                      if (pid) set('recommendations', [...form.recommendations, { product_id: pid, interest_level: 'MEDIUM', note: '' }]);
                    }}
                  >
                    <option value="">+ 제품 추가</option>
                    {[true, false].map((related) => (
                      <optgroup key={String(related)} label={related ? '이 결과지 관련 제품' : '기타 제품'}>
                        {sortedProducts
                          .filter((p) => p.related_services.includes(d.result.service_type) === related)
                          .filter((p) => !form.recommendations.some((r) => r.product_id === p.id))
                          .map((p) => (
                            <option key={p.id} value={p.id}>
                              {p.name} ({won(p.price)})
                            </option>
                          ))}
                      </optgroup>
                    ))}
                  </select>
                </div>

                <div className="row">
                  <label className="check">
                    <input type="checkbox" checked={form.follow_up_needed} onChange={(e) => set('follow_up_needed', e.target.checked)} />
                    후속 상담/재검사 필요
                  </label>
                  {form.follow_up_needed && (
                    <input type="date" value={form.follow_up_date ?? ''} onChange={(e) => set('follow_up_date', e.target.value || null)} />
                  )}
                </div>

                {editable && submitted && (
                  <label>
                    수정 사유 *
                    <input
                      value={editReason}
                      onChange={(e) => setEditReason(e.target.value)}
                      maxLength={300}
                      placeholder="예) 영양제 복용량 안내 정정"
                    />
                    <span className="hint">
                      고객에게 이미 공유된 기록입니다. 수정 이력이 남고, 고객 안내 내용이 바뀌면 고객에게 알림이 갑니다.
                      {d.record_editable_until && ` ${fmtDateTime(d.record_editable_until)}까지 수정할 수 있어요.`}
                    </span>
                  </label>
                )}

                {editable &&
                  (submitted ? (
                    <div className="row-actions">
                      <button
                        type="button"
                        className="btn"
                        disabled={act.busy || !editReason.trim()}
                        onClick={() =>
                          doAction(() => api.saveRecord(b.id, { ...form, edit_reason: editReason })).then(() => setEditReason(''))
                        }
                      >
                        수정 내용 저장
                      </button>
                    </div>
                  ) : (
                    <div className="row-actions">
                      <button
                        type="button"
                        className="btn btn-ghost"
                        disabled={act.busy}
                        onClick={() => act.run(() => api.saveRecord(b.id, form)).then((r) => setSavedAt(r.updated_at))}
                      >
                        임시저장
                      </button>
                      <button
                        type="button"
                        className="btn"
                        disabled={act.busy || !started}
                        title={!started ? '상담 시작 후 제출할 수 있습니다' : ''}
                        onClick={() => doAction(() => api.submitRecord(b.id, form))}
                      >
                        제출하고 상담 완료
                      </button>
                    </div>
                  ))}
                {locked && <p className="hint">제출 후 수정 기간이 지나 고정된 기록입니다.</p>}
              </fieldset>
            )}
          </Card>

          {d.revisions.length > 0 && (
            <Card title={`수정 이력 ${d.revisions.length}건`}>
              <ul className="list">
                {d.revisions.map((r) => (
                  <li key={r.id} className="list-item">
                    <div className="grow">
                      <div>
                        <strong>{r.reason}</strong>
                      </div>
                      <div className="muted small">
                        {fmtDateTime(r.created_at)} · {r.editor_name} · {r.changed_fields.map((k) => FIELD_LABEL[k] ?? k).join(', ')}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
