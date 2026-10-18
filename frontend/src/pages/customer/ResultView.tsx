import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from '../../api';
import { fmtDate } from '../../format';
import { IndicatorTable } from '../../components/IndicatorTable';
import { Card, ErrorBox, Spinner, useAsync } from '../../components/ui';

export function ResultView() {
  const id = Number(useParams().id);
  const { data: r, error } = useAsync(() => api.result(id), [id]);
  const [onlyAbnormal, setOnlyAbnormal] = useState(false);
  if (error) return <ErrorBox error={error} />;
  if (!r) return <Spinner />;
  return (
    <>
      <div className="page-head">
        <div>
          <Link to="/my" className="back">← 내 검사 결과</Link>
          <p className="eyebrow">Report</p>
          <h1>{r.service_label}</h1>
          <p className="sub">
            {r.subject_name} · {r.kit_code} · {fmtDate(r.reported_at)} 발행
          </p>
        </div>
        <Link className="btn" to={`/my/book?subject=${r.subject_id}&result=${r.id}`}>이 결과로 상담 예약</Link>
      </div>
      <Card title="종합 소견">
        <p>{r.overall_comment}</p>
      </Card>
      <Card
        title={`지표 ${r.indicators.length}개`}
        actions={
          <label className="check small">
            <input type="checkbox" checked={onlyAbnormal} onChange={(e) => setOnlyAbnormal(e.target.checked)} />
            확인 필요 지표만 ({r.abnormal_count})
          </label>
        }
      >
        <IndicatorTable indicators={r.indicators} onlyAbnormal={onlyAbnormal} />
      </Card>
    </>
  );
}
