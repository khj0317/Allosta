import type { Indicator } from '../api';
import { INDICATOR_STATUS } from '../format';
import { Badge } from './ui';

/** 참고범위 대비 위치를 막대로 보여준다. 숫자만 나열하면 고객이 의미를 파악하기 어렵기 때문. */
function RangeBar({ i }: { i: Indicator }) {
  const lo = i.ref_low ?? 0;
  const hi = i.ref_high ?? lo;
  const span = hi - lo || hi || 1;
  const min = lo - span * 0.6;
  const max = hi + span * 0.6;
  const pos = Math.min(100, Math.max(0, ((i.value - min) / (max - min)) * 100));
  const loPos = ((lo - min) / (max - min)) * 100;
  const hiPos = ((hi - min) / (max - min)) * 100;
  return (
    <div className="range" aria-hidden="true">
      <div className="range-ok" style={{ left: `${loPos}%`, width: `${hiPos - loPos}%` }} />
      <div className={`range-dot tone-${INDICATOR_STATUS[i.status].tone}`} style={{ left: `${pos}%` }} />
    </div>
  );
}

export function IndicatorTable({
  indicators,
  selectable,
  selected,
  onToggle,
  onlyAbnormal,
}: {
  indicators: Indicator[];
  selectable?: boolean;
  selected?: number[];
  onToggle?: (id: number) => void;
  onlyAbnormal?: boolean;
}) {
  const rows = onlyAbnormal ? indicators.filter((i) => i.status !== 'NORMAL') : indicators;
  let lastCat = '';
  return (
    <div className="table-wrap">
      <table className="table indicators">
        <thead>
          <tr>
            {selectable && <th style={{ width: 32 }} aria-label="논의 여부" />}
            <th>지표</th>
            <th className="num">결과</th>
            <th>참고범위</th>
            <th>상태</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((i) => {
            const showCat = i.category !== lastCat;
            lastCat = i.category;
            return (
              <tr key={i.id} className={i.status !== 'NORMAL' ? 'row-flag' : ''}>
                {selectable && (
                  <td>
                    <input
                      type="checkbox"
                      checked={selected?.includes(i.id) ?? false}
                      onChange={() => onToggle?.(i.id)}
                      aria-label={`${i.name} 논의함`}
                    />
                  </td>
                )}
                <td>
                  {showCat && <div className="cat">{i.category}</div>}
                  <div className="ind-name" title={i.description}>{i.name}</div>
                  <div className="ind-desc">{i.description}</div>
                </td>
                <td className="num">
                  <strong>{i.value}</strong> <span className="unit">{i.unit}</span>
                </td>
                <td>
                  <div className="ref">
                    {i.ref_low ?? '–'} ~ {i.ref_high ?? '–'}
                  </div>
                  <RangeBar i={i} />
                </td>
                <td>
                  <Badge tone={INDICATOR_STATUS[i.status].tone}>{INDICATOR_STATUS[i.status].label}</Badge>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
