// utils/dates.ts
//
// Every date the product shows reads day first with the month as a word ("15 Nov 2026"), and every
// time is 24-hour ("14:05"), whatever the browser's locale: a numeric date such as 11/15/2026 reads
// differently in different countries.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

type When = Date | string | number | null | undefined;

function toDate(when: When): Date | null {
  if (when === null || when === undefined || when === '') return null;
  const d = when instanceof Date ? when : new Date(when);
  return Number.isNaN(d.getTime()) ? null : d;
}

const pad = (n: number) => String(n).padStart(2, '0');

/** "15 Nov 2026"; "15 Nov" when `now` is given and falls in the same year; '' for no date. */
export function formatDay(when: When, now?: Date): string {
  const d = toDate(when);
  if (!d) return '';
  const dayMonth = `${d.getDate()} ${MONTHS[d.getMonth()]}`;
  return now && now.getFullYear() === d.getFullYear() ? dayMonth : `${dayMonth} ${d.getFullYear()}`;
}

/** "14:05", or "14:05:09" with seconds; '' for no date. */
export function formatClock(when: When, seconds = false): string {
  const d = toDate(when);
  if (!d) return '';
  return `${pad(d.getHours())}:${pad(d.getMinutes())}${seconds ? `:${pad(d.getSeconds())}` : ''}`;
}

/** "15 Nov 2026, 14:05"; '' for no date. */
export function formatDayTime(when: When): string {
  const d = toDate(when);
  return d ? `${formatDay(d)}, ${formatClock(d)}` : '';
}
