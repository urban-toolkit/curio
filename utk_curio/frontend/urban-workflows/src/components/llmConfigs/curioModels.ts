import type { LlmDeploymentEndpoint } from "../../api/llmConfigsApi";

/**
 * This Curio's own models, as API Settings offers them: the operator's
 * endpoint file lists them, and a user picks one as the default or for an
 * agent instead of adding a configuration.
 *
 * A pick is `curio:` followed by the JSON pair `["<endpoint name>", "<model>"]`,
 * the text the server stores (`llm_configs.pick_choice`), so any name, with
 * spaces, colons or slashes, round-trips. The value `"deployment"` is Curio's
 * default: the first endpoint's first model, whatever the file lists first.
 */

/** The choice of Curio's default, for the default and for an agent. */
export const CURIO_DEFAULT_CHOICE = "deployment";
export const CURIO_DEFAULT_LABEL = "Curio's default";
/** The name of a Curio row on the API keys tab. */
export const CURIO_ROW_NAME = "Curio";
export const CURIO_DEFAULT_BADGE = "Curio default";
export const MY_CONFIGURATIONS = "My configurations";
export const NO_LONGER_OFFERED = "(no longer offered)";

const PICK_PREFIX = "curio:";

export interface CurioPick {
  endpoint: string;
  model: string;
}

/** The choice of *model* on this Curio's endpoint named *endpoint*. */
export function pickValue(endpoint: string, model: string): string {
  return PICK_PREFIX + JSON.stringify([endpoint, model]);
}

/** The endpoint and model a choice picks, or null when it is not a pick. */
export function parsePick(choice: string | null | undefined): CurioPick | null {
  if (!choice || !choice.startsWith(PICK_PREFIX)) return null;
  try {
    const pair: unknown = JSON.parse(choice.slice(PICK_PREFIX.length));
    if (
      Array.isArray(pair) && pair.length === 2
      && typeof pair[0] === "string" && pair[0]
      && typeof pair[1] === "string" && pair[1]
    ) {
      return { endpoint: pair[0], model: pair[1] };
    }
  } catch {
    // Not a pick this page can read: shown as no longer offered.
  }
  return null;
}

export function isPick(choice: string | null | undefined): boolean {
  return Boolean(choice && choice.startsWith(PICK_PREFIX));
}

/** Whether one of *endpoints* still lists what *choice* picks. */
export function isOffered(choice: string, endpoints: LlmDeploymentEndpoint[]): boolean {
  const pick = parsePick(choice);
  return Boolean(
    pick && endpoints.some((endpoint) => endpoint.name === pick.endpoint && endpoint.models.includes(pick.model)),
  );
}

/** The heading of one endpoint's models in a select. */
export function curioGroupLabel(endpointName: string): string {
  return `Curio · ${endpointName}`;
}

/** The line under a Curio row's name. */
export function providedBy(endpointName: string): string {
  return `Provided by ${endpointName}`;
}

/**
 * How a choice of one of Curio's models that the file no longer offers is
 * shown, so it can be picked again; null for any other choice.
 */
export function goneLabel(choice: string): string | null {
  const pick = parsePick(choice);
  if (pick) return `${curioGroupLabel(pick.endpoint)}: ${pick.model} ${NO_LONGER_OFFERED}`;
  if (isPick(choice)) return `A Curio model ${NO_LONGER_OFFERED}`;
  if (choice === CURIO_DEFAULT_CHOICE) return `${CURIO_DEFAULT_LABEL} ${NO_LONGER_OFFERED}`;
  return null;
}
