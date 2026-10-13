import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import {
  type DetailLayoutSpec,
  PlacedProperties,
  placedProperties,
  type StoredRegions,
} from "./detailLayout";
import { indexPaths } from "./draft";
import type { FieldDef, LayoutEnv } from "./fields";
import {
  FieldsInParts,
  fieldsInParts,
  pluginFields,
  shippedPluginParts,
  usePluginsOnItems,
} from "./plugins";
import { type LayoutContext, type Parts, renderNode } from "./tree";

/**
 * An item's detail, drawn from its stored layout or as shipped, with the
 * plug-ins placed in its initiative drawn on it: what every item's page and
 * the layout editor's preview of it draw.
 */
export const DetailLayoutView = <I,>({
  spec,
  item,
  initiativeId,
  layout,
  editing,
  fields,
  env,
  parts,
}: {
  spec: DetailLayoutSpec;
  item: I;
  /** Where the plug-ins drawn on it are placed; none where it has none. */
  initiativeId: number | null | undefined;
  layout?: StoredRegions | null;
  /** The layout is being edited: each part is marked with its path, which
   *  the editor's detail tree shares. */
  editing?: boolean;
  /** Its fields, given the plug-ins'. */
  fields: (plugins: FieldDef[]) => ReadonlyMap<string, FieldDef>;
  env: LayoutEnv;
  parts: Parts<I>;
}) => {
  const { i18n } = useTranslation();
  const plugins = usePluginsOnItems(initiativeId, true, spec.kind);
  const tree = useMemo(
    () => spec.tree(layout, shippedPluginParts(plugins)),
    [spec, layout, plugins]
  );
  const placed = useMemo(() => placedProperties(tree), [tree]);
  const inParts = useMemo(() => fieldsInParts(tree, plugins), [tree, plugins]);
  const view = useMemo<LayoutContext>(
    () => ({
      fields: fields(pluginFields(plugins, i18n.language)),
      plugins,
      variant: "detail",
      env,
      editing: editing ? indexPaths(tree) : undefined,
    }),
    [fields, plugins, i18n.language, env, editing, tree]
  );
  return (
    <PlacedProperties.Provider value={placed}>
      <FieldsInParts.Provider value={inParts}>
        {renderNode(tree, item, view, parts)}
      </FieldsInParts.Provider>
    </PlacedProperties.Provider>
  );
};
