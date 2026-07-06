import { render, screen } from '@testing-library/react';
import { describe, expect, vi } from 'vitest';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from './card.tsx';

describe('Card', () => {
  test('renders children', () => {
    render(<Card>Card content</Card>);
    expect(screen.getByText('Card content')).toBeInTheDocument();
  });

  test('applies custom className', () => {
    const { container } = render(<Card className="custom-class">Content</Card>);
    const card = container.firstChild as HTMLElement;
    expect(card).toHaveClass('custom-class');
  });

  test('forwards ref', () => {
    const ref = vi.fn();
    render(<Card ref={ref}>Content</Card>);
    expect(ref).toHaveBeenCalled();
  });
});

describe('CardHeader', () => {
  test('renders children', () => {
    render(<CardHeader>Header content</CardHeader>);
    expect(screen.getByText('Header content')).toBeInTheDocument();
  });

  test('applies custom className', () => {
    render(<CardHeader className="custom-class">Header</CardHeader>);
    const header = screen.getByText('Header');
    expect(header).toHaveClass('custom-class');
  });

  test('forwards ref', () => {
    const ref = vi.fn();
    render(<CardHeader ref={ref}>Header</CardHeader>);
    expect(ref).toHaveBeenCalled();
  });
});

describe('CardTitle', () => {
  test('renders children', () => {
    render(<CardTitle>Title content</CardTitle>);
    expect(screen.getByText('Title content')).toBeInTheDocument();
  });

  test('applies custom className', () => {
    render(<CardTitle className="custom-class">Title</CardTitle>);
    const title = screen.getByText('Title');
    expect(title).toHaveClass('custom-class');
  });

  test('forwards ref', () => {
    const ref = vi.fn();
    render(<CardTitle ref={ref}>Title</CardTitle>);
    expect(ref).toHaveBeenCalled();
  });
});

describe('CardDescription', () => {
  test('renders children', () => {
    render(<CardDescription>Description content</CardDescription>);
    expect(screen.getByText('Description content')).toBeInTheDocument();
  });

  test('applies custom className', () => {
    render(<CardDescription className="custom-class">Description</CardDescription>);
    const description = screen.getByText('Description');
    expect(description).toHaveClass('custom-class');
  });

  test('forwards ref', () => {
    const ref = vi.fn();
    render(<CardDescription ref={ref}>Description</CardDescription>);
    expect(ref).toHaveBeenCalled();
  });
});

describe('CardContent', () => {
  test('renders children', () => {
    render(<CardContent>Content</CardContent>);
    expect(screen.getByText('Content')).toBeInTheDocument();
  });

  test('applies custom className', () => {
    render(<CardContent className="custom-class">Content</CardContent>);
    const content = screen.getByText('Content');
    expect(content).toHaveClass('custom-class');
  });

  test('forwards ref', () => {
    const ref = vi.fn();
    render(<CardContent ref={ref}>Content</CardContent>);
    expect(ref).toHaveBeenCalled();
  });
});

describe('CardFooter', () => {
  test('renders children', () => {
    render(<CardFooter>Footer content</CardFooter>);
    expect(screen.getByText('Footer content')).toBeInTheDocument();
  });

  test('applies custom className', () => {
    render(<CardFooter className="custom-class">Footer</CardFooter>);
    const footer = screen.getByText('Footer');
    expect(footer).toHaveClass('custom-class');
  });

  test('forwards ref', () => {
    const ref = vi.fn();
    render(<CardFooter ref={ref}>Footer</CardFooter>);
    expect(ref).toHaveBeenCalled();
  });
});

describe('Card composition', () => {
  test('renders full card with all components', () => {
    render(
      <Card>
        <CardHeader>
          <CardTitle>Card Title</CardTitle>
          <CardDescription>Card description text</CardDescription>
        </CardHeader>
        <CardContent>Main content here</CardContent>
        <CardFooter>Footer actions</CardFooter>
      </Card>,
    );

    expect(screen.getByText('Card Title')).toBeInTheDocument();
    expect(screen.getByText('Card description text')).toBeInTheDocument();
    expect(screen.getByText('Main content here')).toBeInTheDocument();
    expect(screen.getByText('Footer actions')).toBeInTheDocument();
  });
});
