export class Environment {
  // App environment parameters
  public static backend = 'http://localhost:5001';
  public static serverless = false;
  // public static dataFolder = '../data'

  /**
   * Set environment parameters
   * @param {{backend: string}} env Environment parameters
   */
  // public static setEnvironment(env: {backend: string, dataFolder: string}): void {
  public static setEnvironment(env: {backend: string}): void {
    Environment.backend = env.backend;
    // Environment.dataFolder = env.dataFolder;
  }
}