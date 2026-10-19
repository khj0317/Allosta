import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, type FamilyInput, type Relation, type Subject } from '../../api';
import { BirthDateInput, PhoneInput } from '../../components/inputs';
import { fmtDate, parseLocal, RELATION } from '../../format';
import { Card, ErrorBox, Modal, Spinner, useAction, useAsync } from '../../components/ui';

export function MyResults() {
  const { data: subjects, error, loading, reload } = useAsync(api.subjects);
  const welcome = useSearchParams()[0].get('welcome');
  const [adding, setAdding] = useState(false);
  const [claimFor, setClaimFor] = useState<Subject | null>(null);
  const remove = useAction();

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">My Results</p>
          <h1>내 검사 결과</h1>
          <p className="sub">본인과 가족의 결과지를 확인하고, 궁금한 결과에 대해 전문 상담사와 1:1 전화 상담을 예약하세요.</p>
        </div>
        <button className="btn" onClick={() => setAdding(true)}>+ 가족 추가</button>
      </div>
      {welcome && subjects?.every((s) => s.results.length === 0) && (
        <div className="alert alert-info">
          <div>
            <strong>가입을 환영합니다.</strong> 먼저 검사 키트의 코드를 입력해 결과지를 연결해주세요. 결과를 확인한 뒤 바로 상담을 예약할 수 있어요.
          </div>
        </div>
      )}
      <ErrorBox error={error || remove.error} />
      {loading && !subjects && <Spinner />}
      <div className="stack">
        {subjects?.map((s) => {
          return (
            <Card
              key={s.id}
              title={
                <>
                  {s.name} <span className="tag">{RELATION[s.relation]}</span>
                </>
              }
              actions={
                <>
                  {s.relation !== 'SELF' && s.results.length === 0 && (
                    <button
                      className="link-btn"
                      disabled={remove.busy}
                      onClick={() => confirm(`${s.name}님을 가족 목록에서 삭제할까요?`) && remove.run(() => api.removeFamily(s.id)).then(reload)}
                    >
                      삭제
                    </button>
                  )}
                  <button className="btn btn-ghost btn-sm" onClick={() => setClaimFor(s)}>
                    키트 코드로 결과 연결
                  </button>
                </>
              }
            >
              {s.results.length === 0 ? (
                <div className="empty">
                  <p>연결된 결과지가 없습니다.</p>
                  <button className="btn btn-ghost btn-sm" onClick={() => setClaimFor(s)}>키트 코드 입력하기</button>
                </div>
              ) : (
                <ul className="result-list">
                  {s.results.map((r) => (
                    <li key={r.id} className="result-item">
                      <div>
                        <div className="result-title">{r.service_label}</div>
                        <div className="muted small">
                          {r.kit_code} · {fmtDate(r.reported_at)} 발행
                          {r.abnormal_count > 0 && (
                            <>
                              {' '}· <span className="text-warn">확인 필요 지표 {r.abnormal_count}개</span>
                            </>
                          )}
                        </div>
                      </div>
                      <div className="row-actions">
                        <Link className="btn btn-ghost btn-sm" to={`/my/results/${r.id}`}>결과 보기</Link>
                        <Link className="btn btn-sm" to={`/my/book?subject=${s.id}&result=${r.id}`}>상담 예약</Link>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          );
        })}
      </div>
      {adding && (
        <AddFamilyModal
          onClose={() => setAdding(false)}
          onDone={(added) => {
            setAdding(false);
            reload();
            setClaimFor(added); // 등록 직후 바로 결과지 연결로 이어간다
          }}
        />
      )}
      {claimFor && <ClaimModal subject={claimFor} onClose={() => setClaimFor(null)} onDone={() => { setClaimFor(null); reload(); }} />}
    </>
  );
}

/**
 * 가족 추가: 정보 입력 → 가족 본인 휴대폰으로 인증번호 발송 → 인증번호 확인 → 그때 등록.
 * 인증을 마치지 않으면 가족 목록에 아무것도 생기지 않는다.
 */
function AddFamilyModal({ onClose, onDone }: { onClose: () => void; onDone: (s: Subject) => void }) {
  const [form, setForm] = useState<FamilyInput>({ name: '', relation: 'PARENT', birth_date: '', phone: '' });
  const [formKey, setFormKey] = useState(0); // 데모 정보 채우기 시 생년월일 입력칸을 새로 그린다
  const [sent, setSent] = useState(false);
  const [demoCode, setDemoCode] = useState<string | null>(null);
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [left, setLeft] = useState(0);
  const [code, setCode] = useState('');
  const act = useAction();
  const { data: meta } = useAsync(api.meta);
  const { data: hints } = useAsync(() => (meta?.demo_mode ? api.demoHints() : Promise.resolve(null)), [meta?.demo_mode]);

  useEffect(() => {
    const tick = () => setLeft(expiresAt ? Math.max(0, Math.round((parseLocal(expiresAt).getTime() - Date.now()) / 1000)) : 0);
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [expiresAt]);

  const set = <K extends keyof FamilyInput>(k: K, v: FamilyInput[K]) => setForm((f) => ({ ...f, [k]: v }));
  const sendCode = () =>
    act.run(() => api.sendFamilyCode(form)).then((r) => {
      setSent(true);
      setDemoCode(r.demo_code);
      setExpiresAt(r.expires_at);
      setCode('');
    });
  const mmss = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;

  return (
    <Modal title="가족 추가" onClose={onClose}>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          if (!sent) sendCode();
          else act.run(() => api.addFamily({ ...form, code })).then(onDone);
        }}
      >
        <p className="muted small">
          가족의 검사 결과는 민감한 건강정보라서, <strong>가족 본인의 휴대폰</strong>으로 받은 인증번호를 확인해야 가족으로 등록됩니다.
          결과지는 키트 접수 때 등록된 이름·생년월일·휴대폰과 일치해야 연결됩니다.
        </p>
        {hints?.family && !sent && (
          <div className="alert alert-info">
            <div>
              데모 환경: 키트 <strong>AL-DEMO-00</strong>으로 접수된 가상의 아버지({hints.family.name}) 정보로 시연해 볼 수 있어요.
            </div>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => {
                setForm(hints.family);
                setFormKey((k) => k + 1);
              }}
            >
              정보 채우기
            </button>
          </div>
        )}
        <label>
          관계
          <select value={form.relation} disabled={sent} onChange={(e) => set('relation', e.target.value as Relation)}>
            {(['SPOUSE', 'PARENT', 'CHILD', 'SIBLING', 'OTHER'] as Relation[]).map((r) => (
              <option key={r} value={r}>{RELATION[r]}</option>
            ))}
          </select>
        </label>
        <label>
          이름
          <input
            value={form.name}
            disabled={sent}
            onChange={(e) => set('name', e.target.value)}
            required
            maxLength={50}
            placeholder="키트에 등록한 이름 그대로"
          />
        </label>
        <label>
          생년월일
          <BirthDateInput key={formKey} value={form.birth_date} disabled={sent} onChange={(v) => set('birth_date', v)} required />
        </label>
        <label>
          가족 본인 휴대폰 번호
          <PhoneInput value={form.phone} disabled={sent} onChange={(v) => set('phone', v)} required />
          {!sent && <span className="hint">이 번호로 인증번호가 발송됩니다. 내 번호는 입력할 수 없어요.</span>}
        </label>
        {sent && (
          <>
            {demoCode && (
              <div className="alert alert-info">
                <div>
                  데모 환경이라 실제 문자는 발송되지 않습니다. 인증번호: <strong className="tabular">{demoCode}</strong>
                </div>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setCode(demoCode)}>
                  입력
                </button>
              </div>
            )}
            <label>
              인증번호
              <input
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                placeholder="000000"
                className="code-input"
                required
                autoFocus
              />
              <span className="hint">
                {form.name}님께 받은 6자리를 입력하세요. {left > 0 ? `남은 시간 ${mmss}` : '인증번호가 만료되었어요. 다시 받아주세요.'}
              </span>
            </label>
          </>
        )}
        <ErrorBox error={act.error} />
        <button className="btn btn-block" disabled={act.busy || !form.birth_date || (sent && (code.length !== 6 || left === 0))}>
          {sent ? '확인하고 가족 등록' : '인증번호 보내기'}
        </button>
        {sent && (
          <div className="inline-links">
            <button type="button" className="link-btn" disabled={act.busy} onClick={sendCode}>
              인증번호 다시 받기
            </button>
            <button
              type="button"
              className="link-btn"
              onClick={() => {
                setSent(false);
                setDemoCode(null);
                setExpiresAt(null);
                setCode('');
              }}
            >
              정보 수정
            </button>
          </div>
        )}
      </form>
    </Modal>
  );
}

function ClaimModal({ subject, onClose, onDone }: { subject: Subject; onClose: () => void; onDone: () => void }) {
  const [code, setCode] = useState('');
  const act = useAction();
  const { data: meta } = useAsync(api.meta);
  const { data: demoKits } = useAsync(
    () => (meta?.demo_mode ? api.demoKits(subject.id) : Promise.resolve([])),
    [meta?.demo_mode, subject.id],
  );
  return (
    <Modal title={`${subject.name}님 결과 연결`} onClose={onClose}>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          act.run(() => api.claimKit(subject.id, code)).then(onDone);
        }}
      >
        <p className="muted small">키트 상자 또는 결과 안내 문자에 있는 코드를 입력하세요. 키트 접수 때 등록한 이름·생년월일·휴대폰과 일치해야 연결됩니다.</p>
        <label>
          키트 코드
          <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="AL-XX-2026-0000" required />
        </label>
        {demoKits && demoKits.length > 0 && (
          <div>
            <div className="label">데모용 키트 코드 (눌러서 입력)</div>
            <div className="chips">
              {demoKits.slice(0, 6).map((k) => (
                <button type="button" key={k.kit_code} className={`chip chip-sm ${code === k.kit_code ? 'on' : ''}`} onClick={() => setCode(k.kit_code)}>
                  {k.kit_code} · {k.service_label}
                  {k.registered && ` · ${subject.name}님 명의`}
                </button>
              ))}
            </div>
          </div>
        )}
        <ErrorBox error={act.error} />
        <button className="btn" disabled={act.busy}>연결</button>
      </form>
    </Modal>
  );
}
