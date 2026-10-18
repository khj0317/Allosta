import { useEffect, useState } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { homeFor, useAuth } from '../auth';
import { BirthDateInput, PhoneInput } from '../components/inputs';
import { ErrorBox, useAction } from '../components/ui';
import { AuthLayout } from './Login';

/** 고객 회원가입. 상담사·관리자 계정은 운영자가 발급하므로 이 화면에서 만들 수 없다. */
export function Signup() {
  const { user, signup } = useAuth();
  const nav = useNavigate();
  const [form, setForm] = useState({ name: '', email: '', phone: '', birth_date: '', password: '', confirm: '' });
  const [consent, setConsent] = useState(false);
  const [phoneToken, setPhoneToken] = useState('');
  const act = useAction();
  if (user) return <Navigate to={homeFor(user)} replace />;

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });
  const mismatch = form.confirm.length > 0 && form.password !== form.confirm;

  return (
    <AuthLayout
      title="회원가입"
      description="키트 코드만 있으면 바로 결과를 확인할 수 있어요."
      footer={
        <>
          이미 계정이 있으신가요? <Link to="/login">로그인</Link>
        </>
      }
    >
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          if (mismatch) return;
          act
            .run(() =>
              signup({
                name: form.name,
                email: form.email,
                phone: form.phone,
                birth_date: form.birth_date,
                password: form.password,
                phone_token: phoneToken,
                privacy_consent: consent,
              }),
            )
            .then(() => nav('/my?welcome=1'));
        }}
      >
        <label>
          이름
          <input value={form.name} onChange={set('name')} required maxLength={50} autoComplete="name" />
        </label>
        <label>
          이메일
          <input type="email" value={form.email} onChange={set('email')} required autoComplete="email" />
        </label>
        <PhoneVerifyField
          phone={form.phone}
          onPhoneChange={(phone) => {
            setForm({ ...form, phone });
            setPhoneToken('');
          }}
          verified={!!phoneToken}
          onVerified={setPhoneToken}
        />
        <label>
          생년월일
          <BirthDateInput value={form.birth_date} onChange={(birth_date) => setForm({ ...form, birth_date })} required />
        </label>
        <label>
          비밀번호
          <input type="password" value={form.password} onChange={set('password')} required minLength={8} autoComplete="new-password" />
          <span className="hint">영문과 숫자를 포함해 8자 이상</span>
        </label>
        <label>
          비밀번호 확인
          <input type="password" value={form.confirm} onChange={set('confirm')} required autoComplete="new-password" />
          {mismatch && <span className="hint text-danger">비밀번호가 일치하지 않습니다.</span>}
        </label>
        <label className="check consent">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <span>
            <strong>[필수] 건강정보 수집·이용 동의</strong>
            <br />
            <span className="muted small">검사 결과와 상담 내용은 상담 제공 목적으로만 사용되며, 배정된 상담사만 열람합니다.</span>
          </span>
        </label>
        <ErrorBox error={act.error} />
        <button className="btn btn-block" disabled={act.busy || !consent || mismatch || !form.birth_date || !phoneToken}>가입하고 시작하기</button>
      </form>
    </AuthLayout>
  );
}

/**
 * 휴대폰 본인 확인: 번호 → 인증번호 받기 → 6자리 입력 → 확인.
 * 이름·생년월일은 누구나 입력할 수 있으므로, 실제 휴대폰을 가진 사람만 그 번호로 가입하게 한다.
 */
function PhoneVerifyField({
  phone,
  onPhoneChange,
  verified,
  onVerified,
}: {
  phone: string;
  onPhoneChange: (p: string) => void;
  verified: boolean;
  onVerified: (token: string) => void;
}) {
  const [sent, setSent] = useState(false);
  const [demoCode, setDemoCode] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [deadline, setDeadline] = useState(0);
  const [left, setLeft] = useState(0);
  const send = useAction();
  const check = useAction();

  useEffect(() => {
    if (!deadline) return;
    const tick = () => setLeft(Math.max(0, Math.round((deadline - Date.now()) / 1000)));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [deadline]);

  const complete = phone.replace(/\D/g, '').length >= 10;

  return (
    <div className="form-group">
      <label>
        휴대폰 번호
        <div className="input-row">
          <PhoneInput value={phone} onChange={onPhoneChange} required />
          {verified ? (
            <button type="button" className="btn btn-ghost" onClick={() => { onPhoneChange(''); setSent(false); setCode(''); }}>
              번호 변경
            </button>
          ) : (
            <button
              type="button"
              className="btn btn-ghost"
              disabled={!complete || send.busy}
              onClick={() =>
                send.run(() => api.sendPhoneCode(phone)).then((r) => {
                  setSent(true);
                  setDemoCode(r.demo_code);
                  setCode('');
                  setDeadline(Date.now() + 10 * 60 * 1000);
                })
              }
            >
              {sent ? '다시 받기' : '인증번호 받기'}
            </button>
          )}
        </div>
        {verified && <span className="hint text-ok">휴대폰 인증이 완료되었습니다.</span>}
      </label>
      {sent && !verified && (
        <label>
          인증번호
          <div className="input-row">
            <input
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              placeholder="6자리"
            />
            <button
              type="button"
              className="btn btn-ghost"
              disabled={code.length !== 6 || check.busy || left === 0}
              onClick={() => check.run(() => api.verifyPhoneCode(phone, code)).then((r) => onVerified(r.phone_token))}
            >
              확인
            </button>
          </div>
          <span className="hint">
            {left > 0 ? `남은 시간 ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}` : '시간이 지났어요. 다시 받아주세요.'}
            {demoCode && ` · 데모 환경 인증번호 ${demoCode}`}
          </span>
        </label>
      )}
      <ErrorBox error={send.error || check.error} />
    </div>
  );
}
