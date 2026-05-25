import { getToken } from "../utils/authApi";

export default async function useStarters() {
    try {
        // /starters folds in per-template starter source bodies from installed
        // packages when the request is authenticated (see
        // utk_curio/backend/app/api/routes.py → get_starters). Without the Bearer
        // token we'd only ever see the built-in presets, and a freshly-dropped
        // package node would have nothing in its starters dropdown.
        const token = getToken();
        const response = await fetch(process.env.BACKEND_URL + '/starters', {
            headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        });
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const starters = await response.json();
        return starters;
    } catch (error) {
        console.error('Failed to fetch starters:', error);
        return [];
    }
}
