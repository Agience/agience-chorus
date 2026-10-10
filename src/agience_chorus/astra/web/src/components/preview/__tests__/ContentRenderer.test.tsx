/**
 * A PDF artifact embeds its URI in an iframe. The URI is the artifact's, so the frame is fully
 * sandboxed: whatever the URL actually serves gets no scripts, forms, popups or top navigation.
 */

import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';

import { ContentRenderer } from '../ContentRenderer';

describe('ContentRenderer PDF embed', () => {
  it('renders the PDF iframe with an empty (fully restrictive) sandbox', () => {
    const { container } = render(
      <ContentRenderer
        content=""
        mime="application/pdf"
        filename="doc.pdf"
        uri="https://files.example.com/doc.pdf"
      />,
    );
    const iframe = container.querySelector('iframe');
    expect(iframe).not.toBeNull();
    expect(iframe!.getAttribute('src')).toBe('https://files.example.com/doc.pdf');
    expect(iframe!.hasAttribute('sandbox')).toBe(true);
    expect(iframe!.getAttribute('sandbox')).toBe('');
  });
});
