import { useState } from 'react';
import { api, type CounselorAdmin as Counselor, type ServiceType } from '../../api';
import { PhoneInput } from '../../components/inputs';
import { Badge, Card, ErrorBox, Modal, Spinner, useAction, useAsync } from '../../components/ui';

/** 관리자: 상담사 계정 발급·담당 분석 수정·비활성화. 상담사는 회원가입으로 만들 수 없다. */
export function CounselorAdmin() {
  const { data: list, error, reload } = useAsync(api.adminCounselors);
  const { data: meta } = useAsync(api.meta);
  const [adding, setAdding] = useState(false);
  const [issued, setIssued] = useState<{ name: string; email: string; temp: string } | null>(null);
  const act = useAction();
  const label = (s: ServiceType) => meta?.service_types.find((x) => x.value === s)?.label ?? s;

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">Counselors</p>
          <h1>상담사 계정</h1>
          <p className="sub">상담사 계정은 여기서만 발급합니다. 발급 시 임시 비밀번호가 한 번만 표시되고, 상담사는 첫 로그인 후 비밀번호를 바꿔야 합니다.</p>
        </div>
        <button className="btn" onClick={() => setAdding(true)}>+ 상담사 등록</button>
      </div>
      <ErrorBox error={error || act.error} />
      {issued && (
        <div className="alert alert-info">
          <div>
            <strong>{issued.name}</strong> 상담사 계정을 만들었습니다. 아래 정보를 상담사에게 전달해주세요. 이 화면을 벗어나면 임시 비밀번호를 다시 볼 수 없습니다.
            <dl className="kv" style={{ marginTop: 10 }}>
              <dt>이메일</dt>
              <dd className="tabular">{issued.email}</dd>
              <dt>임시 비밀번호</dt>
              <dd className="tabular"><strong>{issued.temp}</strong></dd>
            </dl>
          </div>
          <button className="link-btn" onClick={() => setIssued(null)}>확인했어요</button>
        </div>
      )}
      <Card>
        {!list || !meta ? (
          <Spinner />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>상담사</th>
                  <th>연락처</th>
                  <th>담당 분석</th>
                  <th className="num">예정 상담</th>
                  <th>상태</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {list.map((c) => (
                  <tr key={c.id} className={c.active ? '' : 'dim-row'}>
                    <td>
                      <strong>{c.name}</strong>
                      <div className="muted small">{c.email}</div>
                    </td>
                    <td className="tabular">{c.phone}</td>
                    <td>
                      <SpecialtyEditor counselor={c} options={meta.service_types} label={label} onSaved={reload} />
                    </td>
                    <td className="num">{c.upcoming_bookings}</td>
                    <td>
                      {c.active ? <Badge tone="ok">활성</Badge> : <Badge tone="muted">비활성</Badge>}
                      {c.must_change_password && c.active && <div className="small muted">첫 로그인 전</div>}
                    </td>
                    <td className="num">
                      <button
                        className={`link-btn ${c.active ? 'btn-danger' : ''}`}
                        disabled={act.busy}
                        onClick={() => {
                          if (c.active && !confirm(`${c.name} 상담사를 비활성화할까요? 로그인과 신규 예약 노출이 즉시 막힙니다.`)) return;
                          act.run(() => api.updateCounselor(c.id, { active: !c.active })).then(reload);
                        }}
                      >
                        {c.active ? '비활성화' : '다시 활성화'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {adding && meta && (
        <AddCounselorModal
          options={meta.service_types}
          onClose={() => setAdding(false)}
          onDone={(r) => {
            setAdding(false);
            setIssued({ name: r.counselor.name, email: r.counselor.email, temp: r.temp_password });
            reload();
          }}
        />
      )}
    </>
  );
}

function SpecialtyEditor({
  counselor,
  options,
  label,
  onSaved,
}: {
  counselor: Counselor;
  options: { value: ServiceType; label: string }[];
  label: (s: ServiceType) => string;
  onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState<ServiceType[]>(counselor.specialties);
  const act = useAction();
  if (!editing)
    return (
      <div className="row">
        <span className="small">{counselor.specialties.map(label).join(', ')}</span>
        {counselor.active && (
          <button className="link-btn" onClick={() => setEditing(true)}>수정</button>
        )}
      </div>
    );
  return (
    <div>
      <div className="chips">
        {options.map((o) => (
          <button
            type="button"
            key={o.value}
            className={`chip chip-sm ${value.includes(o.value) ? 'on' : ''}`}
            onClick={() => setValue((v) => (v.includes(o.value) ? v.filter((x) => x !== o.value) : [...v, o.value]))}
          >
            {o.label}
          </button>
        ))}
      </div>
      <ErrorBox error={act.error} />
      <div className="row" style={{ marginTop: 8 }}>
        <button
          className="btn btn-sm"
          disabled={act.busy || value.length === 0}
          onClick={() => act.run(() => api.updateCounselor(counselor.id, { specialties: value })).then(() => { setEditing(false); onSaved(); })}
        >
          저장
        </button>
        <button className="link-btn" onClick={() => { setEditing(false); setValue(counselor.specialties); }}>취소</button>
      </div>
    </div>
  );
}

function AddCounselorModal({
  options,
  onClose,
  onDone,
}: {
  options: { value: ServiceType; label: string }[];
  onClose: () => void;
  onDone: (r: { counselor: Counselor; temp_password: string }) => void;
}) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [bio, setBio] = useState('');
  const [specialties, setSpecialties] = useState<ServiceType[]>([]);
  const act = useAction();
  return (
    <Modal title="상담사 등록" onClose={onClose}>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          act.run(() => api.createCounselor({ name, email, phone, specialties, bio })).then(onDone);
        }}
      >
        <label>
          이름
          <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={50} />
        </label>
        <label>
          업무용 이메일
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          <span className="hint">로그인 아이디로 쓰입니다.</span>
        </label>
        <label>
          휴대폰 번호
          <PhoneInput value={phone} onChange={setPhone} required />
        </label>
        <div>
          <div className="label">담당 분석 서비스 *</div>
          <div className="chips">
            {options.map((o) => (
              <button
                type="button"
                key={o.value}
                className={`chip chip-sm ${specialties.includes(o.value) ? 'on' : ''}`}
                onClick={() => setSpecialties((v) => (v.includes(o.value) ? v.filter((x) => x !== o.value) : [...v, o.value]))}
              >
                {o.label}
              </button>
            ))}
          </div>
          <span className="hint">선택한 분석의 결과지 상담에만 예약 화면에 노출됩니다.</span>
        </div>
        <label>
          소개 <span className="muted">(선택)</span>
          <input value={bio} onChange={(e) => setBio(e.target.value)} maxLength={300} placeholder="예) 임상영양사 · 대사질환 상담 5년" />
        </label>
        <ErrorBox error={act.error} />
        <button className="btn btn-block" disabled={act.busy || specialties.length === 0}>계정 발급</button>
      </form>
    </Modal>
  );
}
