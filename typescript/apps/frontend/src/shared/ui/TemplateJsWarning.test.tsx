import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, vi } from 'vitest';
import { TemplateJsWarning } from './TemplateJsWarning.tsx';

const baseProps = {
  open: true,
  templateName: 'Test Template',
  templateVersion: '1.0.0',
  reason: 'Needed for dynamic content generation',
};

describe('TemplateJsWarning', () => {
  test('renders the template warning details when open', () => {
    render(<TemplateJsWarning {...baseProps} onChoice={vi.fn()} />);

    expect(
      screen.getByRole('heading', { name: 'JavaScript Template Warning' }),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Reason: Needed for dynamic content generation'),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('checkbox', { name: 'Don\'t ask again for "Test Template@1.0.0"' }),
    ).toBeInTheDocument();
  });

  test('does not render warning content while closed', () => {
    render(<TemplateJsWarning {...baseProps} open={false} onChoice={vi.fn()} />);

    expect(
      screen.queryByRole('heading', { name: 'JavaScript Template Warning' }),
    ).not.toBeInTheDocument();
  });

  test('chooses image rendering without remembering by default', async () => {
    const user = userEvent.setup();
    const onChoice = vi.fn();
    render(<TemplateJsWarning {...baseProps} onChoice={onChoice} />);

    await user.click(screen.getByRole('button', { name: 'Render as Image (WebP)' }));

    expect(onChoice).toHaveBeenCalledOnce();
    expect(onChoice).toHaveBeenCalledWith('image', false);
  });

  test('passes the remember preference and resets it after choosing HTML', async () => {
    const user = userEvent.setup();
    const onChoice = vi.fn();
    render(<TemplateJsWarning {...baseProps} onChoice={onChoice} />);
    const rememberCheckbox = screen.getByRole('checkbox', {
      name: 'Don\'t ask again for "Test Template@1.0.0"',
    });

    await user.click(rememberCheckbox);
    await user.click(screen.getByRole('button', { name: 'Render Directly (HTML)' }));

    expect(onChoice).toHaveBeenCalledOnce();
    expect(onChoice).toHaveBeenCalledWith('html', true);
    expect(rememberCheckbox).not.toBeChecked();
  });
});
