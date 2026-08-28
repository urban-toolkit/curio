/**
 * The package registry must not be fetched before anyone is signed in.
 *
 * `/api/packages` is `@require_auth` and its response is per-user, so an
 * anonymous call can only 401. `loadInstalledPackages` already suppressed its
 * own console warning for that status — but the request still went out, and the
 * browser logs "Failed to load resource: 401" itself. Because `index.tsx` called
 * this at import time, that error greeted every visitor on the sign-up page,
 * which is the first screen a new user sees.
 */
const mockLoadInstalledPackages = jest.fn().mockResolvedValue([]);
const mockGetToken = jest.fn<string | undefined, []>();

// The factories delegate rather than capture: jest hoists them above the consts
// above, so a direct reference is still undefined when the module is evaluated.
jest.mock('../../registry/packagesClient', () => ({
  loadInstalledPackages: (...args: unknown[]) => mockLoadInstalledPackages(...args),
}));
jest.mock('../../registry/projectPackagesStore', () => ({
  getCurrentProjectPackages: () => [],
}));
jest.mock('../../utils/authApi', () => ({
  getToken: () => mockGetToken(),
}));

import { refreshPackageRegistry } from '../../registry/packageRegistryBootstrap';

beforeEach(() => {
  jest.clearAllMocks();
});

describe('refreshPackageRegistry', () => {
  it('makes no request when there is no session token', async () => {
    mockGetToken.mockReturnValue(undefined);

    await refreshPackageRegistry();

    expect(mockLoadInstalledPackages).not.toHaveBeenCalled();
  });

  it('fetches once a session token exists', async () => {
    mockGetToken.mockReturnValue('a-session-token');

    await refreshPackageRegistry();

    expect(mockLoadInstalledPackages).toHaveBeenCalledTimes(1);
  });

  it('still resolves when it skips the fetch', async () => {
    // Callers `void` this or chain off it; returning undefined would throw.
    mockGetToken.mockReturnValue(undefined);

    await expect(refreshPackageRegistry()).resolves.toBeUndefined();
  });
});
