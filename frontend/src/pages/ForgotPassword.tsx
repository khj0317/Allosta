import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api';
import { PhoneInput } from '../components/inputs';
import { ErrorBox, useAction, useAsync } from '../components/ui';
import { AuthLayout } from './Login';

/**
 * 비밀번호 찾기: 이메일 + 가입한 휴대폰 → 인증번호 → 새 비밀번호.
 * 이메일·번호가 맞지 않아도 화면은 똑같이 진행된다(가입 여부를 알려주지 않음). 문자는 실제 계정 번호로만 간다.
 */
export function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [sent, setSent] = useState(false);
  const [demoCode, setDemoCode] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [token, setToken] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [done, setDone] = useState(false);
  const [deadline, setDeadline] = useState(0);
  const [left, setLeft] = useState(0);
  const act = useAction();
  const { data: meta } = useAsync(api.meta);
  const { data: hints } = useAsync(() => (meta?.demo_mode ? api.demoHints() : Promise.resolve(null)), [meta?.demo_mode]);

  useEffect(() => {
    if (!deadline) return;
    const tick = () => setLeft(Math.max(0, Math.round((deadline - Date.now()) / 1000)));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [deadline]);

  const mismatch = confirm.length > 0 && next !== confirm;

  return (
    <AuthLayout
      title="비밀번호 찾기"
      description="가입할 때 인증한 휴대폰으로 본인 확인 후 새 비밀번호를 정합니다."
      footer={<Link to="/login">로그인으로 돌아가기</Link>}
    >
      {done ? (
        <div className="form">
          <div className="alert alert-ok">
            <div>
              <strong>비밀번호를 바꿨습니다.</strong> 새 비밀번호로 로그인해주세요. 로그인 잠금도 함께 풀렸어요.
            </div>
          </div>
          <Link className="btn btn-block" to="/login">로그인</Link>
        </div>
      ) : token ? (
        <form
          className="form"
          onSubmit={(e) => {
            e.preventDefault();
            if (mismatch) return;
            act.run(() => api.resetPassword(email, phone, token, next)).then(() => setDone(true));
          }}
        >
          <div className="alert alert-ok">
            <div>휴대폰 인증이 완료되었습니다.</div>
          </div>
          <label>
            새 비밀번호
            <input type="password" value={next} onChange={(e) => setNext(e.target.value)} required minLength={8} autoComplete="new-password" />
            <span className="hint">영문과 숫자를 포함해 8자 이상</span>
          </label>
          <label>
            새 비밀번호 확인
            <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required autoComplete="new-password" />
            {mismatch && <span className="hint text-danger">비밀번호가 일치하지 않습니다.</span>}
          </label>
          <ErrorBox error={act.error} />
          <button className="btn btn-block" disabled={act.busy || mismatch}>비밀번호 변경</button>
        </form>
      ) : (
        <form
          className="form"
          onSubmit={(e) => {
            e.preventDefault();
            if (!sent) {
              act.run(() => api.resetSend(email, phone)).then((r) => {
                setSent(true);
                setDemoCode(r.demo_code);
                setDeadline(Date.now() + 10 * 60 * 1000);
              });
            } else {
              act.run(() => api.resetVerify(email, phone, code)).then((r) => setToken(r.reset_token));
            }
          }}
        >
          {hints?.reset && !sent && (
            <div className="alert alert-info">
              <div>
                데모 환경이라 실제 문자는 발송되지 않고, 인증번호를 화면에 보여드려요. 비밀번호 찾기 시연용 계정({hints.reset.email} ·{' '}
                {hints.reset.phone})으로 시연할 수 있어요.
              </div>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  setEmail(hints.reset!.email);
                  setPhone(hints.reset!.phone);
                }}
              >
                정보 채우기
              </button>
            </div>
          )}
          <label>
            이메일
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required disabled={sent} autoComplete="username" />
          </label>
          <label>
            가입한 휴대폰 번호
            <PhoneInput value={phone} onChange={setPhone} required disabled={sent} />
          </label>
          {sent && meta?.demo_mode && (
            demoCode ? (
              <div className="alert alert-info">
                <div>
                  데모 환경 인증번호: <strong className="tabular">{demoCode}</strong>
                </div>
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setCode(demoCode)}>
                  입력
                </button>
              </div>
            ) : (
              <div className="alert alert-warn">
                <div>
                  데모 환경 안내: 입력한 이메일·휴대폰과 일치하는 계정이 없어 인증번호를 보내지 않았어요. 운영 환경에서는 가입 여부를 알 수
                  없도록 이 안내 없이 똑같이 진행됩니다.
                </div>
              </div>
            )
          )}
          {sent && (
            <label>
              인증번호
              <input
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                placeholder="6자리"
                required
              />
              <span className="hint">
                정보가 맞으면 가입한 휴대폰으로 인증번호를 보냈어요.{' '}
                {left > 0 ? `남은 시간 ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}` : '시간이 지났어요. 처음부터 다시 해주세요.'}
              </span>
            </label>
          )}
          <ErrorBox error={act.error} />
          <button className="btn btn-block" disabled={act.busy || (sent && code.length !== 6)}>
            {sent ? '확인' : '인증번호 받기'}
          </button>
          {sent && (
            <button
              type="button"
              className="link-btn"
              onClick={() => {
                setSent(false);
                setCode('');
                setDemoCode(null);
              }}
            >
              이메일·번호 다시 입력
            </button>
          )}
        </form>
      )}
    </AuthLayout>
  );
}
