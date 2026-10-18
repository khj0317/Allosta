import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, type FamilyCode, type Relation, type Subject } from '../../api';
import { BirthDateInput, PhoneInput } from '../../components/inputs';
import { fmtDate, parseLocal, RELATION } from '../../format';
import { Card, ErrorBox, Modal, Spinner, useAction, useAsync } from '../../components/ui';

export function MyResults() {
  const { data: subjects, error, loading, reload } = useAsync(api.subjects);
  const welcome = useSearchParams()[0].get('welcome');
  const [adding, setAdding] = useState(false);
  const [verifying, setVerifying] = useState<{ subject: Subject; demoCode: string | null } | null>(null);
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
          const pending = s.relation !== 'SELF' && !s.consent_at;
          return (
            <Card
              key={s.id}
              title={
                <>
                  {s.name} <span className="tag">{RELATION[s.relation]}</span>
                  {pending && <span className="badge badge-warn">인증 대기</span>}
                </>
              }
              actions={
                pending ? (
                  s.results.length === 0 && (
                    <button
                      className="link-btn"
                      disabled={remove.busy}
                      onClick={() => confirm(`${s.name}님을 가족 목록에서 삭제할까요?`) && remove.run(() => api.removeFamily(s.id)).then(reload)}
                    >
                      삭제
                    </button>
                  )
                ) : (
                  <button className="btn btn-ghost btn-sm" onClick={() => setClaimFor(s)}>
                    키트 코드로 결과 연결
                  </button>
                )
              }
            >
              {pending ? (
                <div className="alert alert-warn">
                  <div>
                    <strong>{s.name}님 본인의 휴대폰 인증이 필요합니다.</strong> {s.phone_masked}로 보낸 인증번호를 {s.name}님께 받아
                    입력하면 가족 등록이 완료되고, 그때부터 결과 연결과 상담 예약을 할 수 있어요.
                  </div>
                  <button className="btn btn-sm" onClick={() => setVerifying({ subject: s, demoCode: null })}>
                    인증번호 입력
                  </button>
                </div>
              ) : s.results.length === 0 ? (
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
          onSent={(r) => {
            setAdding(false);
            setVerifying({ subject: r.subject, demoCode: r.demo_code });
            reload();
          }}
        />
      )}
      {verifying && (
        <VerifyModal
          subject={verifying.subject}
          initialDemoCode={verifying.demoCode}
          onClose={() => setVerifying(null)}
          onDone={() => {
            setVerifying(null);
            reload();
          }}
        />
      )}
      {claimFor && <ClaimModal subject={claimFor} onClose={() => setClaimFor(null)} onDone={() => { setClaimFor(null); reload(); }} />}
    </>
  );
}

/** 1단계: 가족 정보 입력 → 가족 본인 휴대폰으로 인증번호 발송 */
function AddFamilyModal({ onClose, onSent }: { onClose: () => void; onSent: (r: FamilyCode) => void }) {
  const [name, setName] = useState('');
  const [birth, setBirth] = useState('');
  const [phone, setPhone] = useState('');
  const [relation, setRelation] = useState<Relation>('PARENT');
  const act = useAction();
  return (
    <Modal title="가족 추가" onClose={onClose}>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          act.run(() => api.addFamily({ name, relation, birth_date: birth, phone })).then(onSent);
        }}
      >
        <p className="muted small">
          가족의 검사 결과는 민감한 건강정보라서, <strong>가족 본인의 휴대폰</strong>으로 인증번호를 보내 동의를 확인합니다. 결과지는 키트
          접수 때 등록된 이름·생년월일과 일치해야 연결됩니다.
        </p>
        <label>
          관계
          <select value={relation} onChange={(e) => setRelation(e.target.value as Relation)}>
            {(['SPOUSE', 'PARENT', 'CHILD', 'SIBLING', 'OTHER'] as Relation[]).map((r) => (
              <option key={r} value={r}>{RELATION[r]}</option>
            ))}
          </select>
        </label>
        <label>
          이름
          <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={50} placeholder="키트에 등록한 이름 그대로" />
        </label>
        <label>
          생년월일
          <BirthDateInput value={birth} onChange={setBirth} required />
        </label>
        <label>
          가족 본인 휴대폰 번호
          <PhoneInput value={phone} onChange={setPhone} required />
          <span className="hint">이 번호로 인증번호가 발송됩니다. 내 번호는 입력할 수 없어요.</span>
        </label>
        <ErrorBox error={act.error} />
        <button className="btn btn-block" disabled={act.busy || !birth}>인증번호 보내기</button>
      </form>
    </Modal>
  );
}

/** 2단계: 가족에게 받은 6자리 인증번호 입력 */
function VerifyModal({
  subject,
  initialDemoCode,
  onClose,
  onDone,
}: {
  subject: Subject;
  initialDemoCode: string | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const [code, setCode] = useState('');
  const [demoCode, setDemoCode] = useState(initialDemoCode);
  const [expiresAt, setExpiresAt] = useState(subject.verify_expires_at);
  const [left, setLeft] = useState(0);
  const act = useAction();
  const resend = useAction();

  useEffect(() => {
    const tick = () => setLeft(expiresAt ? Math.max(0, Math.round((parseLocal(expiresAt).getTime() - Date.now()) / 1000)) : 0);
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [expiresAt]);

  const mmss = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;

  return (
    <Modal title={`${subject.name}님 인증`} onClose={onClose}>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          act.run(() => api.verifyFamily(subject.id, code)).then(onDone);
        }}
      >
        <p className="muted small">
          {subject.phone_masked}로 보낸 6자리 인증번호를 {subject.name}님께 받아 입력해주세요.
        </p>
        {demoCode && (
          <div className="alert alert-info">
            <div>
              데모 환경이라 실제 문자는 발송되지 않습니다. 인증번호: <strong className="tabular">{demoCode}</strong>
            </div>
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
          />
          <span className="hint">{left > 0 ? `남은 시간 ${mmss}` : '인증번호가 만료되었거나 아직 받지 않았어요. 다시 받아주세요.'}</span>
        </label>
        <ErrorBox error={act.error || resend.error} />
        <button className="btn btn-block" disabled={act.busy || code.length !== 6 || left === 0}>확인</button>
        <button
          type="button"
          className="link-btn"
          disabled={resend.busy}
          onClick={() =>
            resend.run(() => api.resendFamilyCode(subject.id)).then((r) => {
              setDemoCode(r.demo_code);
              setExpiresAt(r.subject.verify_expires_at);
              setCode('');
            })
          }
        >
          {expiresAt ? '인증번호 다시 받기' : '인증번호 받기'}
        </button>
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
        <p className="muted small">키트 상자 또는 결과 안내 문자에 있는 코드를 입력하세요. 키트 접수 때 등록한 이름·생년월일과 일치해야 연결됩니다.</p>
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
