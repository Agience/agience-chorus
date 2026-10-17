// The search panel's choices reach the recall query. 2026-10-13, a tester: the tag, type and
// match-style controls changed nothing, because none of them was sent.
import { describe, it, expect } from 'vitest';
import { composeRecallQuery, TYPE_GROUPS } from '../recallQuery';

describe('composeRecallQuery', () => {
  it('sends the text alone when nothing is chosen', () => {
    expect(composeRecallQuery({ text: ' quasar lantern ' })).toEqual({ query: 'quasar lantern' });
  });

  it('writes Exact words as a phrase', () => {
    expect(composeRecallQuery({ text: 'quasar lantern', exact: true })).toEqual({ query: '="quasar lantern"' });
  });

  it('writes the tag and the type as recall filters', () => {
    expect(composeRecallQuery({ text: '131026', tag: 'alpha-test', typeGroup: 'markdown' }))
      .toEqual({ query: '131026 tag:alpha-test type:text/markdown' });
    expect(composeRecallQuery({ text: 'x', tag: 'Alpha Test', tagExact: true }))
      .toEqual({ query: 'x tag:="Alpha Test"' });
    expect(composeRecallQuery({ text: 'x', typeGroup: 'text' }))
      .toEqual({ query: `x type:${TYPE_GROUPS.text.types.join(',')}` });
  });

  it('says why a filter alone is not a search', () => {
    expect(composeRecallQuery({ text: '', tag: 'alpha-test' }))
      .toEqual({ error: 'Filters narrow a search: add a word to search for.' });
    expect(composeRecallQuery({ text: '  ' })).toEqual({ error: '' });
  });
});
