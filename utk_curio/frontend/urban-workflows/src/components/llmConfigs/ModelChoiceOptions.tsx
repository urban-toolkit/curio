import React from "react";
import type { LlmListing } from "../../api/llmConfigsApi";
import {
  CURIO_DEFAULT_CHOICE,
  CURIO_DEFAULT_LABEL,
  MY_CONFIGURATIONS,
  curioGroupLabel,
  goneLabel,
  isOffered,
  isPick,
  parsePick,
  pickValue,
} from "./curioModels";

/**
 * A stored choice as the select's value: a pick written the way the options
 * write it, so the server's text and the page's always match.
 */
export function choiceValue(choice: string | null | undefined): string {
  if (!choice) return "";
  const pick = parsePick(choice);
  return pick ? pickValue(pick.endpoint, pick.model) : choice;
}

/** Whether the select still offers *choice*. */
function stillOffered(choice: string, listing: LlmListing): boolean {
  if (isPick(choice)) return isOffered(choice, listing.deployment.endpoints ?? []);
  if (choice === CURIO_DEFAULT_CHOICE) return Boolean(listing.deployment.model);
  return true;
}

/**
 * What the default and each agent may run on, in order: Curio's default with
 * its model, each of this Curio's endpoints with its models, then the
 * account's own configurations. Without an endpoint file only the account's
 * own are offered. A choice of one of Curio's models that the file no longer
 * offers is shown, disabled, so it can be picked again.
 */
export const ModelChoiceOptions: React.FC<{
  listing: LlmListing;
  /** The value Curio's default takes here: "" for the default, "deployment" for an agent. */
  curioDefaultValue: string;
  /** The stored choice. */
  current: string | null;
}> = ({ listing, curioDefaultValue, current }) => {
  const { deployment, configs } = listing;
  const endpoints = deployment.endpoints ?? [];
  const gone = current && !stillOffered(current, listing) ? goneLabel(current) : null;
  return (
    <>
      {gone ? (
        <option value={choiceValue(current)} disabled>
          {gone}
        </option>
      ) : null}
      {deployment.model ? (
        <option value={curioDefaultValue}>
          {CURIO_DEFAULT_LABEL}: {deployment.model}
        </option>
      ) : null}
      {endpoints.map((endpoint) => (
        <optgroup key={endpoint.name} label={curioGroupLabel(endpoint.name)}>
          {endpoint.models.map((model) => (
            <option key={model} value={pickValue(endpoint.name, model)}>
              {model}
            </option>
          ))}
        </optgroup>
      ))}
      {configs.length ? (
        <optgroup label={MY_CONFIGURATIONS}>
          {configs.map((config) => (
            <option key={config.id} value={config.id}>
              {config.label}: {config.model}
            </option>
          ))}
        </optgroup>
      ) : null}
    </>
  );
};
