import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import HelpDialog from '../HelpDialog';
import { article, FEEDBACK_HREF, GET_STARTED_STEPS } from '../helpContent';

vi.mock('@/context/shortcuts/useShortcuts', () => ({
  useShortcuts: () => ({ groups: [], openDialog: () => {} }),
}));

describe('HelpDialog', () => {
  it('opens on five getting-started steps, with a feedback link', () => {
    render(<HelpDialog isOpen onClose={() => {}} />);
    expect(GET_STARTED_STEPS.map((s) => s.title)).toEqual([
      'Open a workspace', 'Add an artifact', 'Group artifacts in a collection', 'Build a workflow', 'Share it']);
    for (const s of GET_STARTED_STEPS) expect(screen.getByText(new RegExp(s.title))).toBeTruthy();
    const link = screen.getByRole('link', { name: 'Send feedback' });
    expect(link.getAttribute('href')).toBe(FEEDBACK_HREF);
    expect(FEEDBACK_HREF.startsWith('mailto:connect@agience.ai')).toBe(true);
  });

  it('says "an artifact", never "a artifact"', () => {
    expect(article('artifact')).toBe('an');
    expect(article('card')).toBe('a');
  });
});
