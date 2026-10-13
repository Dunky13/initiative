import { createContext, type ReactNode, type RefObject, useCallback, useContext } from "react";
import { useTranslation } from "react-i18next";

import {
  type QueueItemRead,
  type QueueItemUpdate,
  SearchEntityType,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";
import { MemberSelect } from "@/components/members/MemberSearchSelect";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { type ItemFieldSave, useItemFieldSave } from "@/hooks/useFieldSave";
import { queueItemSaves } from "@/hooks/useQueues";
import { referenceRef } from "@/lib/smartChips";

import { DetailLayoutView } from "./DetailLayoutView";
import { PlacedProperties, type StoredRegions } from "./detailLayout";
import { FieldFrame, useFieldDraft } from "./editing";
import {
  DescriptionField,
  PlacedPropertyField,
  PropertiesField,
  TagsField,
  TitleField,
} from "./fieldEditors";
import { type FieldDef, PROPERTY_FIELD_PREFIX, useProjectLayoutEnv } from "./fields";
import { PluginFieldOnDetail } from "./plugins";
import { QUEUE_ITEM_FIELDS, QUEUE_ITEM_LAYOUT, queueItemFields } from "./queueItems";
import { LAYOUT_PARTS, type LayoutContext, type Parts } from "./tree";

/** What a queue item's detail shares with its parts, beside the item itself. */
export interface QueueItemLayoutContext {
  /** The server says the reader cannot change the item. */
  readOnly: boolean;
  queueId: number;
  initiativeId: number;
  /** Set when the detail is left on purpose, so an open draft does not hold it. */
  leaving: RefObject<boolean>;
  /** Reporting it, and the menu of what else can be done with it. */
  actions: ReactNode;
  /** Drawn in the layout editor, where nothing is changed. */
  preview?: boolean;
}

const DetailContext = createContext<QueueItemLayoutContext | null>(null);

const useQueueItemLayout = (): QueueItemLayoutContext => {
  const context = useContext(DetailContext);
  if (!context) throw new Error("A queue item detail part is drawn outside its detail");
  return context;
};

type EditorProps = { item: QueueItemRead; label: string };
type Save = ItemFieldSave<QueueItemRead, QueueItemUpdate>;

/** A field's save, for the queue the item is in. */
const useSave = (item: QueueItemRead, label: string): Save =>
  useItemFieldSave(queueItemSaves(useQueueItemLayout().queueId), item.id, label);

const LabelEditor = ({ item, label }: EditorProps) => {
  const { t } = useTranslation("queues");
  return (
    <TitleField
      id="queue-item-label"
      field="label"
      label={label}
      value={item.label}
      save={useSave(item, label)}
      readOnly={useQueueItemLayout().readOnly}
      placeholder={t("labelPlaceholder")}
    />
  );
};

/** Its notes, written and saved as a task's description is. */
const NotesEditor = ({ item, label }: EditorProps) => {
  const { t } = useTranslation("queues");
  const context = useQueueItemLayout();
  return (
    <DescriptionField
      field="notes"
      kind={queueItemSaves(context.queueId)}
      id={item.id}
      options={{}}
      label={label}
      htmlId="queue-item-notes"
      value={item.notes ?? null}
      readOnly={context.readOnly}
      initiativeId={context.initiativeId}
      subject={referenceRef(SearchEntityType.queue_item, item.id)}
      leaving={context.leaving}
      preview={context.preview}
      placeholder={t("notesPlaceholder")}
    />
  );
};

/** Where it stands in the queue: a higher number goes first. */
const PositionEditor = ({ item, label }: EditorProps) => {
  const { t } = useTranslation("queues");
  const { readOnly } = useQueueItemLayout();
  const save = useSave(item, label);
  const draft = useFieldDraft(
    String(item.position),
    (text) => save.save({ patch: { position: Number(text) }, shows: { position: Number(text) } }),
    Object.is,
    (text) => text.trim() !== "" && Number.isFinite(Number(text))
  );
  if (readOnly) {
    return (
      <div className="space-y-1">
        <p className="font-medium text-sm">{label}</p>
        <p className="text-sm">{item.position}</p>
      </div>
    );
  }
  return (
    <FieldFrame
      label={label}
      htmlFor="queue-item-position"
      save={save}
      changed={draft.changed}
      keys={draft.keys}
    >
      <Input
        id="queue-item-position"
        type="number"
        value={draft.value}
        onChange={(change) => draft.change(change.target.value)}
      />
      <p className="text-muted-foreground text-xs">{t("positionHelp")}</p>
    </FieldFrame>
  );
};

const ColorEditor = ({ item, label }: EditorProps) => {
  const { readOnly } = useQueueItemLayout();
  const save = useSave(item, label);
  if (readOnly) {
    return item.color ? (
      <div className="space-y-1">
        <p className="font-medium text-sm">{label}</p>
        <span className="block h-5 w-5 rounded-full border" style={{ backgroundColor: item.color }}>
          <span className="sr-only">{item.color}</span>
        </span>
      </div>
    ) : null;
  }
  return (
    <FieldFrame label={label} save={save}>
      <ColorPickerPopover
        value={item.color ?? ""}
        onChangeComplete={(color) => void save.save({ patch: { color }, shows: { color } })}
        triggerLabel={label}
        className="h-9"
      />
    </FieldFrame>
  );
};

/** Whether the queue shows it in its turns. */
const VisibleEditor = ({ item, label }: EditorProps) => {
  const { t } = useTranslation("queues");
  const { readOnly } = useQueueItemLayout();
  const save = useSave(item, label);
  if (readOnly) {
    return (
      <div className="space-y-1">
        <p className="font-medium text-sm">{label}</p>
        <p className="text-sm">{item.is_visible ? t("visible") : t("hidden")}</p>
      </div>
    );
  }
  return (
    <FieldFrame label={label} save={save}>
      <div className="flex items-center gap-3">
        <Switch
          checked={item.is_visible}
          onCheckedChange={(shown) =>
            void save.save({ patch: { is_visible: shown }, shows: { is_visible: shown } })
          }
          aria-label={label}
        />
        <span className="text-muted-foreground text-sm">
          {item.is_visible ? t("visible") : t("hidden")}
        </span>
      </div>
    </FieldFrame>
  );
};

/** The member whose turn it is, saved as they are picked. */
const PersonEditor = ({ item, label }: EditorProps) => {
  const { t } = useTranslation("queues");
  const { readOnly, queueId } = useQueueItemLayout();
  const save = useSave(item, label);
  if (readOnly) {
    return item.user ? (
      <div className="space-y-1">
        <p className="font-medium text-sm">{label}</p>
        <p className="text-sm">{item.user.display_name}</p>
      </div>
    ) : null;
  }
  return (
    <FieldFrame label={label} save={save}>
      <MemberSelect
        scope={{ type: "canOpen", tool: Tool.queue, id: queueId }}
        value={item.user_id ?? null}
        onChange={(userId) =>
          void save.save(
            { patch: { user_id: userId }, shows: { user_id: userId } },
            userId === null ? { patch: { user_id: item.user_id }, shows: item } : undefined
          )
        }
        selectedUser={item.user}
        placeholder={t("selectUser")}
        emptyMessage={t("noUser")}
        aria-label={label}
      />
    </FieldFrame>
  );
};

const TagsEditor = ({ item, label }: EditorProps) => {
  const { t } = useTranslation("queues");
  return (
    <TagsField
      label={label}
      tags={item.tags}
      save={useSave(item, label)}
      readOnly={useQueueItemLayout().readOnly}
      placeholder={t("tags")}
    />
  );
};

/** Each field's editor on the item's detail, by its id. */
const FIELD_EDITORS: Record<keyof typeof QUEUE_ITEM_FIELDS, (props: EditorProps) => ReactNode> = {
  label: LabelEditor,
  notes: NotesEditor,
  position: PositionEditor,
  color: ColorEditor,
  visible: VisibleEditor,
  person: PersonEditor,
  tags: TagsEditor,
};

const propsOf = (item: QueueItemRead, context: QueueItemLayoutContext) => ({
  kind: queueItemSaves(context.queueId),
  id: item.id,
  properties: item.properties,
  readOnly: context.readOnly,
  initiativeId: context.initiativeId,
  canOpen: { tool: Tool.queue, id: context.queueId },
});

/** One field of the item, by its id: its own, a property or a plug-in's. */
const QueueItemField = ({
  id,
  item,
  view,
}: {
  id: string;
  item: QueueItemRead;
  view: LayoutContext;
}) => {
  const { t } = useTranslation(["queues", "common"]);
  const context = useQueueItemLayout();
  if (id.startsWith(PROPERTY_FIELD_PREFIX)) {
    return (
      <PlacedPropertyField
        {...propsOf(item, context)}
        propertyId={Number(id.slice(PROPERTY_FIELD_PREFIX.length))}
      />
    );
  }
  const field = view.fields.get(id);
  if (field?.source === "plugin") return <PluginFieldOnDetail field={field} item={item} />;
  if (!Object.hasOwn(FIELD_EDITORS, id)) return null;
  const Editor = FIELD_EDITORS[id as keyof typeof FIELD_EDITORS];
  return (
    <Editor item={item} label={t(QUEUE_ITEM_FIELDS[id as keyof typeof FIELD_EDITORS].label)} />
  );
};

/** Its properties, but for those the layout places on their own. */
const Properties = ({ item }: { item: QueueItemRead }) => (
  <PropertiesField {...propsOf(item, useQueueItemLayout())} except={useContext(PlacedProperties)} />
);

const Relations = ({ item }: { item: QueueItemRead }) => {
  const { queueId, initiativeId, readOnly } = useQueueItemLayout();
  return (
    <ToolRelationsPanel
      tool={Tool.queue}
      entity={{ id: queueId, initiative_id: initiativeId }}
      target={{ type: SearchEntityType.queue_item, id: item.id }}
      canEdit={!readOnly}
      entityTitle={item.label}
    />
  );
};

const Actions = () => <>{useQueueItemLayout().actions}</>;

/** The parts a queue item's detail is drawn from. */
const QUEUE_ITEM_PARTS: Parts<QueueItemRead> = {
  ...LAYOUT_PARTS,
  field: (node, item, view) => (
    <QueueItemField id={String(node.props?.field)} item={item} view={view} />
  ),
  properties: (_node, item) => <Properties item={item} />,
  relations: (_node, item) => <Relations item={item} />,
  actions: () => <Actions />,
};

const QUEUE_ITEM_DETAIL_FIELDS = (plugins: FieldDef[]) => queueItemFields([], plugins);

// A queue item's detail draws no task, so nothing asks it for a task's address.
const NO_TASK = () => "";

/** A queue item's detail, drawn from its queue's layout, or as shipped. */
export const QueueItemLayoutView = ({
  item,
  context,
  layout,
  editing,
}: {
  item: QueueItemRead;
  context: QueueItemLayoutContext;
  layout?: StoredRegions | null;
  /** The layout is being edited: each part is marked with its path. */
  editing?: boolean;
}) => {
  const communityId = useActiveCommunityId();
  const env = useProjectLayoutEnv(useCallback(NO_TASK, []));
  return (
    // Another item's detail starts afresh, with none of this one's drafts.
    <DetailContext.Provider key={`${communityId}:${item.id}`} value={context}>
      <DetailLayoutView
        spec={QUEUE_ITEM_LAYOUT}
        item={item}
        initiativeId={context.initiativeId}
        layout={layout}
        editing={editing}
        fields={QUEUE_ITEM_DETAIL_FIELDS}
        env={env}
        parts={QUEUE_ITEM_PARTS}
      />
    </DetailContext.Provider>
  );
};
