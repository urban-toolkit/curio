// jest-dom adds custom jest matchers for asserting on DOM nodes.
// allows you to do things like:
// expect(element).toHaveTextContent(/react/i)
// learn more: https://github.com/testing-library/jest-dom
import '@testing-library/jest-dom'; 
import { TextEncoder, TextDecoder } from 'util';

// Inject TextEncoder and TextDecoder into the global Jest/jsdom environment
Object.assign(global, { TextDecoder, TextEncoder });