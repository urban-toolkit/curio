/**
 * What a node shows when a run reused the result its last run kept, as a
 * dashboard visitor's step does (dataflow audit step 6, step 9): Done, with
 * that result, and, in place of its logs, when the result was made and that
 * the node did not run. The same comes back from a run's record (a tab that
 * follows or reopens the run), and a reuse records no run in the provenance.
 */
import { executionResultOutput, recordExecProvenance } from '../../utils/executionResult';
import { replyFromRecord, replyFromTails } from '../../providers/flow/serverRunSteps';

const MADE_AT = '2026-11-23T14:32:05.123456+00:00';
const OUTPUT = { path: '1763905925123_ab12cd', dataType: 'dataframe' };
const WHEN = new Date(MADE_AT).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
const REUSED_LINE =
  `Reused the result of ${WHEN}: same code, inputs and datasets, so the node did not run. ` +
  'Play the node to run it again.';

describe('a reused result', () => {
  test('says when it was made and that the node did not run, in place of its logs', () => {
    const { shown, artifact } = executionResultOutput({
      stdout: [], stderr: '', output: OUTPUT, reused: { madeAt: MADE_AT },
    });

    expect(shown.code).toBe('success');
    expect(shown.content).toBe(`${REUSED_LINE}\nSaved to file: ${OUTPUT.path}`);
    expect(artifact).toEqual(OUTPUT);
  });

  test("says the same from a run's record and from a step's tails", () => {
    const fromRecord = replyFromRecord({
      nodeId: 'a', status: 'ok', outputPath: OUTPUT.path, outputType: OUTPUT.dataType,
      stdoutTail: null, stderrTail: null, reusedMadeAt: MADE_AT,
    } as any);
    const fromTails = replyFromTails({
      output: OUTPUT, stdoutTail: '', stderrTail: '', reusedMadeAt: MADE_AT,
    } as any);

    for (const reply of [fromRecord, fromTails]) {
      expect(executionResultOutput(reply).shown.content).toBe(`${REUSED_LINE}\nSaved to file: ${OUTPUT.path}`);
    }
  });

  test('records no run in the provenance', () => {
    const provenance = jest.fn();

    recordExecProvenance(provenance, {
      startedAt: new Date(), finishedAt: new Date(), workflowName: 'w', nodeId: 'a', input: '',
      reply: { stdout: [], stderr: '', output: OUTPUT, reused: { madeAt: MADE_AT } }, code: 'return 1',
    });

    expect(provenance).not.toHaveBeenCalled();
  });

  test('guard: a result that ran shows its logs and records its run, as before', () => {
    const provenance = jest.fn();
    const reply = { stdout: ['ran a'], stderr: '', output: OUTPUT };

    expect(executionResultOutput(reply).shown.content).toBe(`stdout:\nran a\nSaved to file: ${OUTPUT.path}`);
    recordExecProvenance(provenance, {
      startedAt: new Date(), finishedAt: new Date(), workflowName: 'w', nodeId: 'a', input: '', reply, code: 'return 1',
    });
    expect(provenance).toHaveBeenCalledTimes(1);
  });
});
