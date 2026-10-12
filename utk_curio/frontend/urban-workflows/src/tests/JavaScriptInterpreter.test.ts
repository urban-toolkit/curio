import { JavaScriptInterpreter } from '../JavaScriptInterpreter';
import { NodeType } from '../constants';
import { holdNextReply } from './_support/heldReply';

const flushPromises = () => new Promise<void>(resolve => setTimeout(resolve, 0));

process.env.BACKEND_URL = 'http://localhost:5002';

jest.mock('../utils/authApi', () => ({
    getToken: () => null,
}));

jest.mock('../utils/formatters', () => ({
    formatDate: () => '2024-01-01T00:00:00',
    mapTypes: (t: any) => t,
}));

global.fetch = jest.fn();

const mockNodeExecProv = jest.fn();

describe('JavaScriptInterpreter', () => {
    let interpreter: JavaScriptInterpreter;

    beforeEach(() => {
        interpreter = new JavaScriptInterpreter();
        jest.clearAllMocks();
    });

    test('calls /processJavaScriptCode endpoint (not /processPythonCode)', async () => {
        (global.fetch as jest.Mock).mockResolvedValueOnce({
            ok: true,
            json: async () => ({
                stdout: [],
                stderr: '',
                input: { dataType: '' },
                output: { path: 'abc123', dataType: 'int' },
            }),
        });

        const callback = jest.fn();

        interpreter.interpretCode(
            'return 1;',
            'return 1;',
            '',
            [],
            callback,
            NodeType.JS_COMPUTATION,
            'node-1',
            'workflow-1',
            mockNodeExecProv,
        );

        await flushPromises();

        expect(global.fetch).toHaveBeenCalledTimes(1);
        const [url] = (global.fetch as jest.Mock).mock.calls[0];
        expect(url).toContain('/processJavaScriptCode');
        expect(url).not.toContain('/processPythonCode');
    });

    test('calls callback with response JSON on success', async () => {
        const fakeResponse = {
            stdout: ['hello'],
            stderr: '',
            input: { dataType: 'str' },
            output: { path: 'xyz', dataType: 'int' },
        };

        (global.fetch as jest.Mock).mockResolvedValueOnce({
            ok: true,
            json: async () => fakeResponse,
        });

        const callback = jest.fn();

        interpreter.interpretCode(
            'return 1;', 'return 1;', '', [], callback,
            NodeType.JS_COMPUTATION, 'node-1', 'wf', mockNodeExecProv,
        );

        await flushPromises();

        expect(callback).toHaveBeenCalledWith(fakeResponse);
    });

    test('calls callback with error object on network failure', async () => {
        (global.fetch as jest.Mock).mockRejectedValueOnce(new Error('Network error'));

        const callback = jest.fn();

        interpreter.interpretCode(
            'return 1;', 'return 1;', '', [], callback,
            NodeType.JS_COMPUTATION, 'node-1', 'wf', mockNodeExecProv,
        );

        await flushPromises();

        expect(callback).toHaveBeenCalledWith(expect.objectContaining({
            stderr: expect.stringContaining('Network error'),
            output: expect.objectContaining({ path: '' }),
        }));
    });

    test('sends code without Python 4-space indentation', async () => {
        (global.fetch as jest.Mock).mockResolvedValueOnce({
            ok: true,
            json: async () => ({
                stdout: [], stderr: '',
                input: { dataType: '' },
                output: { path: 'x', dataType: 'int' },
            }),
        });

        const userCode = 'return 1;';
        interpreter.interpretCode(
            userCode, userCode, '', [], jest.fn(),
            NodeType.JS_COMPUTATION, 'node-1', 'wf', mockNodeExecProv,
        );

        await flushPromises();

        const body = JSON.parse((global.fetch as jest.Mock).mock.calls[0][1].body);
        expect(body.code).toBe(userCode);
        expect(body.code).not.toMatch(/^    /);
    });

    describe('a run that waited for its turn (#888)', () => {
        // The backend answers every run, however long the run first waited for
        // a free Node slot, and its own timeout decides (#863). So the reply
        // can come long after the request was sent, past the backend's own
        // 600 s, and the node must still get it.
        const HELD_MS = 900_000;

        test('a reply that comes after 180 s, and after the backend\'s 600 s, still reaches the node', async () => {
            jest.useFakeTimers();
            try {
                const reply = holdNextReply(global.fetch as jest.Mock, {
                    stdout: [],
                    stderr: '',
                    output: { path: 'after-the-wait', dataType: 'int' },
                });
                const callback = jest.fn();
                interpreter.interpretCode(
                    'return 1;', 'return 1;', '', [], callback,
                    NodeType.JS_COMPUTATION, 'node-1', 'wf', mockNodeExecProv,
                );

                await jest.advanceTimersByTimeAsync(HELD_MS);
                reply.release();
                await jest.advanceTimersByTimeAsync(0);

                expect(callback).toHaveBeenCalledTimes(1);
                expect(callback.mock.calls[0][0].stderr).toBe('');
                expect(callback.mock.calls[0][0].output.path).toBe('after-the-wait');
            } finally {
                jest.useRealTimers();
            }
        });

        test('a sandbox_timeout body is surfaced with its message, as a Python node does', async () => {
            (global.fetch as jest.Mock).mockResolvedValueOnce({
                ok: false,
                status: 504,
                json: async () => ({
                    error: 'sandbox_timeout',
                    message: 'The sandbox did not respond within 600s on /execJs.',
                }),
            });

            const callback = jest.fn();
            interpreter.interpretCode(
                'return 1;', 'return 1;', '', [], callback,
                NodeType.JS_COMPUTATION, 'node-1', 'wf', mockNodeExecProv,
            );
            await flushPromises();

            expect(callback).toHaveBeenCalledTimes(1);
            const result = callback.mock.calls[0][0];
            expect(result.stderr).toContain('did not respond within 600s');
            expect(result.stderr).not.toContain('transport error');
            expect(result.output.path).toBe('');
        });
    });
});
