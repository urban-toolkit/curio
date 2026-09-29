import { backendUrl } from '../utils/backendUrl';

const w = window as any;

describe('backendUrl()', () => {
    const originalEnv = process.env.BACKEND_URL;

    function serve(url: string) {
        const meta = document.createElement('meta');
        meta.setAttribute('name', 'curio-backend-url');
        meta.setAttribute('content', url);
        document.head.appendChild(meta);
    }

    afterEach(() => {
        delete w.__CURIO_BACKEND_URL__;
        document.querySelectorAll('meta[name="curio-backend-url"]').forEach((el) => el.remove());
        if (originalEnv === undefined) delete process.env.BACKEND_URL;
        else process.env.BACKEND_URL = originalEnv;
    });

    test('prefers the runtime value injected on window', () => {
        process.env.BACKEND_URL = 'http://baked:5002';
        serve('https://served.example.org/app/api');
        w.__CURIO_BACKEND_URL__ = 'http://injected:5203';
        expect(backendUrl()).toBe('http://injected:5203');
    });

    test('then the address the frontend server wrote into the page', () => {
        process.env.BACKEND_URL = 'http://baked:5002';
        serve('https://served.example.org/app/api');
        expect(backendUrl()).toBe('https://served.example.org/app/api');
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
