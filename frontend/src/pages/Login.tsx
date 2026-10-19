import { useState, type ReactNode } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { api, type Role, type User } from '../api';
import { homeFor, useAuth } from '../auth';
import { ErrorBox, useAction, useAsync } from '../components/ui';

const DEMO: { role: Role; label: string; desc: string }[] = [
  { role: 'CUSTOMER', label: '고객으로 둘러보기', desc: '홍길동 · 결과 조회, 예약, 대기, 가족 상담' },
  { role: 'COUNSELOR', label: '상담사로 둘러보기', desc: '이몽룡 · 오늘의 상담, 상담 기록, 일정' },
  { role: 'ADMIN', label: '운영 관리자로 둘러보기', desc: '대시보드, 전체 예약, 상담사 일정' },
];

const STEPS = [
  { no: '01', title: '결과지 확인', desc: '지표가 참고범위에서 어디쯤인지 먼저 살펴봅니다.' },
  { no: '02', title: '원하는 시간 예약', desc: '마감된 날은 대기를 걸어두면 자리가 날 때 알려드려요.' },
  { no: '03', title: '전문가 1:1 전화', desc: '상담 후 요약과 추천 사항을 다시 볼 수 있습니다.' },
];

/**
 * 로그인·회원가입 공용 레이아웃: 왼쪽 서비스 소개(고정), 오른쪽 폼.
 * 두 화면의 제목·설명·폼·하단 링크 위치를 같은 틀로 맞춘다.
 */
export function AuthLayout({
  title,
  description,
  footer,
  extra,
  children,
}: {
  title: string;
  description: string;
  /** 폼 바로 아래 계정 전환 링크(로그인 ↔ 회원가입) */
  footer: ReactNode;
  /** 링크 아래 부가 영역(데모 계정 등) */
  extra?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="login">
      <section className="login-brand">
        <div className="brand big">
          <span className="brand-word">Allosta</span>
          <span className="brand-sep" aria-hidden="true" />
          <span className="brand-sub">결과 상담</span>
        </div>
        <div className="login-brand-body">
          <p className="eyebrow">Consultation</p>
          <h2>
            결과지의 숫자가
            <br />
            궁금해졌다면.
          </h2>
          <p>대사체 분석 결과를 받은 뒤, 전문 상담사와 30분 전화로 내 상태와 관리 방법을 이야기해 보세요.</p>
          <ol className="login-steps">
            {STEPS.map((s) => (
              <li key={s.no}>
                <span>{s.no}</span>
                <div>
                  <strong>{s.title}</strong>
                  <em>{s.desc}</em>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>
      <section className="login-panel">
        <div className="login-card">
          <header className="auth-head">
            <h1>{title}</h1>
            <p>{description}</p>
          </header>
          {children}
          <p className="auth-switch">{footer}</p>
          {extra}
        </div>
      </section>
    </div>
  );
}

export function Login() {
  const { user, login, switchDemoRole } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const { data: meta } = useAsync(api.meta);
  const act = useAction();
  if (user) return <Navigate to={homeFor(user)} replace />;

  const enter = (p: Promise<User>) => act.run(() => p).then((u) => nav(homeFor(u)));

  return (
    <AuthLayout
      title="로그인"
      description="검사 결과 확인과 상담 예약을 이어서 진행하세요."
      footer={
        <>
          처음이신가요? <Link to="/signup">회원가입</Link>
          <span className="sep" aria-hidden="true">·</span>
          <Link to="/forgot">비밀번호 찾기</Link>
        </>
      }
      extra={
        meta?.demo_mode && (
            <div className="demo">
              <div className="label">회원가입 없이 둘러보기</div>
              {DEMO.map((d) => (
                <button key={d.role} className="demo-btn" disabled={act.busy} onClick={() => enter(switchDemoRole(d.role))}>
                  <strong>{d.label}</strong>
                  <span>{d.desc}</span>
                </button>
              ))}
            </div>
        )
      }
    >
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          enter(login(email, password));
        }}
      >
        <label>
          이메일
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="username" />
        </label>
        <label>
          비밀번호
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" />
        </label>
        <ErrorBox error={act.error} />
        <button className="btn btn-block" disabled={act.busy}>로그인</button>
      </form>
    </AuthLayout>
  );
}
