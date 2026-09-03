import { backendUrl } from '../utils/backendUrl';

const w = window as any;

describe('backendUrl()', () => {
    const originalEnv = process.env.BACKEND_URL;

    afterEach(() => {
        delete w.__CURIO_BACKEND_URL__;
        if (originalEnv === undefined) delete process.env.BACKEND_URL;
        else process.env.BACKEND_URL = originalEnv;
    });

    test('prefers the runtime value injected on window', () => {
        process.env.BACKEND_URL = 'http://baked:5002';
        w.__CURIO_BACKEND_URL__ = 'http://injected:5203';
        expect(backendUrl()).toBe('http://injected:5203');
    });

    test('falls back to the build-time env var when nothing is injected', () => {
        process.env.BACKEND_URL = 'http://baked:5002';
        expect(backendUrl()).toBe('http://baked:5002');
    });

    test('an empty injection does not shadow the env var', () => {
        process.env.BACKEND_URL = 'http://baked:5002';
        w.__CURIO_BACKEND_URL__ = '';
        expect(backendUrl()).toBe('http://baked:5002');
    });

    test('is same-origin (empty) when neither is set, so callers keep their own default', () => {
        delete process.env.BACKEND_URL;
        expect(backendUrl()).toBe('');
        expect(backendUrl() || 'http://localhost:5002').toBe('http://localhost:5002');
    });

    test('strips a trailing slash so `${backendUrl()}/path` never doubles it', () => {
        w.__CURIO_BACKEND_URL__ = 'http://injected:5203/';
        expect(backendUrl()).toBe('http://injected:5203');
    });
});
