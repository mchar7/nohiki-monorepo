import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, vi } from 'vitest';
import { axe } from 'vitest-axe';
import '@/test/axe-setup.ts';
import { Input } from './input.tsx';

describe('Input rendering', () => {
  test('renders with default type', () => {
    render(<Input placeholder="Enter text" />);
    const input = screen.getByPlaceholderText('Enter text');
    expect(input).toBeInTheDocument();
  });

  test('renders with specified type', () => {
    render(<Input type="email" placeholder="Enter email" />);
    const input = screen.getByPlaceholderText('Enter email');
    expect(input).toHaveAttribute('type', 'email');
  });

  test('supports password type', () => {
    render(<Input type="password" placeholder="Password" />);
    const input = screen.getByPlaceholderText('Password');
    expect(input).toHaveAttribute('type', 'password');
  });

  test('supports number type', () => {
    render(<Input type="number" placeholder="Number" />);
    const input = screen.getByPlaceholderText('Number');
    expect(input).toHaveAttribute('type', 'number');
  });

  test('applies custom className', () => {
    render(<Input className="custom-class" placeholder="Test" />);
    const input = screen.getByPlaceholderText('Test');
    expect(input).toHaveClass('custom-class');
  });
});

describe('Input behavior', () => {
  test('handles user input', async () => {
    const user = userEvent.setup();
    render(<Input placeholder="Type here" />);
    const input = screen.getByPlaceholderText('Type here');

    await user.type(input, 'Hello World');
    await expect(input).toHaveValue('Hello World');
  });

  test('calls onChange handler', async () => {
    const user = userEvent.setup();
    const handleChange = vi.fn();
    render(<Input onChange={handleChange} placeholder="Test" />);
    const input = screen.getByPlaceholderText('Test');

    await user.type(input, 'a');
    expect(handleChange).toHaveBeenCalled();
  });

  test('can be disabled', () => {
    render(<Input disabled={true} placeholder="Disabled" />);
    const input = screen.getByPlaceholderText('Disabled');
    expect(input).toBeDisabled();
  });

  test('forwards ref correctly', () => {
    const ref = vi.fn();
    render(<Input ref={ref} placeholder="Test" />);
    expect(ref).toHaveBeenCalled();
  });

  test('supports readonly attribute', () => {
    render(<Input readOnly={true} value="Read only" placeholder="Test" />);
    const input = screen.getByPlaceholderText('Test');
    expect(input).toHaveAttribute('readonly');
  });
});

describe('Input - accessibility', () => {
  test('has no accessibility violations', async () => {
    const { container } = render(<Input aria-label="test input" />);
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
