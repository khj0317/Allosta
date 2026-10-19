import { useParams } from 'react-router-dom';
import { api } from '../api';
import { fmtDateTime } from '../format';
import { ErrorBox, Spinner, useAction, useAsync } from '../components/ui';

/**
 * 문자 링크로 여는 참석 응답 화면(로그인 없음).
 * 가족 번호로 상담 전화를 받는 분도 계정 없이 '통화 가능 / 어려워요'를 알려줄 수 있다.
 */
export function Attendance() {
  const token = useParams().token ?? '';
  const { data, error, setData } = useAsync(() => api.publicAttendance(token), [token]);
  const act = useAction();

  return (
    <div className="attend">
      <div className="attend-card">
        <div className="brand">
          <span className="brand-word">Allosta</span>
          <span className="brand-sep" aria-hidden="true" />
          <span className="brand-sub">결과 상담</span>
        </div>
        {error ? (
          <ErrorBox error={error} />
        ) : !data ? (
          <Spinner />
        ) : (
          <>
            <p className="eyebrow">Reminder</p>
            <h1>{fmtDateTime(data.start_at)}</h1>
            <p className="sub">
              {data.counselor_name} 상담사가 <strong>{data.contact_phone}</strong>로 전화드립니다.
              <br />
              {data.subject_name}님 검사 결과 상담 · 약 30분
            </p>

            {!data.can_respond ? (
              <div className="alert alert-info">
                <div>이미 지났거나 취소된 상담입니다.</div>
              </div>
            ) : data.attendance_confirmed_at ? (
              <div className="alert alert-ok">
                <div>
                  <strong>참석 확인 완료.</strong> 상담사가 시간에 맞춰 전화드릴게요.
                </div>
              </div>
            ) : data.attendance_declined_at ? (
              <div className="alert alert-warn">
                <div>
                  <strong>통화가 어렵다고 전달했습니다.</strong> 예약하신 분께 일정 변경 안내를 보내드렸어요.
                </div>
              </div>
            ) : (
              <p className="attend-q">이 시간에 통화 가능하신가요?</p>
            )}

            <ErrorBox error={act.error} />
            {data.can_respond && (
              <div className="attend-actions">
                <button
                  className="btn btn-block"
                  disabled={act.busy || !!data.attendance_confirmed_at}
                  onClick={() => act.run(() => api.publicConfirm(token)).then(setData)}
                >
                  네, 통화 가능합니다
                </button>
                <button
                  className="btn btn-ghost btn-block"
                  disabled={act.busy || !!data.attendance_declined_at}
                  onClick={() => act.run(() => api.publicDecline(token)).then(setData)}
                >
                  이 시간은 어려워요
                </button>
              </div>
            )}
            <p className="hint">일정 변경·취소는 예약하신 분이 알로스타에 로그인해서 할 수 있어요.</p>
          </>
        )}
      </div>
    </div>
  );
}
