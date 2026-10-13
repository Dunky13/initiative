import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import type {
  PropertyDefinitionCreate,
  PropertyDefinitionRead,
  PropertyDefinitionUpdate,
  PropertyDefinitionUpdateResponse,
  PropertyOption,
  PropertySummary,
  PropertyTarget,
} from "@/api/generated/initiativeAPI.schemas";
import {
  createPropertyDefinition,
  deletePropertyDefinition,
  getListPropertyDefinitionsQueryKey,
  listPropertyDefinitions,
  updatePropertyDefinition,
} from "@/api/generated/property-definitions/property-definitions";
import { invalidate, q } from "@/api/query-keys";
import { buildUniqueOptionSlug, findOptionByLabel } from "@/components/properties/propertyHelpers";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { type FieldSaveKind, usePendingShown } from "@/hooks/useFieldSave";
import { toast } from "@/lib/mascotToast";
import type { MutationOpts } from "@/types/mutation";

// ── Queries ──────────────────────────────────────────────────────────────────

/**
 * List property definitions.
 *
 * - ``initiativeId`` bound: scopes to that one initiative (for per-entity
 *   pickers and the initiative settings manager page).
 * - ``initiativeId`` omitted: returns the union across every initiative the
 *   caller is a member of — used by global views (My Tasks, Files list,
 *   events list) so property columns and filters aggregate across initiatives.
 */
export const useProperties = (options?: { initiativeId?: number; enabled?: boolean }) => {
  const communityId = useActiveCommunityId();
  const initiativeId = options?.initiativeId;
  const params: { initiative_id?: number } = {};
  if (initiativeId !== undefined) params.initiative_id = initiativeId;
  const hasParams = Object.keys(params).length > 0;
  return useQuery<PropertyDefinitionRead[]>({
    queryKey: getListPropertyDefinitionsQueryKey(communityId, hasParams ? params : undefined),
    queryFn: () => listPropertyDefinitions(communityId, hasParams ? params : undefined),
    enabled: options?.enabled ?? true,
    staleTime: 60 * 1000,
  });
};

// ── Mutations ────────────────────────────────────────────────────────────────

export const useCreateProperty = (
  options?: MutationOpts<PropertyDefinitionRead, PropertyDefinitionCreate>
) =>
  useCommunityMutation<PropertyDefinitionRead, PropertyDefinitionCreate>(
    {
      mutationFn: (communityId, data) => createPropertyDefinition(communityId, data),
      invalidate: () => invalidate(q.allProperties()),
      errorKey: "properties:manager.createError",
    },
    options
  );

export const useUpdateProperty = (
  options?: MutationOpts<
    PropertyDefinitionUpdateResponse,
    { propertyId: number; data: PropertyDefinitionUpdate }
  >
) =>
  useCommunityMutation<
    PropertyDefinitionUpdateResponse,
    { propertyId: number; data: PropertyDefinitionUpdate }
  >(
    {
      mutationFn: (communityId, { propertyId, data }) =>
        updatePropertyDefinition(communityId, propertyId, data),
      // Every row's embedded summaries carry the definition's name, options
      // and color.
      invalidate: () => invalidate(q.allProperties(), q.allPropertyHolders()),
      errorKey: "properties:manager.updateError",
    },
    options
  );

export const useDeleteProperty = (options?: MutationOpts<void, number>) =>
  useCommunityMutation<void, number>(
    {
      mutationFn: (communityId, propertyId) => deletePropertyDefinition(communityId, propertyId),
      invalidate: () => invalidate(q.allProperties(), q.allPropertyHolders()),
      errorKey: "properties:manager.deleteError",
    },
    options
  );

/**
 * Append a single option to a select / multi_select definition and return
 * the newly-added option. If a case-insensitive label match already exists
 * the existing option is returned without hitting the network, so the UI
 * can use it transparently as "picked" after the user typed an existing
 * label.
 */
export const useAppendPropertyOption = () => {
  const { t } = useTranslation("properties");
  const communityId = useActiveCommunityId();

  const mutation = useMutation({
    mutationFn: async (vars: {
      definition: PropertyDefinitionRead;
      label: string;
      color?: string | null;
    }) => {
      const label = vars.label.trim();
      if (!label) {
        throw new Error("Option label cannot be empty");
      }
      const existing = findOptionByLabel(vars.definition, label);
      if (existing) {
        return { option: existing, created: false as const };
      }
      const currentOptions = vars.definition.options ?? [];
      const slug = buildUniqueOptionSlug(label, currentOptions);
      const newOption: PropertyOption = {
        value: slug,
        label,
        color: vars.color ?? null,
      };
      const nextOptions: PropertyOption[] = [...currentOptions, newOption];
      const saved = await updatePropertyDefinition(communityId, vars.definition.id, {
        options: nextOptions,
      });
      // The server keeps options it already holds as they are, so the one
      // asked for is only there if it came back under this label.
      const stored = findOptionByLabel(saved.definition, label);
      if (!stored) {
        void invalidate(q.allProperties());
        throw new Error("Option was not added");
      }
      return { option: stored, created: true as const };
    },
    onSuccess: (result) => {
      void invalidate(q.allProperties(), q.allPropertyHolders());
      if (result.created) {
        toast.success(t("input.optionAdded"));
      }
    },
    onError: () => {
      toast.error(t("input.optionAddFailed"));
    },
  });

  return {
    appendOption: (definition: PropertyDefinitionRead, label: string, color?: string | null) =>
      mutation.mutateAsync({ definition, label, color }),
    isPending: mutation.isPending,
  };
};

/** Anything that carries property values. */
type PropertyHolder = { properties: PropertySummary[] };

/**
 * How one row's properties are saved, one value at a time, where the page has
 * no read of the row to write answers into: {@link useHeldProperties} holds
 * them until the page reads the row afresh.
 */
export const propertySaves = (target: PropertyTarget): FieldSaveKind<PropertyHolder, never> => ({
  name: `properties-${target}`,
  readKey: (communityId, id) => ["held-properties", communityId, target, id],
  // Only its properties are saved this way.
  patch: () => Promise.reject(new Error("a row's properties take no patch")),
  properties: target,
  lists: () => q.propertyHolder(target),
  itself: () => ({}),
});

/**
 * A row's properties as the page read them, with what its saves answered held
 * over them until the page reads them again, and saves not yet answered shown
 * over that.
 */
export const useHeldProperties = (
  kind: FieldSaveKind<PropertyHolder, never>,
  id: number,
  saved: PropertySummary[]
): PropertySummary[] => {
  const communityId = useActiveCommunityId();
  const queryClient = useQueryClient();
  const key = kind.readKey(communityId, id);
  const held = useQuery({
    queryKey: key,
    queryFn: () => queryClient.getQueryData<PropertyHolder>(key) ?? { properties: saved },
    initialData: { properties: saved },
    staleTime: Number.POSITIVE_INFINITY,
  });
  useEffect(() => {
    queryClient.setQueryData(kind.readKey(communityId, id), { properties: saved });
  }, [queryClient, kind, communityId, id, saved]);
  return usePendingShown(kind, id, held.data)?.properties ?? saved;
};
