// jest-dom adds custom jest matchers for asserting on DOM nodes.
// allows you to do things like:
// expect(element).toHaveTextContent(/react/i)
// learn more: https://github.com/testing-library/jest-dom
import '@testing-library/jest-dom';
import { resetRunDetailsForTests } from './components/agents/attach/chat/runDetails';

// Show run details is a viewer's own switch, kept in the browser: each case
// starts with it off, whatever an earlier case of its file turned on.
beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    // A test environment with no storage keeps nothing to clear.
  }
  resetRunDetailsForTests();
}); 