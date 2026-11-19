import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// The Facet makes a named link: a collection edged by `initialized_by` to an initializer is what
// files a request's approval as its part, and that edge is made here, without a script.
const linkArtifact = vi.fn();
const removeArtifactLinks = vi.fn();
let links: Array<Record<string, unknown>> = [];
const artifacts: Record<string, Record<string, unknown>> = {
  'coll-1': { id: 'coll-1', context: JSON.stringify({ title: 'Release requests' }) },
  'init-7': { id: 'init-7', root_id: 'init-7', context: JSON.stringify({ title: 'Release initializer' }) },
};
vi.mock('@/api/artifacts', async (orig) => ({
  RELATIONSHIP_PATTERN: ((await orig()) as { RELATIONSHIP_PATTERN: RegExp }).RELATIONSHIP_PATTERN,
  getArtifact: async (id: string) => {
    if (artifacts[id]) return artifacts[id];
    throw Object.assign(new Error('nf'), { response: { status: 404, data: { detail: 'Artifact not found' } } });
  },
  listArtifactLinks: async () => links,
  linkArtifact: (...a: unknown[]) => linkArtifact(...a),
  removeArtifactLinks: (...a: unknown[]) => removeArtifactLinks(...a),
}));

import { LinksDialog } from '../LinksDialog';

const open = () => render(<LinksDialog open onOpenChange={() => {}} artifactId="coll-1" />);

describe('LinksDialog', () => {
  beforeEach(() => {
    links = [];
    linkArtifact.mockReset().mockImplementation(async (_from: string, to: string, rel: string) => {
      links = [...links, { ...artifacts[to], relationship: rel, direction: 'out' }];
      return artifacts[to];
    });
    removeArtifactLinks.mockReset().mockImplementation(async (_from: string, rel: string) => {
      links = links.filter((l) => l.relationship !== rel);
      return { removed: 1 };
    });
  });

  it('links an artifact by id under a name and lists it', async () => {
    open();
    await waitFor(() => expect(screen.getByText('Links: Release requests')).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText('initialized_by'), { target: { value: 'initialized_by' } });
    fireEvent.change(screen.getByPlaceholderText(/Paste an id/), { target: { value: 'init-7' } });
    await waitFor(() => expect(screen.getByTestId('link-target').textContent).toContain('Release initializer'));
    await act(async () => { fireEvent.click(screen.getByText('Add link')); });
    expect(linkArtifact).toHaveBeenCalledWith('coll-1', 'init-7', 'initialized_by');
    await waitFor(() => expect(screen.getAllByTestId('link-out')).toHaveLength(1));
    expect(screen.getByTestId('link-out').textContent).toContain('initialized_by');
    expect(screen.getByTestId('link-out').textContent).toContain('Release initializer');
  });

  it('removes a link by its name', async () => {
    links = [{ ...artifacts['init-7'], relationship: 'initialized_by', direction: 'out' }];
    open();
    await waitFor(() => expect(screen.getAllByTestId('link-out')).toHaveLength(1));
    await act(async () => { fireEvent.click(screen.getByLabelText('Remove initialized_by')); });
    expect(removeArtifactLinks).toHaveBeenCalledWith('coll-1', 'initialized_by');
    await waitFor(() => expect(screen.queryAllByTestId('link-out')).toHaveLength(0));
  });

  it('refuses a name Mantle would refuse, and an id nobody can read', async () => {
    open();
    fireEvent.change(screen.getByPlaceholderText('initialized_by'), { target: { value: 'initialized by' } });
    expect(screen.getByTestId('link-name-invalid')).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText(/Paste an id/), { target: { value: 'nope' } });
    await waitFor(() => expect(screen.getByTestId('link-target-error').textContent).toContain('Artifact not found'));
    expect((screen.getByText('Add link') as HTMLButtonElement).disabled).toBe(true);
  });

  it('lists the links that point at the artifact apart from its own', async () => {
    links = [{ id: 'req-2', context: JSON.stringify({ title: 'Deploy request' }), relationship: 'filed_in', direction: 'in' }];
    open();
    await waitFor(() => expect(screen.getAllByTestId('link-in')).toHaveLength(1));
    expect(screen.queryAllByTestId('link-out')).toHaveLength(0);
  });
});
