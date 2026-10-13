import { Minus, Plus } from "lucide-react";
import { createContext, type ReactNode, type RefObject, useCallback, useContext } from "react";
import { useTranslation } from "react-i18next";

import {
  type CounterRead,
  type CounterUpdate,
  CounterViewMode,
  SearchEntityType,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";
import { CounterView } from "@/components/initiativeTools/counters/views/CounterView";
import { Button } from "@/components/ui/button";
import { ColorPickerPopover } from "@/components/ui/color-picker-popover";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { counterSaves, type SteppedCount, useCounterGroup, useSetCount } from "@/hooks/useCounters";
import { type ItemFieldSave, useItemFieldSave } from "@/hooks/useFieldSave";
import { isAtMax, isAtMin } from "@/lib/counter-math";

import { COUNTER_FIELDS, COUNTER_LAYOUT, counterFields } from "./counters";
import { DetailLayoutView } from "./DetailLayoutView";
import { PlacedProperties, type StoredRegions } from "./detailLayout";
import { FieldFrame, useFieldDraft } from "./editing";
import { PlacedPropertyField, PropertiesField, TitleField } from "./fieldEditors";
import { type FieldDef, PROPERTY_FIELD_PREFIX, useProjectLayoutEnv } from "./fields";
import { PluginFieldOnDetail } from "./plugins";
import { LAYOUT_PARTS, type LayoutContext, type Parts } from "./tree";

/** What a counter's detail shares with its parts, beside the counter itself. */
export interface CounterLayoutContext {
  /** The server says the reader cannot change the counter. */
  readOnly: boolean;
  groupId: number;
  /** The group's initiative; a community's own group has none, and so no
   *  properties or links. */
  initiativeId: number | null;
  /** Set when the detail is left on purpose. */
  leaving: RefObject<boolean>;
  /** The menu of what else can be done with it. */
  actions: ReactNode;
  /** The page's stepper, which every step of the group's counters goes
   *  through; none in the layout editor, where nothing is changed. */
  stepper?: SteppedCount;
}

const DetailContext = createContext<CounterLayoutContext | null>(null);

const useCounterLayout = (): CounterLayoutContext => {
  const context = useContext(DetailContext);
  if (!context) throw new Error("A counter detail part is drawn outside its detail");
  return context;
};

type EditorProps = { counter: CounterRead; label: string };
type Save = ItemFieldSave<CounterRead, CounterUpdate>;

/** A field's save, for the group the counter is in. */
const useSave = (counter: CounterRead, label: string): Save =>
  useItemFieldSave(counterSaves(useCounterLayout().groupId), counter.id, label);

const NameEditor = ({ counter, label }: EditorProps) => {
  const { t } = useTranslation("counterGroups");
  return (
    <TitleField
      id="counter-name"
      field="name"
      label={label}
      value={counter.name}
      save={useSave(counter, label)}
      readOnly={useCounterLayout().readOnly}
      placeholder={t("counterNamePlaceholder")}
    />
  );
};

const ColorEditor = ({ counter, label }: EditorProps) => {
  const { readOnly } = useCounterLayout();
  const save = useSave(counter, label);
  if (readOnly) {
    return counter.color ? (
      <div className="space-y-1">
        <p className="font-medium text-sm">{label}</p>
        <span
          className="block h-5 w-5 rounded-full border"
          style={{ backgroundColor: counter.color }}
        >
          <span className="sr-only">{counter.color}</span>
        </span>
      </div>
    ) : null;
  }
  return (
    <FieldFrame label={label} save={save}>
      <ColorPickerPopover
        value={counter.color ?? ""}
        onChangeComplete={(color) => void save.save({ patch: { color }, shows: { color } })}
        triggerLabel={label}
        className="h-9"
      />
    </FieldFrame>
  );
};

/** Which of the counter's numbers a field edits, and whether it may be empty. */
const NUMBERS = {
  min: { key: "min", optional: true },
  max: { key: "max", optional: true },
  step: { key: "step", optional: false },
  start: { key: "initial_count", optional: false },
} as const;

/** One of the numbers it counts by: a bound, its step or where it starts. A
 *  bound left empty is no bound. */
const NumberEditor = ({
  counter,
  label,
  number,
}: EditorProps & { number: keyof typeof NUMBERS }) => {
  const { readOnly } = useCounterLayout();
  const save = useSave(counter, label);
  const { key, optional } = NUMBERS[number];
  const saved = counter[key] ?? "";
  const draft = useFieldDraft(
    saved,
    (text) => {
      const value = text.trim() === "" ? null : text.trim();
      return save.save({ patch: { [key]: value }, shows: { [key]: value } });
    },
    Object.is,
    (text) => (text.trim() === "" ? optional : Number.isFinite(Number(text)) && text.trim() !== "")
  );
  const id = `counter-${number}`;
  if (readOnly) {
    return saved ? (
      <div className="space-y-1">
        <p className="font-medium text-sm">{label}</p>
        <p className="text-sm tabular-nums">{saved}</p>
      </div>
    ) : null;
  }
  return (
    <FieldFrame label={label} htmlFor={id} save={save} changed={draft.changed} keys={draft.keys}>
      <Input
        id={id}
        type="number"
        inputMode="decimal"
        value={draft.value}
        onChange={(change) => draft.change(change.target.value)}
      />
    </FieldFrame>
  );
};

/** How it is drawn: a number, a bar or a clock. A bar and a clock need both
 *  bounds. */
const ViewEditor = ({ counter, label }: EditorProps) => {
  const { t } = useTranslation("counterGroups");
  const { readOnly } = useCounterLayout();
  const save = useSave(counter, label);
  const bounded = counter.min != null && counter.max != null;
  const names: Record<CounterViewMode, string> = {
    [CounterViewMode.number]: t("viewModeNumber"),
    [CounterViewMode.progress_bar]: t("viewModeProgressBar"),
    [CounterViewMode.segmented_clock]: t("viewModeSegmentedClock"),
  };
  if (readOnly) {
    return (
      <div className="space-y-1">
        <p className="font-medium text-sm">{label}</p>
        <p className="text-sm">{names[counter.view_mode]}</p>
      </div>
    );
  }
  return (
    <FieldFrame label={label} htmlFor="counter-view-mode" save={save}>
      <Select
        value={counter.view_mode}
        onValueChange={(mode) =>
          void save.save({
            patch: { view_mode: mode as CounterViewMode },
            shows: { view_mode: mode as CounterViewMode },
          })
        }
      >
        <SelectTrigger id="counter-view-mode">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {Object.values(CounterViewMode).map((mode) => (
            <SelectItem
              key={mode}
              value={mode}
              disabled={mode !== CounterViewMode.number && !bounded}
            >
              {names[mode]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {bounded ? null : (
        <p className="text-muted-foreground text-xs">{t("viewModeRequiresBounds")}</p>
      )}
    </FieldFrame>
  );
};

/** Each field's editor on the counter's detail, by its id. */
const FIELD_EDITORS: Record<keyof typeof COUNTER_FIELDS, (props: EditorProps) => ReactNode> = {
  name: NameEditor,
  color: ColorEditor,
  min: (props) => <NumberEditor {...props} number="min" />,
  max: (props) => <NumberEditor {...props} number="max" />,
  step: (props) => <NumberEditor {...props} number="step" />,
  start: (props) => <NumberEditor {...props} number="start" />,
  view: ViewEditor,
};

const propsOf = (counter: CounterRead, context: CounterLayoutContext) => ({
  kind: counterSaves(context.groupId),
  id: counter.id,
  properties: counter.properties,
  readOnly: context.readOnly,
  initiativeId: context.initiativeId,
  canOpen: { tool: Tool.counter_group, id: context.groupId },
});

/** One field of the counter, by its id: its own, a property or a plug-in's. */
const CounterField = ({
  id,
  counter,
  view,
}: {
  id: string;
  counter: CounterRead;
  view: LayoutContext;
}) => {
  const { t } = useTranslation(["counterGroups", "common"]);
  const context = useCounterLayout();
  if (id.startsWith(PROPERTY_FIELD_PREFIX)) {
    return (
      <PlacedPropertyField
        {...propsOf(counter, context)}
        propertyId={Number(id.slice(PROPERTY_FIELD_PREFIX.length))}
      />
    );
  }
  const field = view.fields.get(id);
  if (field?.source === "plugin") return <PluginFieldOnDetail field={field} item={counter} />;
  if (!Object.hasOwn(FIELD_EDITORS, id)) return null;
  const Editor = FIELD_EDITORS[id as keyof typeof FIELD_EDITORS];
  return (
    <Editor counter={counter} label={t(COUNTER_FIELDS[id as keyof typeof FIELD_EDITORS].label)} />
  );
};

/** Its properties, but for those the layout places on their own. A
 *  community's own group has no definitions to offer. */
const Properties = ({ counter }: { counter: CounterRead }) => {
  const context = useCounterLayout();
  const placed = useContext(PlacedProperties);
  if (context.initiativeId === null) return null;
  return <PropertiesField {...propsOf(counter, context)} except={placed} />;
};

const Relations = ({ counter }: { counter: CounterRead }) => {
  const { groupId, initiativeId, readOnly } = useCounterLayout();
  return (
    <ToolRelationsPanel
      tool={Tool.counter_group}
      entity={{ id: groupId, initiative_id: initiativeId }}
      target={{ type: SearchEntityType.counter, id: counter.id }}
      canEdit={!readOnly}
      entityTitle={counter.name}
    />
  );
};

/** Its count, stepped or set as on its group's page. Read from the group,
 *  where a step shows at once. */
const Count = ({ counter }: { counter: CounterRead }) => {
  const { t } = useTranslation("counterGroups");
  const { groupId, readOnly, stepper } = useCounterLayout();
  const live =
    useCounterGroup(groupId).data?.counters.find((each) => each.id === counter.id) ?? counter;
  const setCount = useSetCount(groupId);
  const locked = readOnly || !stepper;
  return (
    <div className="flex items-center justify-center gap-4 rounded-lg border bg-card p-4">
      <Button
        type="button"
        variant="outline"
        size="icon"
        onClick={() => stepper?.decrement(live)}
        disabled={locked || isAtMin(live)}
        aria-label={t("decrement")}
      >
        <Minus className="h-4 w-4" />
      </Button>
      <CounterView
        counter={live}
        disabled={locked}
        textColor="currentColor"
        onCommit={(value) => {
          stepper?.cancel(live.id);
          setCount.mutate({ counterId: live.id, data: { count: value } });
        }}
        size="lg"
      />
      <Button
        type="button"
        variant="outline"
        size="icon"
        onClick={() => stepper?.increment(live)}
        disabled={locked || isAtMax(live)}
        aria-label={t("increment")}
      >
        <Plus className="h-4 w-4" />
      </Button>
    </div>
  );
};

const Actions = () => <>{useCounterLayout().actions}</>;

/** The parts a counter's detail is drawn from. */
const COUNTER_PARTS: Parts<CounterRead> = {
  ...LAYOUT_PARTS,
  field: (node, counter, view) => (
    <CounterField id={String(node.props?.field)} counter={counter} view={view} />
  ),
  properties: (_node, counter) => <Properties counter={counter} />,
  relations: (_node, counter) => <Relations counter={counter} />,
  count: (_node, counter) => <Count counter={counter} />,
  actions: () => <Actions />,
};

const COUNTER_DETAIL_FIELDS = (plugins: FieldDef[]) => counterFields([], plugins);

// A counter's detail draws no task, so nothing asks it for a task's address.
const NO_TASK = () => "";

/** A counter's detail, drawn from its group's layout, or as shipped. */
export const CounterLayoutView = ({
  counter,
  context,
  layout,
  editing,
}: {
  counter: CounterRead;
  context: CounterLayoutContext;
  layout?: StoredRegions | null;
  /** The layout is being edited: each part is marked with its path. */
  editing?: boolean;
}) => {
  const communityId = useActiveCommunityId();
  const env = useProjectLayoutEnv(useCallback(NO_TASK, []));
  return (
    // Another counter's detail starts afresh, with none of this one's drafts.
    <DetailContext.Provider key={`${communityId}:${counter.id}`} value={context}>
      <DetailLayoutView
        spec={COUNTER_LAYOUT}
        item={counter}
        initiativeId={context.initiativeId}
        layout={layout}
        editing={editing}
        fields={COUNTER_DETAIL_FIELDS}
        env={env}
        parts={COUNTER_PARTS}
      />
    </DetailContext.Provider>
  );
};
