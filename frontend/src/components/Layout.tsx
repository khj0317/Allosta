import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth';

const NAV = {
  CUSTOMER: [
    { to: '/my', label: '내 검사 결과', end: true },
    { to: '/my/book', label: '상담 예약' },
    { to: '/my/bookings', label: '예약 내역' },
    { to: '/my/notifications', label: '알림' },
  ],
  COUNSELOR: [
    { to: '/staff', label: '오늘의 상담', end: true },
    { to: '/staff/slots', label: '내 상담 일정' },
  ],
  ADMIN: [
    { to: '/admin', label: '운영 대시보드', end: true },
    { to: '/admin/bookings', label: '전체 예약' },
    { to: '/admin/slots', label: '상담사 일정 관리' },
  ],
} as const;

const ROLE_LABEL = { CUSTOMER: '고객', COUNSELOR: '상담사', ADMIN: '운영 관리자' };

export function Layout() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  if (!user) return null;
  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-inner">
          <NavLink to="/" className="brand" aria-label="Allosta Care 홈">
            <span className="brand-word">Allosta</span>
            <span className="brand-sep" aria-hidden="true" />
            <span className="brand-sub">결과 상담</span>
          </NavLink>
          <nav className="nav">
            {NAV[user.role].map((n) => (
              <NavLink key={n.to} to={n.to} end={'end' in n ? n.end : false} className="nav-link">
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="who">
            <span className="who-name">{user.name}</span>
            <span className="who-role">{ROLE_LABEL[user.role]}</span>
            <button
              className="link-btn"
              onClick={() => {
                logout();
                nav('/login');
              }}
            >
              로그아웃
            </button>
          </div>
        </div>
      </header>
      <main className="page">
        <Outlet />
      </main>
    </div>
  );
}
