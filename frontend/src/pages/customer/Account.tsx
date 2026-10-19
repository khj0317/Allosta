import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../../api';
import { useAuth } from '../../auth';
import { fmtDateTime } from '../../format';
import { Card, ErrorBox, Spinner, useAction, useAsync } from '../../components/ui';

/** 내 정보 + 회원 탈퇴. 탈퇴 전에 무엇이 취소·삭제되고 무엇이 익명으로 남는지 먼저 보여준다. */
export function Account() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const { data: preview, error, loading } = useAsync(api.withdrawalPreview);
  const [password, setPassword] = useState('');
  const [agree, setAgree] = useState(false);
  const act = useAction();
  if (!user) return null;

  const blocked = preview?.blocked_reason ?? null;

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">Account</p>
          <h1>내 정보</h1>
        </div>
      </div>
      <div className="stack">
        <Card title="계정" actions={<Link className="btn btn-ghost btn-sm" to="/password">비밀번호 변경</Link>}>
          <dl className="kv">
            <dt>이름</dt>
            <dd>{user.name}</dd>
            <dt>이메일</dt>
            <dd>{user.email}</dd>
            <dt>휴대폰</dt>
            <dd>{user.phone}</dd>
          </dl>
        </Card>

        <Card title="회원 탈퇴">
          <ErrorBox error={error} />
          {loading && !preview && <Spinner />}
          {preview && (
            <>
              <ul className="withdraw-impact">
                <li>
                  예정된 상담 <strong>{preview.upcoming_bookings}건</strong>은 취소되고, 비워진 시간은 대기 중인 다른 고객에게 안내됩니다.
                </li>
                <li>
                  대기 신청 <strong>{preview.active_waitlists}건</strong>이 취소됩니다.
                </li>
                <li>
                  결과지 <strong>{preview.results}개</strong>의 검사 수치와 가족 <strong>{preview.family_members}명</strong>의 정보가 삭제됩니다.
                </li>
              </ul>
              <div className="withdraw-grid">
                <div>
                  <div className="label">바로 삭제돼요</div>
                  <p className="small">
                    이름·이메일·휴대폰·생년월일(본인·가족), 결과지 지표 수치와 코멘트, 상담 기록 내용, 사전 질문, 알림함, 인증 기록
                  </p>
                </div>
                <div>
                  <div className="label">누구인지 알 수 없게 남아요</div>
                  <p className="small">
                    상담 일시·상태(통계용), 주문 {preview.orders_kept}건의 제품·금액(전자상거래법에 따라 5년 보관). 이름·연락처와는 연결되지
                    않습니다.
                  </p>
                </div>
              </div>

              {blocked ? (
                <div className="alert alert-warn">
                  <div>
                    {blocked}
                    {preview.imminent_bookings.length > 0 && (
                      <ul className="small" style={{ margin: '8px 0 0', paddingLeft: 18 }}>
                        {preview.imminent_bookings.map((b) => (
                          <li key={b.id}>
                            {fmtDateTime(b.start_at)} · {b.counselor_name} 상담사
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>
              ) : (
                <form
                  className="form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (!confirm('정말 탈퇴할까요? 삭제된 정보는 되돌릴 수 없습니다.')) return;
                    act.run(() => api.withdraw(password)).then(() => {
                      logout();
                      nav('/login', { replace: true, state: { notice: '탈퇴가 완료되었습니다. 그동안 이용해 주셔서 감사합니다.' } });
                    });
                  }}
                >
                  <label>
                    비밀번호 확인
                    <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" />
                  </label>
                  <label className="check consent">
                    <input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} />
                    <span>위 내용을 확인했고, 삭제된 정보는 되돌릴 수 없다는 것을 이해했습니다.</span>
                  </label>
                  <ErrorBox error={act.error} />
                  <div>
                    <button className="btn btn-danger" disabled={act.busy || !agree || !password}>
                      탈퇴하기
                    </button>
                  </div>
                </form>
              )}
            </>
          )}
        </Card>
      </div>
    </>
  );
}
