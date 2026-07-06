import { render, screen } from '@testing-library/react';
import { describe, expect, vi } from 'vitest';
import { Label } from './label.tsx';

describe('Label', () => {
  test('renders with text content', () => {
    render(<Label>Username</Label>);
    expect(screen.getByText('Username')).toBeInTheDocument();
  });

  test('applies custom className', () => {
    render(<Label className="custom-class">Test</Label>);
    expect(screen.getByText('Test')).toHaveClass('custom-class');
  });

  test('forwards ref', () => {
    const ref = vi.fn();
    render(<Label ref={ref}>Test</Label>);
    expect(ref).toHaveBeenCalled();
  });

  test('associates with input via htmlFor', () => {
    render(<Label htmlFor="test-input">Email</Label>);
    const label = screen.getByText('Email');
    expect(label).toHaveAttribute('for', 'test-input');
  });

  test('renders with nested elements', () => {
    render(
      <Label>
        <span>Required</span> Field
      </Label>,
    );
    expect(screen.getByText('Required')).toBeInTheDocument();
  });
});
