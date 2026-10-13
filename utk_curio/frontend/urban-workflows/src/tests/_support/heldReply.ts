/**
 * A fetch reply the test sends when it chooses, the way the backend answers a
 * node run only when the run ends, however long it waited for its turn first
 * (#888). The request's AbortSignal is honoured as a browser honours it, so a
 * clock of the page's own that gives up on the request ends it with an
 * AbortError, as on a real page.
 */
export function holdNextReply(fetchMock: jest.Mock, body: unknown, status = 200): { release: () => void } {
    let release = (): void => {
        throw new Error('the node never sent its request');
    };
    fetchMock.mockImplementationOnce((_url: string, init?: RequestInit) =>
        new Promise((resolve, reject) => {
            init?.signal?.addEventListener('abort', () => {
                const error = new Error('The operation was aborted.');
                error.name = 'AbortError';
                reject(error);
            });
            release = () => resolve({ ok: status < 400, status, json: async () => body });
        }));
    return { release: () => release() };
}
