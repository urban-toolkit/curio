/**
 * The agent import picker's cases behind a cold load of the modal.
 *
 * CI's Jest starts with no transform cache, so the first test that loads the
 * agent import modal pays for transforming everything the modal imports. On
 * main's run 42230248452, "a second selection adds to the first" took
 * 7,517 ms against the 5 s a test gets; the next case, with the modal already
 * loaded, took 143 ms. Here the modal's ModalShell takes 3 s to load and each
 * case gets 2 s, so a case that loads the modal on its own clock fails.
 */
jest.mock("../../components/ModalShell", () => {
  const loaded = Date.now() + 3000;
  while (Date.now() < loaded) {
    // What a cold transform of the modal's imports costs on a busy runner.
  }
  return jest.requireActual("../../components/ModalShell");
});

jest.mock("../../services/agents/agentsApi", () => ({
  agentsApi: { uploadImport: jest.fn() },
}));

import { describeTheAgentImportPicker } from "../_support/agentImportPicker";

describeTheAgentImportPicker(2000);
