// isolation/mergeViewContext.ts
//
// A view edits a copy of its card's context, taken when it opened. Meanwhile an operator may have
// written to the same card: Lumen records each timer run (`timer_state`), each move of an Inbox
// item. Writing the view's copy back whole erased those. 2026-10-19, on staging: disarming a timer
// from its card wiped the record of the runs it had made.
//
// So a view's save is a three-way merge, key by key, against what the view was given:
//   - a key the view changed (or removed) since it was given the context takes the view's value;
//   - every other key takes the stored value, whatever wrote it since.

type Ctx = Record<string, unknown>;

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function mergeViewContext(given: Ctx, stored: Ctx, fromView: Ctx): Ctx {
  const out: Ctx = { ...stored };
  const keys = new Set([...Object.keys(given), ...Object.keys(fromView)]);
  for (const key of keys) {
    const inView = Object.prototype.hasOwnProperty.call(fromView, key);
    if (same(given[key], fromView[key]) && inView === Object.prototype.hasOwnProperty.call(given, key)) {
      continue;                       // the view left it alone: the stored value stands
    }
    if (inView) out[key] = fromView[key];
    else delete out[key];
  }
  return out;
}
