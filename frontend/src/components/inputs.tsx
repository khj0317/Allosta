import { useState } from 'react';

/** 숫자만 남긴다 */
const digitsOf = (v: string) => v.replace(/\D/g, '');

function formatBirth(d: string) {
  if (d.length <= 4) return d;
  if (d.length <= 6) return `${d.slice(0, 4)}.${d.slice(4)}`;
  return `${d.slice(0, 4)}.${d.slice(4, 6)}.${d.slice(6, 8)}`;
}

/** 8자리 → 'YYYY-MM-DD'. 달력상 존재하지 않거나 미래·1900년 이전이면 오류 메시지 */
export function parseBirth(d: string): { iso: string | null; error: string | null } {
  if (d.length < 8) return { iso: null, error: null };
  const y = Number(d.slice(0, 4));
  const m = Number(d.slice(4, 6));
  const day = Number(d.slice(6, 8));
  const date = new Date(y, m - 1, day);
  if (date.getFullYear() !== y || date.getMonth() !== m - 1 || date.getDate() !== day) {
    return { iso: null, error: '존재하지 않는 날짜입니다.' };
  }
  if (y < 1900 || date > new Date()) return { iso: null, error: '생년월일을 다시 확인해주세요.' };
  return { iso: `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}`, error: null };
}

function koreanAge(iso: string) {
  const b = new Date(iso);
  const t = new Date();
  return t.getFullYear() - b.getFullYear() - (t.getMonth() * 100 + t.getDate() < b.getMonth() * 100 + b.getDate() ? 1 : 0);
}

/**
 * 생년월일 입력: 달력에서 연도를 찾아 내려가는 대신 숫자 8자리를 바로 입력한다.
 * '19910412' → '1991.04.12'로 자동 정리, 모바일에서는 숫자 키패드가 뜬다.
 * onChange에는 유효한 날짜일 때만 'YYYY-MM-DD', 아니면 ''을 넘긴다.
 */
export function BirthDateInput({
  value,
  onChange,
  required,
  disabled,
  id,
}: {
  value: string;
  onChange: (iso: string) => void;
  required?: boolean;
  disabled?: boolean;
  id?: string;
}) {
  const [digits, setDigits] = useState(digitsOf(value).slice(0, 8));
  const { iso, error } = parseBirth(digits);
  return (
    <>
      <input
        id={id}
        inputMode="numeric"
        autoComplete="bday"
        placeholder="예) 19910412"
        value={formatBirth(digits)}
        required={required}
        disabled={disabled}
        aria-invalid={!!error}
        onChange={(e) => {
          const d = digitsOf(e.target.value).slice(0, 8);
          setDigits(d);
          onChange(parseBirth(d).iso ?? '');
        }}
      />
      {error ? (
        <span className="hint text-danger">{error}</span>
      ) : iso ? (
        <span className="hint">만 {koreanAge(iso)}세</span>
      ) : (
        <span className="hint">숫자 8자리로 입력하세요</span>
      )}
    </>
  );
}

function formatPhone(d: string) {
  if (d.length <= 3) return d;
  if (d.length <= 7) return `${d.slice(0, 3)}-${d.slice(3)}`;
  // 010-123-4567(10자리) / 010-1234-5678(11자리)
  const mid = d.length === 10 ? 6 : 7;
  return `${d.slice(0, 3)}-${d.slice(3, mid)}-${d.slice(mid, 11)}`;
}

/** 휴대폰 번호: 숫자만 입력해도 하이픈을 자동으로 넣는다 */
export function PhoneInput({
  value,
  onChange,
  required,
  disabled,
  id,
}: {
  value: string;
  onChange: (formatted: string) => void;
  required?: boolean;
  disabled?: boolean;
  id?: string;
}) {
  return (
    <input
      id={id}
      type="tel"
      inputMode="numeric"
      autoComplete="tel"
      placeholder="010-0000-0000"
      value={value}
      required={required}
      disabled={disabled}
      onChange={(e) => onChange(formatPhone(digitsOf(e.target.value).slice(0, 11)))}
    />
  );
}
