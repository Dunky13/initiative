import { useMemo } from "react";

import type { PropertySummary, PropertyTarget, Tool } from "@/api/generated/initiativeAPI.schemas";
import { propertySaves, useHeldProperties } from "@/hooks/useProperties";
import { PropertiesField } from "@/lib/layouts/fieldEditors";

const NONE: PropertySummary[] = [];

export interface PropertyPanelProps {
  target: PropertyTarget;
  entityId: number;
  /** The row's properties as the server last sent them. */
  saved: PropertySummary[] | undefined;
  /** The initiative whose definitions may be added. */
  initiativeId: number | null;
  /** Whose people a person-valued property may name: who can open this tool. */
  canOpen: { tool: Tool; id: number | null | undefined };
  disabled?: boolean;
}

/**
 * The properties on one tool or sub-tool, under a heading its host draws, each
 * saved on its own as an item's page saves them.
 *
 * Keyed by the row: a host that stays on screen while it moves to another row
 * (a wiki page's drawer, a file opened from a file) gets a fresh one, so one
 * row's edits never reach the next.
 */
export const PropertyPanel = (props: PropertyPanelProps) => (
  <RowProperties key={`${props.target}:${props.entityId}`} {...props} />
);

const RowProperties = ({
  target,
  entityId,
  saved = NONE,
  initiativeId,
  canOpen,
  disabled = false,
}: PropertyPanelProps) => {
  const kind = useMemo(() => propertySaves(target), [target]);
  return (
    <PropertiesField
      kind={kind}
      id={entityId}
      properties={useHeldProperties(kind, entityId, saved)}
      readOnly={disabled}
      initiativeId={initiativeId}
      canOpen={canOpen}
      hideLabel
    />
  );
};
