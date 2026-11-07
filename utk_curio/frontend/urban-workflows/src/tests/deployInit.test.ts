/**
 * The deployed container runs Docker's init as PID 1, which reaps every
 * process the container inherits (docker-compose.deploy.yml's `init: true`).
 * Without it PID 1 is the launcher, which never reaps one: a node's child
 * killed when the execution zygote died, or a process a killed node had
 * started, stayed a zombie until the container restarted. The backend suite
 * runs in the image, which ships no compose file, so this check lives here.
 */
import { read } from "./_support/workflowPaths";

test("the deployed container runs an init that reaps what it inherits", () => {
    expect(read("docker-compose.deploy.yml")).toMatch(/^ {4}init: true$/m);
});
