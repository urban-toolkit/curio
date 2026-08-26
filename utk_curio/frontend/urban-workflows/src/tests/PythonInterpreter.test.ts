import { PythonInterpreter } from '../PythonInterpreter';
import { NodeType } from '../constants';

const flushPromises = () => new Promise<void>(resolve => setTimeout(resolve, 0));

process.env.BACKEND_URL = 'http://localhost:5002';

jest.mock('../utils/authApi', () => ({
    getToken: () => 'test-token',
}));

jest.mock('../utils/formatters', () => ({
    formatDate: () => '2024-01-01T00:00:00',
    mapTypes: (t: any) => t,
}));

global.fetch = jest.fn();

const mockNodeExecProv = jest.fn();

/**
 * Isolated node execution introduces failure modes the in-process path never
 * had: a node killed for exceeding its memory cap, or stopped at the
 * wall-clock deadline. Those arrive as an ordinary 200 with a populated
 * `stderr` and an empty `output.path` (see the response contract in
 * utk_curio/sandbox/isolation/runner.py).
 *
 * The risk being tested is a silent success: if the UI keys off the HTTP
 * status instead of the body, a killed node renders as a node that returned
 * nothing, and the user sees no error at all.
 */
describe('PythonInterpreter', () => {
    let interpreter: PythonInterpreter;

    const run = (callback: jest.Mock) =>
        interpreter.interpretCode(
            'return 1',
            'return 1',
            '',
            [],
            callback,
            NodeType.COMPUTATION_ANALYSIS,
            'node-1',
            'workflow-1',
            mockNodeExecProv,
        );

    beforeEach(() => {
        interpreter = new PythonInterpreter();
        jest.clearAllMocks();
    });

    test('calls /processPythonCode and attaches the bearer token', async () => {
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
        run(callback);
        await flushPromises();

        expect(global.fetch).toHaveBeenCalledTimes(1);
        const [url, options] = (global.fetch as jest.Mock).mock.calls[0];
        expect(url).toContain('/processPythonCode');
        expect(options.headers.Authorization).toBe('Bearer test-token');
    });

    test('indents the user code so it lands inside def userCode(arg)', async () => {
        (global.fetch as jest.Mock).mockResolvedValueOnce({
            ok: true,
            json: async () => ({
                stdout: [],
                stderr: '',
                input: { dataType: '' },
                output: { path: 'abc', dataType: 'int' },
            }),
        });

        interpreter.interpretCode(
            'return 1',
            'x = 1\nreturn x',
            '',
            [],
            jest.fn(),
            NodeType.COMPUTATION_ANALYSIS,
            'node-1',
            'workflow-1',
            mockNodeExecProv,
        );
        await flushPromises();

        const [, options] = (global.fetch as jest.Mock).mock.calls[0];
        const body = JSON.parse(options.body);
        // The sandbox wraps this as `def userCode(arg):\n<code>`, so every
        // line has to arrive already indented.
        expect(body.code).toBe('    x = 1\n    return x\n');
    });

    describe('isolated-execution failures surface as node errors', () => {
        const cases: Array<[string, string]> = [
            [
                'killed at the wall-clock deadline',
                'This node was stopped after 300s. It is still counted as a failure '
                    + 'rather than a partial result.',
            ],
            [
                'killed for exceeding the memory cap',
                'This node was killed by the operating system. The usual cause is '
                    + 'exceeding the memory limit of 4096 MB.',
            ],
            [
                'confinement could not be applied',
                'The sandbox could not confine this execution, so it refused to run '
                    + 'the node rather than run it unprotected.',
            ],
            [
                'a result the sandbox refused',
                'The isolated execution returned a result the sandbox refused: '
                    + 'unsafe filename in child manifest',
            ],
        ];

        test.each(cases)('%s reaches the callback as stderr', async (_name, stderr) => {
            (global.fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                json: async () => ({
                    stdout: [],
                    stderr,
                    input: { dataType: '' },
                    // The failure contract: an empty output path.
                    output: { path: '', dataType: 'str' },
                }),
            });

            const callback = jest.fn();
            run(callback);
            await flushPromises();

            expect(callback).toHaveBeenCalledTimes(1);
            const result = callback.mock.calls[0][0];
            expect(result.stderr).toBe(stderr);
            expect(result.output.path).toBe('');
        });

        test('a killed node is not mistaken for a successful empty result', async () => {
            (global.fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                json: async () => ({
                    stdout: ['partial output before the kill'],
                    stderr: 'This node was stopped after 300s.',
                    input: { dataType: '' },
                    output: { path: '', dataType: 'str' },
                }),
            });

            const callback = jest.fn();
            run(callback);
            await flushPromises();

            const result = callback.mock.calls[0][0];
            expect(result.stderr).not.toBe('');
            // stdout produced before the kill must survive: it is the main
            // debugging tool for a node that never finished.
            expect(result.stdout).toEqual(['partial output before the kill']);
        });

        test('stdout is preserved on a successful run too', async () => {
            (global.fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                json: async () => ({
                    stdout: ['one', 'two'],
                    stderr: '',
                    input: { dataType: '' },
                    output: { path: 'abc', dataType: 'int' },
                }),
            });

            const callback = jest.fn();
            run(callback);
            await flushPromises();

            expect(callback.mock.calls[0][0].stdout).toEqual(['one', 'two']);
        });
    });

    describe('transport-level failures', () => {
        test('a sandbox_timeout body is surfaced with its message', async () => {
            (global.fetch as jest.Mock).mockResolvedValueOnce({
                ok: false,
                status: 504,
                json: async () => ({
                    error: 'sandbox_timeout',
                    message: 'The sandbox did not respond within 600s on /exec.',
                }),
            });

            const callback = jest.fn();
            run(callback);
            await flushPromises();

            const result = callback.mock.calls[0][0];
            expect(result.stderr).toContain('did not respond within 600s');
            expect(result.output.path).toBe('');
        });

        test('a sandbox_unauthorized body is surfaced rather than swallowed', async () => {
            // The backend returns this when the two processes disagree about
            // CURIO_SANDBOX_TOKEN (see routes.py::_sandbox_call).
            (global.fetch as jest.Mock).mockResolvedValueOnce({
                ok: false,
                status: 502,
                json: async () => ({
                    error: 'sandbox_unauthorized',
                    stderr: 'The sandbox rejected the backend on /exec.',
                    message: 'The sandbox rejected the backend on /exec.',
                }),
            });

            const callback = jest.fn();
            run(callback);
            await flushPromises();

            expect(callback.mock.calls[0][0].stderr).toContain('rejected the backend');
        });

        test('a non-JSON response does not leave the node silent', async () => {
            (global.fetch as jest.Mock).mockResolvedValueOnce({
                ok: false,
                status: 500,
                json: async () => {
                    throw new Error('Unexpected token < in JSON');
                },
            });

            const callback = jest.fn();
            run(callback);
            await flushPromises();

            expect(callback).toHaveBeenCalledTimes(1);
            expect(callback.mock.calls[0][0].stderr).toContain('invalid JSON');
        });
    });
});
