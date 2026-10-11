/**
 * What the Access tab can be opened with: one community, one operations case,
 * or both already chosen in one of its forms. The Communities tab links here
 * from a row, so the community arrives picked rather than typed; a case links
 * here with itself, and the community it is about where it names one. The form
 * it was meant for says which of the two picks them up.
 */

export type AccessGrantsForm = "request" | "break_glass";

/** The content rungs a request may start on. */
export type AccessGrantsLevel = "read" | "read_write" | "moderate";
const LEVELS: readonly AccessGrantsLevel[] = ["read", "read_write", "moderate"];

export interface AccessGrantsSearch {
  /** The community the form starts with. */
  community?: number;
  /** Its name, carried along so the picker can show it without a lookup. */
  name?: string;
  /** The operations case the grant is for, by its task id. */
  case?: number;
  /** Which form it is for. */
  form?: AccessGrantsForm;
  /** The content rung the request form starts on: what the errand that
   *  linked here needs, such as Moderate for content the platform holds. */
  level?: AccessGrantsLevel;
}

const positiveId = (value: unknown): number | undefined => {
  const id = Number(value);
  return Number.isInteger(id) && id > 0 ? id : undefined;
};

export const validateAccessGrantsSearch = (search: Record<string, unknown>): AccessGrantsSearch => {
  const community = positiveId(search.community);
  const caseTaskId = positiveId(search.case);
  if (community === undefined && caseTaskId === undefined) return {};
  const form = search.form === "request" || search.form === "break_glass" ? search.form : undefined;
  // A name means nothing without the community it names.
  const name =
    community !== undefined && typeof search.name === "string" && search.name.trim()
      ? search.name
      : undefined;
  const level = LEVELS.find((rung) => rung === search.level);
  return {
    ...(community !== undefined ? { community } : {}),
    ...(name ? { name } : {}),
    ...(caseTaskId !== undefined ? { case: caseTaskId } : {}),
    ...(form ? { form } : {}),
    ...(level ? { level } : {}),
  };
};
