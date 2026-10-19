import { useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { api, tokenStore } from '../api';
import { homeFor, useAuth } from '../auth';
import { ErrorBox, useAction } from '../components/ui';
import { AuthLayout } from './Login';

/** 비밀번호 변경. 운영자가 임시 비밀번호로 발급한 계정은 첫 로그인 직후 이 화면으로 온다. */
export function ChangePassword() {
  const { user, loading, setCurrentUser, logout } = useAuth();
  const nav = useNavigate();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const act = useAction();
  if (loading) return null; // 새로고침 직후 로그인 정보를 불러오는 중에 로그인 화면으로 튕기지 않게
  if (!user) return <Navigate to="/login" replace />;

  const mismatch = confirm.length > 0 && next !== confirm;
  const forced = user.must_change_password;

  return (
    <AuthLayout
      title="비밀번호 변경"
      description={forced ? '임시 비밀번호로 로그인했습니다. 사용할 비밀번호를 새로 정해주세요.' : '새 비밀번호를 입력해주세요.'}
      footer={
        <button
          type="button"
          className="link-btn"
          onClick={() => {
            logout();
            nav('/login');
          }}
        >
          로그아웃
        </button>
      }
    >
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          if (mismatch) return;
          act.run(() => api.changePassword(current, next)).then((res) => {
            tokenStore.set(res.access_token); // 이전 토큰은 서버에서 무효가 되므로 새 토큰으로 교체
            setCurrentUser(res.user);
            nav(homeFor(res.user), { replace: true });
          });
        }}
      >
        <label>
          {forced ? '임시 비밀번호' : '현재 비밀번호'}
          <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} required autoComplete="current-password" />
        </label>
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
        <button className="btn btn-block" disabled={act.busy || mismatch}>변경하고 시작하기</button>
      </form>
    </AuthLayout>
  );
}
