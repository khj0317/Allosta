import { useState } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
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
        <label>
          휴대폰 번호
          <PhoneInput value={form.phone} onChange={(phone) => setForm({ ...form, phone })} required />
        </label>
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
        <button className="btn btn-block" disabled={act.busy || !consent || mismatch || !form.birth_date}>가입하고 시작하기</button>
      </form>
    </AuthLayout>
  );
}
