import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api, type Dashboard as D } from '../../api';
import { addDays, parseLocal, pct, today, weekday, won } from '../../format';
import { Card, ErrorBox, Spinner, useAsync } from '../../components/ui';

const RANGES = [
  { label: '최근 7일', days: 7 },
  { label: '최근 4주', days: 28 },
  { label: '최근 90일', days: 90 },
];

export function Dashboard() {
  const [days, setDays] = useState(28);
  const to = today();
  const from = addDays(to, -(days - 1));
  const { data, error, loading } = useAsync(() => api.dashboard(from, to), [from, to]);

  return (
    <>
      <div className="page-head">
        <div>
          <p className="eyebrow">Operations</p>
          <h1>운영 대시보드</h1>
          <p className="sub">
            상담 예약·참석·기록·구매 전환을 자동 집계합니다. 전환 = 상담 완료 후 {data?.attribution_days ?? 30}일 이내 상담사가 추천한 제품 구매.
          </p>
        </div>
        <div className="seg" role="radiogroup" aria-label="기간">
          {RANGES.map((r) => (
            <button key={r.days} className={days === r.days ? 'on' : ''} onClick={() => setDays(r.days)}>
              {r.label}
            </button>
          ))}
        </div>
      </div>
      <ErrorBox error={error} />
      {loading && !data ? <Spinner /> : data && <Body d={data} />}
    </>
  );
}

