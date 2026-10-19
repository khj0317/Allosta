import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useAuth } from '../auth';

/** 알림을 읽었을 때 상단 개수를 바로 갱신하도록 보내는 이벤트 */
export const NOTIFICATIONS_CHANGED = 'allostar:notifications-changed';

/** 고객 상단 메뉴 '알림' 옆 안 읽은 개수. 화면 이동·알림 읽음·1분마다 갱신. */
function useUnreadCount(enabled: boolean) {
  const [count, setCount] = useState(0);
  const location = useLocation();
  useEffect(() => {
    if (!enabled) return;
    const load = () => api.unreadCount().then((r) => setCount(r.count)).catch(() => {});
    load();
    const t = setInterval(load, 60_000);
    window.addEventListener(NOTIFICATIONS_CHANGED, load);
    return () => {
      clearInterval(t);
      window.removeEventListener(NOTIFICATIONS_CHANGED, load);
    };
  }, [enabled, location.pathname]);
  return count;
}

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
    { to: '/admin/counselors', label: '상담사 계정' },
  ],
} as const;

const ROLE_LABEL = { CUSTOMER: '고객', COUNSELOR: '상담사', ADMIN: '운영 관리자' };

export function Layout() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const unread = useUnreadCount(user?.role === 'CUSTOMER');
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
                {n.to === '/my/notifications' && unread > 0 && (
                  <span className="nav-count" aria-label={`안 읽은 알림 ${unread}개`}>{unread > 99 ? '99+' : unread}</span>
                )}
              </NavLink>
            ))}
          </nav>
          <div className="who">
            {user.role === 'CUSTOMER' ? (
              <NavLink to="/my/account" className="who-name who-link" title="내 정보">
                {user.name}
              </NavLink>
            ) : (
              <span className="who-name">{user.name}</span>
            )}
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
