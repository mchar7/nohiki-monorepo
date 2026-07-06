import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, vi } from 'vitest';
import { Switch } from './switch.tsx';

describe('Switch', () => {
  test('renders in unchecked state by default', () => {
    render(<Switch />);
    const switchEl = screen.getByRole('switch');
    expect(switchEl).toBeInTheDocument();
    expect(switchEl).toHaveAttribute('data-state', 'unchecked');
  });

  test('renders in checked state when defaultChecked', () => {
    render(<Switch defaultChecked={true} />);
    const switchEl = screen.getByRole('switch');
    expect(switchEl).toHaveAttribute('data-state', 'checked');
  });

  test('toggles state on click', async () => {
    const user = userEvent.setup();
    render(<Switch />);
    const switchEl = screen.getByRole('switch');

    await expect(switchEl).toHaveAttribute('data-state', 'unchecked');

    await user.click(switchEl);
    await expect(switchEl).toHaveAttribute('data-state', 'checked');

    await user.click(switchEl);
    await expect(switchEl).toHaveAttribute('data-state', 'unchecked');
  });

  test('calls onCheckedChange when toggled', async () => {
    const user = userEvent.setup();
    const handleChange = vi.fn();
    render(<Switch onCheckedChange={handleChange} />);
    const switchEl = screen.getByRole('switch');

    await user.click(switchEl);
    expect(handleChange).toHaveBeenCalledWith(true);
  });

  test('applies custom className', () => {
    render(<Switch className="custom-class" />);
    const switchEl = screen.getByRole('switch');
    expect(switchEl).toHaveClass('custom-class');
  });

  test('can be disabled', () => {
    render(<Switch disabled={true} />);
    const switchEl = screen.getByRole('switch');
    expect(switchEl).toBeDisabled();
  });

  test('forwards ref', () => {
    const ref = vi.fn();
    render(<Switch ref={ref} />);
    expect(ref).toHaveBeenCalled();
  });
});