function Body({ d }: { d: D }) {
  const s = d.summary;
  return (
    <div className="stack">
      {s.overdue > 0 && (
        <div className="alert alert-warn">
          <div>
            <strong>처리 안 된 지난 상담 {s.overdue}건</strong> — 상담 시간이 지났는데 기록 제출·부재 처리가 안 되어 완료율·부재율·전환율에서 빠져 있습니다.
          </div>
          <Link className="btn btn-sm" to="/admin/bookings">확인하기</Link>
        </div>
      )}
      <div className="kpis kpis-lg">
        <Kpi label="상담 전환율" value={pct(s.conversion_rate)} note={`추천 제품 구매 · 귀속 매출 ${won(s.attributed_revenue)}`} />
        <Kpi label="부재율" value={pct(s.no_show_rate)} note={`완료 ${s.completed} · 부재 ${s.no_show}`} />
        <Kpi label="참석 확인율" value={pct(s.attendance_confirm_rate)} note="리마인더 응답 기준" />
        <Kpi label="취소율" value={pct(s.cancel_rate)} note={`전체 예약 ${s.total_bookings}건`} />
        <Kpi label="슬롯 가동률" value={pct(s.slot_utilization)} note="오픈 슬롯 중 예약" />
        <Kpi label="대기 후 예약 전환" value={pct(d.waitlist.recovery_rate)} note={`대기 ${d.waitlist.total}건 중 ${d.waitlist.booked}건 예약`} />
      </div>

      <Card title="일별 상담 결과">
        <DailyChart daily={d.daily} />
      </Card>

      <Card title="상담사별 성과">
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>상담사</th>
                <th className="num">예약</th>
                <th className="num">완료</th>
                <th className="num">부재율</th>
                <th className="num">기록 제출률</th>
                <th className="num">추천률</th>
                <th className="num">상담 전환율</th>
                <th className="num">일반 구매율</th>
                <th className="num">귀속 매출</th>
              </tr>
            </thead>
            <tbody>
              {d.per_counselor.map((c) => (
                <tr key={c.counselor_id}>
                  <td>{c.name}</td>
                  <td className="num">{c.total_bookings}</td>
                  <td className="num">{c.completed}</td>
                  <td className="num">{pct(c.no_show_rate)}</td>
                  <td className="num">{pct(c.record_submit_rate)}</td>
                  <td className="num">{pct(c.recommendation_rate)}</td>
                  <td className="num"><strong>{pct(c.conversion_rate)}</strong></td>
                  <td className="num">{pct(c.any_purchase_rate)}</td>
                  <td className="num">{won(c.attributed_revenue)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid-2">
        <Card title="추천 제품 성과">
          <ProductBars items={d.top_products} />
        </Card>
        <Card title="상담 관심사별 전환">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>관심사</th>
                  <th className="num">상담 수</th>
                  <th className="num">전환율</th>
                </tr>
              </thead>
              <tbody>
                {d.top_concerns.map((c) => (
                  <tr key={c.tag}>
                    <td>{c.tag}</td>
                    <td className="num">{c.count}</td>
                    <td className="num">{pct(c.conversion_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </div>
  );
}

function Kpi({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="kpi">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </div>
  );
}

const SERIES = [
  { key: 'completed', label: '완료', color: 'var(--series-1)' },
  { key: 'no_show', label: '부재', color: 'var(--series-2)' },
  { key: 'cancelled', label: '취소', color: 'var(--series-3)' },
] as const;

/** 누적 막대(완료/부재/취소). 3계열 → 검증된 팔레트 1~3번 슬롯, 범례 + 호버 툴팁. 주말은 제외. */
function DailyChart({ daily }: { daily: D['daily'] }) {
  const [hover, setHover] = useState<number | null>(null);
  const rows = daily.filter((r) => !['토', '일'].includes(weekday(r.date)));
  const max = Math.max(1, ...rows.map((r) => r.completed + r.no_show + r.cancelled));
  const H = 180;
  const showLabelEvery = Math.ceil(rows.length / 12);
  const h = hover !== null ? rows[hover] : null;
  return (
    <div className="chart">
      <div className="legend">
        {SERIES.map((s) => (
          <span key={s.key}>
            <i style={{ background: s.color }} /> {s.label}
          </span>
        ))}
      </div>
      <div className="bars" style={{ height: H }} onMouseLeave={() => setHover(null)}>
        {rows.map((r, i) => {
          const total = r.completed + r.no_show + r.cancelled;
          return (
            <div key={r.date} className={`bar-col ${hover === i ? 'hover' : ''}`} onMouseEnter={() => setHover(i)} aria-label={`${r.date} 완료 ${r.completed}, 부재 ${r.no_show}, 취소 ${r.cancelled}`}>
              <div className="bar-stack" style={{ height: `${(total / max) * 100}%` }}>
                {SERIES.map((s) =>
                  r[s.key] > 0 ? <div key={s.key} style={{ flexGrow: r[s.key], background: s.color }} /> : null,
                )}
              </div>
              <div className="bar-x">{i % showLabelEvery === 0 ? `${parseLocal(r.date).getMonth() + 1}/${parseLocal(r.date).getDate()}` : ''}</div>
            </div>
          );
        })}
      </div>
      {h && (
        <div className="tooltip-line">
          <strong>{h.date} ({weekday(h.date)})</strong> · 완료 {h.completed} · 부재 {h.no_show} · 취소 {h.cancelled}
          {h.booked - h.completed - h.no_show - h.cancelled > 0 && <> · 예정 {h.booked - h.completed - h.no_show - h.cancelled}</>}
        </div>
      )}
      {!h && <div className="tooltip-line muted">막대에 마우스를 올리면 상세 수치를 볼 수 있어요.</div>}
    </div>
  );
}

function ProductBars({ items }: { items: D['top_products'] }) {
  const max = Math.max(1, ...items.map((i) => i.recommended));
  return (
    <div className="hbars">
      <div className="legend">
        <span><i style={{ background: 'var(--series-1)' }} /> 추천 횟수</span>
        <span className="muted small">오른쪽: 높은 관심 / 구매 수량</span>
      </div>
      {items.map((p) => (
        <div key={p.product_id} className="hbar" title={`${p.name}: 추천 ${p.recommended}, 높은 관심 ${p.high_interest}, 구매 ${p.purchased_qty}`}>
          <div className="hbar-label">{p.name}</div>
          <div className="hbar-track">
            <div className="hbar-fill" style={{ width: `${(p.recommended / max) * 100}%` }} />
          </div>
          <div className="hbar-val">
            {p.recommended} <span className="muted">· {p.high_interest} / {p.purchased_qty}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
