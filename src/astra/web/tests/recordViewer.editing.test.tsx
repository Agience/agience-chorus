import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';

const updateArtifact = vi.fn(() => Promise.resolve());

vi.mock('../src/hooks/useWorkspaces', () => ({
  useWorkspaces: () => ({ activeWorkspaceId: 'ws-1' }),
}));

vi.mock('../src/hooks/useWorkspace', () => {
  return {
    useWorkspace: () => ({
      artifacts: [
        {
          id: 'org-1',
          state: 'draft',
          context: JSON.stringify({
            content_type: 'application/vnd.agience.organization+json',
            identity: {
              display_name: 'Acme Labs',
              legal_name: 'Acme Labs LLC',
              entity_kind: 'company',
              jurisdiction: 'DE',
              website_uri: 'https://acme.example',
            },
            licensing: {
              employee_count: 8,
              annual_gross_revenue_usd: 750000,
              packaging: { hosted_service: false },
            },
            relationships: {
              affiliate_organization_ids: ['org-2'],
            },
          }),
          content: 'Operator profile',
        },
      ],
      displayedArtifacts: [],
      updateArtifact,
    }),
  };
});

import RecordViewer from '../src/content-types/_record/viewer';
import { setRuntimeContentTypes } from '../src/registry/content-types';

// The record schema is declarative — it comes from the type's own `ui.record`,
// served by the platform at runtime. Seed it the same way ContentTypesProvider
// does (GET /types/all → setRuntimeContentTypes) so the viewer renders the org
// form. The viewer holds no type-specific knowledge.
const ORG_RECORD = {
  titlePath: 'identity.display_name',
  subtitlePath: 'identity.legal_name',
  fields: [
    { path: 'identity.entity_kind', label: 'Entity Kind' },
    { path: 'identity.jurisdiction', label: 'Jurisdiction', editable: true },
    { path: 'identity.website_uri', label: 'Website', editable: true, editor: 'url' },
    { path: 'licensing.employee_count', label: 'Employees', editable: true, editor: 'number' },
    { path: 'licensing.annual_gross_revenue_usd', label: 'Annual Gross Revenue (USD)', editable: true, editor: 'number' },
  ],
  collections: [{ path: 'relationships.affiliate_organization_ids', label: 'Affiliates', editable: true }],
  objects: [{ path: 'identity', label: 'Identity' }, { path: 'licensing.packaging', label: 'Packaging' }],
};

describe('RecordViewer editing', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setRuntimeContentTypes([{
      content_type: 'application/vnd.agience.organization+json',
      definition: { ui: { label: 'Organization', icon: 'building-2', viewer: 'record', record: ORG_RECORD } },
    }]);
  });

  it('edits an organization record and persists context', async () => {
    const artifact = {
      id: 'org-1',
      state: 'draft',
      content_type: 'application/vnd.agience.organization+json',
      context: JSON.stringify({
        content_type: 'application/vnd.agience.organization+json',
        identity: {
          display_name: 'Acme Labs',
          legal_name: 'Acme Labs LLC',
          entity_kind: 'company',
          jurisdiction: 'DE',
          website_uri: 'https://acme.example',
        },
        licensing: {
          employee_count: 8,
          annual_gross_revenue_usd: 750000,
          packaging: { hosted_service: false },
        },
        relationships: {
          affiliate_organization_ids: ['org-2'],
        },
      }),
      content: 'Operator profile',
      collection_ids: [],
    };

    render(<RecordViewer artifact={artifact} />);

    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));

    fireEvent.change(screen.getByLabelText('Title'), {
      target: { value: 'Acme Research' },
    });
    fireEvent.change(screen.getByLabelText('Employees'), {
      target: { value: '9' },
    });
    fireEvent.change(screen.getByLabelText('Affiliates'), {
      target: { value: 'org-2\norg-3' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(updateArtifact).toHaveBeenCalledTimes(1);
    });

    expect(updateArtifact).toHaveBeenCalledWith(
      expect.objectContaining({
        id: 'org-1',
        context: expect.any(String),
      })
    );

    const payload = JSON.parse(updateArtifact.mock.calls[0][0].context);
    expect(payload.identity.display_name).toBe('Acme Research');
    expect(payload.licensing.employee_count).toBe(9);
    expect(payload.relationships.affiliate_organization_ids).toEqual(['org-2', 'org-3']);
  });
});