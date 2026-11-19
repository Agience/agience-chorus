import { get } from './api';

// How each listed artifact is told apart from others shown under the same name comes from
// Crystal, which works it out over every one the caller can reach as their type declares
// (`view.tell_apart`). The listing comes from Mantle; the marks are laid over it by id. Marks
// only decorate a name, so a listing still shows when Crystal does not answer.
export async function withMarks<T extends { id?: unknown }>(rows: Promise<T[]>,
                                                          contentType: string): Promise<T[]> {
  const marks = (async (): Promise<Record<string, object>> => {
    try {
      const body = await get<{ marks?: Record<string, object> }>(
        `/marks?content_type=${encodeURIComponent(contentType)}`);
      return body?.marks ?? {};
    } catch (err) {
      console.warn('marks unavailable; names are listed without them', err);
      return {};
    }
  })();
  const [list, byId] = await Promise.all([rows, marks]);
  return list.map((row) => {
    const mark = byId[String(row.id)];
    return mark ? { ...row, ...mark } : row;
  });
}
