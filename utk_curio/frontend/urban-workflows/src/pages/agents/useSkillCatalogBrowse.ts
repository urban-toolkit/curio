import { useCallback, useEffect, useMemo, useState } from "react";

import { skillServes, skillsApi, type SkillCard } from "../../services/agents";

/** Which skills the rail's Skills section shows: all, or the core ones. */
export type SkillBrowseFilter = "all" | "core";

export interface SkillCatalogBrowseState {
  loading: boolean;
  /** Every skill Curio ships, unfiltered. */
  skills: SkillCard[];
  /** The skills after the search and the rail's filter, by name. */
  filtered: SkillCard[];
  coreCount: number;
  /** `undefined` = nothing chosen yet (show the first); `null` = closed. */
  selectedName: string | null | undefined;
  setSelectedName: (name: string | null | undefined) => void;
  selectedSkill: SkillCard | null;
  /** Read the skills again: an agent's skills changed, so their users did. */
  reload: () => Promise<void>;
}

/** Whether *skill* matches the search *query*: its name, its description or
 *  what it serves. */
export function matchesSkillSearch(skill: SkillCard, query: string): boolean {
  const wanted = query.trim().toLowerCase();
  if (!wanted) return true;
  return [skill.name, skill.description, ...skillServes(skill)].some((text) =>
    text.toLowerCase().includes(wanted),
  );
}

/**
 * The skills the Agent Catalog page lists beside its agents, read once on
 * arrival so the rail can count them. A feed beside the agents', never a
 * precondition: a failure leaves the Skills section empty, and the agents as
 * they are.
 */
export function useSkillCatalogBrowse(search: string, filter: SkillBrowseFilter): SkillCatalogBrowseState {
  const [skills, setSkills] = useState<SkillCard[]>([]);
  const [loading, setLoading] = useState(true);
  // Tri-state, as the agents' selection is: `undefined` falls back to the
  // first row, `null` is a drawer the user closed.
  const [selectedName, setSelectedName] = useState<string | null | undefined>(undefined);

  const reload = useCallback(async () => {
    try {
      const resp = await skillsApi.list();
      setSkills(resp.skills ?? []);
    } catch (err) {
      console.warn("[agent-catalog] could not read the skills:", err);
      setSkills([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const filtered = useMemo(
    () =>
      skills
        .filter((skill) => (filter === "core" ? skill.core : true))
        .filter((skill) => matchesSkillSearch(skill, search))
        .sort((a, b) => a.name.localeCompare(b.name)),
    [skills, filter, search],
  );

  const selectedSkill = useMemo(() => {
    if (selectedName === null) return null;
    if (selectedName != null) return filtered.find((skill) => skill.name === selectedName) ?? null;
    return filtered[0] ?? null;
  }, [filtered, selectedName]);

  // A chosen skill that leaves the list drops back to the first row; a
  // closed drawer stays closed.
  useEffect(() => {
    if (selectedName == null) return;
    if (!filtered.some((skill) => skill.name === selectedName)) setSelectedName(undefined);
  }, [filtered, selectedName]);

  return {
    loading,
    skills,
    filtered,
    coreCount: skills.filter((skill) => skill.core).length,
    selectedName,
    setSelectedName,
    selectedSkill,
    reload,
  };
}
