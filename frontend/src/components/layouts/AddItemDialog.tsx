import { Loader2 } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  GetLayoutsParams,
  PropertySummary,
  PropertyValueInput,
} from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { type ItemDraft, ItemDraftContext, type ItemEdit } from "@/hooks/useFieldSave";
import { useSetItemLinks } from "@/hooks/useRelationships";
import { detailLayoutOf, useToolLayouts } from "@/hooks/useToolLayouts";
import { AddingLinks, type DetailKind, DetailLayoutView } from "@/lib/layouts/DetailLayoutView";
import type { StoredRegions } from "@/lib/layouts/detailLayout";
import type { PluginItem } from "@/lib/layouts/plugins";
import type { LinkedRef } from "@/lib/relationships";
import type { DialogProps } from "@/types/dialog";

type Item = PluginItem & { properties: PropertySummary[] };

/** An item being added as Add found it: as it is drawn, the fields changed
 *  on it as they are sent, and the properties it is given. */
export interface Written<I, P> {
  item: I;
  fields: Partial<P>;
  properties: PropertyValueInput[];
}

type AddItemProps<I extends Item, C, P> = {
  detail: DetailKind<I, C, P>;
  /** The item as it starts, before anything is changed. */
  blank: I;
  context: C;
  /** Where its kind's layout is kept; none draws it as shipped. */
  layouts: GetLayoutsParams | null;
  /** The dialog's title, and what its button says. */
  title: string;
  /** Whether it can be added as it stands: it has a name. */
  ready: (item: I) => boolean;
  /** Makes it from what was changed, answering it. */
  create: (written: Written<I, P>) => Promise<{ id: number }>;
  /** Once it is made, and its links with it. */
  onAdded: () => void;
};

/**
 * Adding an item, drawn as its kind's layout lays it out with each field's own
 * editor. Nothing is saved until Add, which makes it from everything changed
 * and then writes the links picked; closing the dialog drops it all.
 */
export const AddItemDialog = <I extends Item, C, P>({
  open,
  onOpenChange,
  ...props
}: DialogProps & AddItemProps<I, C, P>) => (
  <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className="w-full rounded-2xl border bg-card shadow-2xl sm:max-w-3xl">
      <Adding {...props} />
    </DialogContent>
  </Dialog>
);

// Drawn only while the dialog is open, so each opening starts blank.
const Adding = <I extends Item, C, P>({
  detail,
  blank,
  context,
  layouts,
  title,
  ready,
  create,
  onAdded,
}: AddItemProps<I, C, P>) => {
  const { t } = useTranslation("common");
  const [item, setItem] = useState(blank);
  const [links, setLinks] = useState<LinkedRef[]>([]);
  const [adding, setAdding] = useState(false);
  // The fields showing a value they cannot take, which Add waits for.
  const [holding, setHolding] = useState<ReadonlySet<string>>(new Set());
  // Read by Add, which can run in the same event as the change it follows
  // (leaving a field, or Enter in it), before the render that shows it.
  const latest = useRef({
    item,
    fields: {} as Partial<P>,
    values: new Map<number, unknown>(),
    holding: new Set<string>(),
  });
  const layout = detailLayoutOf(useToolLayouts(layouts).data, detail.spec.kind);
  const home = detail.home(blank, context);
  const target = home.links.target;
  const setLinksOn = useSetItemLinks(home.canOpen.tool, home.canOpen.id);
  // The item this sitting made, whose links did not all land: Add again
  // finishes it rather than making a second. And the links last asked for,
  // which a retry writes against.
  const made = useRef<number | null>(null);
  const asked = useRef<LinkedRef[]>([]);

  const finish = async (id: number) => {
    if (target && (links.length > 0 || asked.current.length > 0)) {
      const previous = asked.current;
      asked.current = links;
      await setLinksOn.mutateAsync({
        item: { type: target.type, id },
        links,
        previous,
        force: previous.length > 0,
      });
    }
    onAdded();
  };

  const add = async () => {
    const { item: now, fields, values, holding: held } = latest.current;
    if (adding || held.size > 0 || !ready(now)) return;
    setAdding(true);
    try {
      if (made.current === null) {
        // A description written over is named with its base; a new one has none.
        const sent = Object.fromEntries(
          Object.entries(fields).filter(([key]) => !key.endsWith("_base"))
        ) as Partial<P>;
        const properties = [...values].map(([property_id, value]) => ({ property_id, value }));
        made.current = (await create({ item: now, fields: sent, properties })).id;
      }
      await finish(made.current);
    } catch {
      // What failed has said so; everything changed is still here to try again.
    } finally {
      setAdding(false);
    }
  };
  const submit = useRef(add);
  submit.current = add;

  const draft = useMemo<ItemDraft>(
    () => ({
      edit: (edit: ItemEdit<unknown, unknown>) => {
        const held = latest.current;
        held.item = { ...held.item, ...(edit.shows as Partial<I>) };
        if ("patch" in edit) {
          held.fields = { ...held.fields, ...(edit.patch as Partial<P>) };
        } else {
          for (const { property_id, value } of edit.properties.values) {
            held.values.set(property_id, value);
          }
          // A property taken off shows as gone: nothing reads it back.
          const removed = edit.properties.removed ?? [];
          for (const id of removed) held.values.delete(id);
          held.item = {
            ...held.item,
            properties: held.item.properties.filter((each) => !removed.includes(each.property_id)),
          };
        }
        setItem(held.item);
      },
      submit: () => void submit.current(),
      hold: (id: string, holds: boolean) => {
        const held = latest.current.holding;
        if (held.has(id) === holds) return;
        if (holds) held.add(id);
        else held.delete(id);
        setHolding(new Set(held));
      },
    }),
    []
  );
  const picking = useMemo(() => ({ value: links, onChange: setLinks }), [links]);

  return (
    <>
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription className="sr-only">{title}</DialogDescription>
      </DialogHeader>
      <ItemDraftContext.Provider value={draft}>
        <AddingLinks.Provider value={picking}>
          <DetailLayoutView
            detail={detail}
            item={item}
            context={context}
            layout={layout as StoredRegions | null}
          />
        </AddingLinks.Provider>
      </ItemDraftContext.Provider>
      <DialogFooter>
        <Button
          type="button"
          onClick={() => void add()}
          disabled={adding || holding.size > 0 || !ready(item)}
        >
          {adding ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {adding ? t("adding") : title}
        </Button>
      </DialogFooter>
    </>
  );
};
