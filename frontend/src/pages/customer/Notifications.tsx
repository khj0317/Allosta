import { Link } from 'react-router-dom';
import { api } from '../../api';
import { fmtDateTime } from '../../format';
import { NOTIFICATIONS_CHANGED } from '../../components/Layout';
import { Card, Empty, ErrorBox, Spinner, useAsync } from '../../components/ui';

export function Notifications() {
  const { data, error, reload: load } = useAsync(api.notifications);
  // 읽음 처리 후 목록과 상단 개수를 함께 갱신
  const reload = () => load().then(() => window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED)));
  const unread = data?.filter((n) => !n.read_at).length ?? 0;
  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">Notifications</p>
          <h1>알림</h1>
          <p className="sub">문자(알림톡)로 보내드린 내용을 여기서도 확인할 수 있어요.</p>
        </div>
        {unread > 0 && (
          <button className="btn btn-ghost btn-sm" onClick={() => api.readAllNotifications().then(reload)}>
            모두 읽음 ({unread})
          </button>
        )}
      </div>
      <ErrorBox error={error} />
      {!data ? (
        <Spinner />
      ) : (
        <Card>
          {data.length === 0 ? (
            <Empty>받은 알림이 없습니다.</Empty>
          ) : (
            <ul className="list">
              {data.map((n) => {
                const link = n.booking_id ? `/my/bookings/${n.booking_id}` : n.waitlist_id ? '/my/bookings' : null;
                return (
                  <li key={n.id} className={`list-item notif ${n.read_at ? '' : 'unread'}`} onClick={() => !n.read_at && api.readNotification(n.id).then(reload)}>
                    <div className="grow">
                      <strong>{n.title}</strong>
                      <p className="pre small">{n.body.replace(/https?:\/\/\S+/g, '').trim()}</p>
                      <div className="muted small">{n.sent_at && fmtDateTime(n.sent_at)}</div>
                    </div>
                    {link && <Link to={link} className="btn btn-ghost btn-sm">바로가기</Link>}
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      )}
    </>
  );
}
