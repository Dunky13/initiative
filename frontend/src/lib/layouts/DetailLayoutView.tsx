import type { FlatNamespace } from "i18next";
import {
  type ComponentType,
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
} from "react";
import { useTranslation } from "react-i18next";

import type {
  PropertyDefinitionRead,
  PropertySummary,
  SearchEntityType,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { EntityLinkField } from "@/components/entities/EntityLinkField";
import type { RelationsLayout } from "@/components/entities/RelationsSection";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { type FieldSaveKind, ItemDraftContext } from "@/hooks/useFieldSave";
import { useCommunityPath } from "@/lib/communityUrl";
import type { LinkedRef } from "@/lib/relationships";
import type { ToolRelationEntity } from "@/lib/tools";
import type { TranslateFn } from "@/types/i18n";

import {
  type DetailLayoutSpec,
  PlacedProperties,
  placedProperties,
  type StoredRegions,
} from "./detailLayout";
import { indexPaths } from "./draft";
import { PlacedPropertyField, PropertiesField } from "./fieldEditors";
import { type FieldDef, PROPERTY_FIELD_PREFIX, useProjectLayoutEnv } from "./fields";
import {
  FieldsInParts,
  fieldsInParts,
  PluginFieldOnDetail,
  type PluginItem,
  pluginFields,
  shippedPluginParts,
  usePluginsOnItems,
} from "./plugins";
import { LAYOUT_PARTS, type LayoutContext, type LayoutNode, type Parts, renderNode } from "./tree";

/** What every kind of item drawn on a detail has. */
type Item = PluginItem & { properties: PropertySummary[] };

/** Where one item lives, which the parts every item's detail has read. */
export interface ItemHome<I, P> {
  /** How its fields and properties are saved. */
  saves: FieldSaveKind<I, P>;
  /** The server says the reader cannot change it. */
  readOnly: boolean;
  /** Its initiative, which holds its properties' definitions and places its
   *  plug-ins; none for a community's own tool. */
  initiativeId: number | null;
  /** The tool it is opened in: whose members a person-valued property names. */
  canOpen: { tool: Tool; id: number };
  /** What its links are kept under: the tool entity, and the item itself
   *  where it is not that entity. */
  links: {
    entity: ToolRelationEntity;
    target?: { type: SearchEntityType; id: number };
    title?: string;
    layout?: RelationsLayout;
  };
  /** The menu of what else can be done with it. */
  actions?: ReactNode;
}

/**
 * One kind of item's detail: its layout, its own fields' editors and parts,
 * and where an item of it lives. The fields placed from its initiative's
 * properties and its plug-ins, and its properties, links and actions, are
 * drawn alike for every kind.
 */
export interface DetailKind<I extends Item, C, P> {
  spec: DetailLayoutSpec;
  /** Its fields, given its initiative's properties and the plug-ins'. */
  fields: (definitions: PropertyDefinitionRead[], plugins: FieldDef[]) => Map<string, FieldDef>;
  /** Where its fields' labels are worded. */
  namespaces: readonly FlatNamespace[];
  /** Its own fields' editors, by field id. */
  editors: Readonly<Record<string, ComponentType<{ item: I; label: string }>>>;
  /** Its own parts, beside those every item has. */
  parts?: Parts<I>;
  home: (item: I, context: C) => ItemHome<I, P>;
  /** Where a task drawn on it opens, inside its community. */
  taskRoute?: (item: I, context: C, taskId: number) => string;
  /** Holds what its parts keep across a change of layout. */
  Shell?: ComponentType<{ context: C; children: ReactNode }>;
  /** Its own parts an item being added draws: those that need nothing saved. */
  addingParts?: readonly string[];
}

interface Drawn {
  detail: DetailKind<Item, unknown, unknown>;
  context: unknown;
  home: ItemHome<Item, unknown>;
}

const DrawnItem = createContext<Drawn | null>(null);

const useDrawn = (): Drawn => {
  const drawn = useContext(DrawnItem);
  if (!drawn) throw new Error("An item's detail part is drawn outside its detail");
  return drawn;
};

/** What the page drawing the item gave its detail. */
export const useItemContext = <C,>(): C => useDrawn().context as C;

const propertiesOf = (item: Item, home: ItemHome<Item, unknown>) => ({
  kind: home.saves,
  id: item.id,
  properties: item.properties,
  readOnly: home.readOnly,
  initiativeId: home.initiativeId,
  canOpen: home.canOpen,
});

/** One field, by its id: one of its initiative's properties, a plug-in's, or
 *  the kind's own. */
const ItemField = ({ id, item, view }: { id: string; item: Item; view: LayoutContext }) => {
  const { detail, home } = useDrawn();
  const t = useTranslation(detail.namespaces).t as TranslateFn;
  if (id.startsWith(PROPERTY_FIELD_PREFIX)) {
    return home.initiativeId === null ? null : (
      <PlacedPropertyField
        {...propertiesOf(item, home)}
        propertyId={Number(id.slice(PROPERTY_FIELD_PREFIX.length))}
      />
    );
  }
  const field = view.fields.get(id);
  if (!field) return null;
  // A plug-in's value is the plug-in's to change.
  if (field.source === "plugin") return <PluginFieldOnDetail field={field} item={item} />;
  const Editor = Object.hasOwn(detail.editors, id) ? detail.editors[id] : undefined;
  return Editor ? <Editor item={item} label={t(field.label)} /> : null;
};

/** Its properties, but for those the layout places on their own. A reader
 *  sees none where it holds none; a community's own tool has none to offer. */
const ItemProperties = ({ item }: { item: Item }) => {
  const { home } = useDrawn();
  const placed = useContext(PlacedProperties);
  if (home.initiativeId === null) return null;
  if (home.readOnly && item.properties.every((each) => placed.has(each.property_id))) return null;
  return <PropertiesField {...propertiesOf(item, home)} except={placed} />;
};

const ItemRelations = () => {
  const { home } = useDrawn();
  return (
    <ToolRelationsPanel
      tool={home.canOpen.tool}
      entity={home.links.entity}
      target={home.links.target}
      canEdit={!home.readOnly}
      entityTitle={home.links.title}
      defaultLayout={home.links.layout}
    />
  );
};

const ItemActions = () => <>{useDrawn().home.actions}</>;

/** The links an item being added is to be made with. */
export const AddingLinks = createContext<{
  value: LinkedRef[];
  onChange: (next: LinkedRef[]) => void;
} | null>(null);

/** What an item being added is to be linked to, written once it is made. */
const LinksToMake = () => {
  const { t } = useTranslation("relations");
  const { home } = useDrawn();
  const links = useContext(AddingLinks);
  if (!links || home.initiativeId === null) return null;
  return (
    <EntityLinkField
      label={t("groups.attached.title")}
      initiativeId={home.initiativeId}
      value={links.value}
      onChange={links.onChange}
    />
  );
};

/** The parts every item's detail has, then its kind's own. One being added
 *  draws what needs nothing saved: its fields and properties, the links to
 *  make, and the parts of its kind's own it names; nothing a plug-in draws
 *  and nothing it could be done with yet. */
const partsOf = <I extends Item>(own: Parts<I> = {}, adding?: readonly string[]): Parts<I> => {
  const parts: Parts<I> = {
    ...LAYOUT_PARTS,
    field: (node: LayoutNode, item: I, view: LayoutContext) => (
      <ItemField id={String(node.props?.field)} item={item} view={view} />
    ),
    properties: (_node: LayoutNode, item: I) => <ItemProperties item={item} />,
    relations: () => (adding ? <LinksToMake /> : <ItemRelations />),
    actions: () => <ItemActions />,
    ...own,
  };
  if (!adding) return parts;
  return Object.fromEntries(
    Object.entries(parts).filter(([type]) =>
      Object.hasOwn(own, type) ? adding.includes(type) : type !== "plugin" && type !== "actions"
    )
  );
};

type ViewProps<I extends Item, C, P> = {
  detail: DetailKind<I, C, P>;
  item: I;
  context: C;
  layout?: StoredRegions | null;
  /** The layout is being edited: each part is marked with its path, which
   *  the editor's detail tree shares. */
  editing?: boolean;
};

/**
 * An item's detail, drawn from its stored layout or as shipped, with the
 * plug-ins placed in its initiative drawn on it: what every item's page and
 * the layout editor's preview of it draw. Another item's detail starts
 * afresh, with none of this one's drafts.
 */
export const DetailLayoutView = <I extends Item, C, P>(props: ViewProps<I, C, P>) => (
  <ItemDetail key={`${useActiveCommunityId()}:${props.item.id}`} {...props} />
);

const ItemDetail = <I extends Item, C, P>({
  detail,
  item,
  context,
  layout,
  editing,
}: ViewProps<I, C, P>) => {
  const { i18n } = useTranslation();
  const home = detail.home(item, context);
  const { spec, taskRoute, Shell } = detail;
  const gp = useCommunityPath();
  const taskHref = useCallback(
    (taskId: number) => (taskRoute ? gp(taskRoute(item, context, taskId)) : ""),
    [taskRoute, gp, item, context]
  );
  const env = useProjectLayoutEnv(taskHref);
  const plugins = usePluginsOnItems(home.initiativeId, true, spec.kind);
  const tree = useMemo(
    () => spec.tree(layout, shippedPluginParts(plugins)),
    [spec, layout, plugins]
  );
  const placed = useMemo(() => placedProperties(tree), [tree]);
  const inParts = useMemo(() => fieldsInParts(tree, plugins), [tree, plugins]);
  const view = useMemo<LayoutContext>(
    () => ({
      fields: detail.fields([], pluginFields(plugins, i18n.language)),
      plugins,
      variant: "detail",
      env,
      editing: editing ? indexPaths(tree) : undefined,
    }),
    [detail, plugins, i18n.language, env, editing, tree]
  );
  const adding = useContext(ItemDraftContext) !== null;
  const parts = useMemo(
    () => partsOf(detail.parts, adding ? (detail.addingParts ?? []) : undefined),
    [detail, adding]
  );
  // The parts every item has read the kind whatever its item is.
  const drawn = { detail, context, home } as unknown as Drawn;
  const body = (
    <PlacedProperties.Provider value={placed}>
      <FieldsInParts.Provider value={inParts}>
        {renderNode(tree, item, view, parts)}
      </FieldsInParts.Provider>
    </PlacedProperties.Provider>
  );
  return (
    <DrawnItem.Provider value={drawn}>
      {Shell ? <Shell context={context}>{body}</Shell> : body}
    </DrawnItem.Provider>
  );
};
