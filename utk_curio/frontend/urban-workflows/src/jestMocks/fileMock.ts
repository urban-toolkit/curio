/**
 * Stand-in for imported binary assets (images, fonts).
 *
 * These must NOT share identity-obj-proxy with CSS modules. Two things break
 * when they do:
 *  - a `jest.mock('assets/logo.png', ...)` in any test resolves to
 *    identity-obj-proxy and so silently replaces every CSS module too, turning
 *    `styles.someClass` into undefined and every className into "";
 *  - identity-obj-proxy answers Symbol.toPrimitive with a symbol, which React
 *    cannot coerce into an <img src> attribute.
 */
export default "test-file-stub";
