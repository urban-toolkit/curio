# Testing Documentation

This project uses Jest and React Testing Library for testing React components and TypeScript code.

## Quick Start

```bash
# Run all tests
npm test

# Run tests in watch mode
npm test -- --watch

# Run tests with coverage
npm test -- --coverage
```

## Project Structure

Tests are organized in a separate `tests/` directory that mirrors the source code structure:

```
src/
├── tests/
│   ├── components/    # Component tests
│   ├── providers/     # Context provider tests (TODO)
│   ├── services/      # Service/API tests (TODO)
│   ├── hooks/         # Custom hook tests (TODO)
│   └── utils/         # Utility function tests (TODO)
├── components/        # Source components
├── providers/         # Source providers
└── setupTests.ts      # Test configuration
```

## Writing Tests

### File Naming
Test files use the same name as the source file with `.test.tsx` (or `.test.ts`) suffix:
- `Button.tsx` → `Button.test.tsx`
- `utils.ts` → `utils.test.ts`

### Basic Example

```typescript
// src/tests/components/Button.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { Button } from '../../components/Button';

describe('Button', () => {
  it('renders with text', () => {
    render(<Button>Click me</Button>);
    expect(screen.getByText('Click me')).toBeInTheDocument();
  });

  it('handles click events', () => {
    const handleClick = jest.fn();
    render(<Button onClick={handleClick}>Click me</Button>);
    
    fireEvent.click(screen.getByText('Click me'));
    expect(handleClick).toHaveBeenCalledTimes(1);
  });
});
```

### Import Paths
Since tests are in a separate directory, use relative imports:

```typescript
import { Component } from '../../components/Component';
import { useCustomHook } from '../../hooks/useCustomHook';
```

## Testing Guidelines

### What to Test
- Component rendering with different props
- User interactions (clicks, input changes)
- Conditional rendering logic
- Error states and edge cases

### What NOT to Test
- Implementation details
- Third-party library internals
- Style/CSS properties (unless critical)

### Mocking

Mock external dependencies and modules as needed:

```typescript
// Mock a custom hook
jest.mock('../../hooks/useAuth', () => ({
  useAuth: () => ({
    user: { id: '123', name: 'Test User' },
    isAuthenticated: true,
  }),
}));

// Mock an API service
jest.mock('../../services/api', () => ({
  fetchData: jest.fn(() => Promise.resolve({ data: [] })),
}));
```

## Running Specific Tests

```bash
# Run tests matching a pattern
npm test -- --testPathPattern=Button

# Run tests with a specific name
npm test -- --testNamePattern="renders correctly"

# Debug a single test file
npm test -- Button.test.tsx --verbose
```

## Contributing

When adding new features:

1. Create a corresponding test file in the `tests/` directory
2. Write tests that cover the main functionality
3. Ensure all tests pass before submitting a PR
4. Aim for meaningful test coverage, not 100%

## Resources

- [Jest Documentation](https://jestjs.io/docs/getting-started)
- [React Testing Library](https://testing-library.com/docs/react-testing-library/intro)
- [Testing Best Practices](https://kentcdodds.com/blog/common-mistakes-with-react-testing-library) 