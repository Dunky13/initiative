/**
 * Stars: any tool, kept in its own community.
 *
 * A community's list (`/c/{id}/favorites`) answers both "what has the reader
 * starred here" — the sidebar's Favorites — and "is this one starred", for the
 * star on a tool's page and on its card; it is a few dozen rows at most, so one
 * read serves every star on the screen. `/me/favorites` gathers every
 * community's for the home page.
 */

import { type UseQueryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";

import {
  addFavorite,
  getListCommunityFavoritesQueryKey,
  getListMyFavoritesQueryKey,
  listCommunityFavorites,
  listMyFavorites,
  removeFavorite,
} from "@/api/generated/favorites/favorites";
import type { FavoriteItemRead, Tool } from "@/api/generated/initiativeAPI.schemas";
import { invalidate, q } from "@/api/query-keys";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";

type QueryOpts<TData> = Omit<UseQueryOptions<TData>, "queryKey" | "queryFn">;

/** The reader's stars in one community (the active one unless named), newest first. */
export const useCommunityFavorites = (
  communityId?: number | null,
  options?: QueryOpts<FavoriteItemRead[]>
) => {
  const active = useActiveCommunityId();
  const id = communityId ?? active;
  return useQuery<FavoriteItemRead[]>({
    queryKey: getListCommunityFavoritesQueryKey(id),
    queryFn: () => listCommunityFavorites(id),
    staleTime: 30 * 1000,
    ...options,
    enabled: Boolean(id) && (options?.enabled ?? true),
  });
};

/** The reader's stars in every community they are in, newest first. */
export const useMyFavorites = (options?: QueryOpts<FavoriteItemRead[]>) =>
  useQuery<FavoriteItemRead[]>({
    queryKey: getListMyFavoritesQueryKey(),
    queryFn: () => listMyFavorites(),
    staleTime: 30 * 1000,
    ...options,
  });

/** Whether the reader starred this tool, in its community (the active one
 *  unless named). */
export const useIsFavorite = (tool: Tool, entityId: number, communityId?: number): boolean => {
  const { data } = useCommunityFavorites(communityId);
  return useMemo(
    () => Boolean(data?.some((item) => item.entity_type === tool && item.entity_id === entityId)),
    [data, tool, entityId]
  );
};

export interface ToggleFavoriteArgs {
  tool: Tool;
  entityId: number;
  /** Star it (true) or take the star off (false). */
  next: boolean;
  /** The tool's own community; the active one when left out. */
  communityId?: number;
  /** What a list shows for it until the server's answer arrives. */
  name?: string;
  initiativeId?: number | null;
}

const sameItem = (item: FavoriteItemRead, tool: Tool, entityId: number, communityId: number) =>
  item.entity_type === tool && item.entity_id === entityId && item.community_id === communityId;

/**
 * Star or unstar a tool. The star changes at once — the community's list and
 * every community's are rewritten in the cache, and put back if the write
 * fails — and both are read again once it lands.
 */
export const useToggleFavorite = () => {
  const active = useActiveCommunityId();
  const qc = useQueryClient();

  return useMutation({
    mutationFn: async ({ tool, entityId, next, communityId }: ToggleFavoriteArgs) => {
      const id = communityId ?? active;
      if (next) await addFavorite(id, tool, entityId);
      else await removeFavorite(id, tool, entityId);
    },
    onMutate: async ({ tool, entityId, next, communityId, name, initiativeId }) => {
      const id = communityId ?? active;
      const keys = [getListCommunityFavoritesQueryKey(id), getListMyFavoritesQueryKey()];
      await Promise.all(keys.map((queryKey) => qc.cancelQueries({ queryKey })));
      const before = keys.map((queryKey) => [queryKey, qc.getQueryData(queryKey)] as const);
      const placeholder: FavoriteItemRead = {
        entity_type: tool,
        entity_id: entityId,
        community_id: id,
        initiative_id: initiativeId ?? null,
        name: name ?? "",
        favorited_at: new Date().toISOString(),
        icon: null,
        file_type: null,
        mime_type: null,
        original_filename: null,
      };
      for (const queryKey of keys) {
        qc.setQueryData<FavoriteItemRead[]>(queryKey, (prev) => {
          if (!prev) return prev;
          const rest = prev.filter((item) => !sameItem(item, tool, entityId, id));
          return next ? [placeholder, ...rest] : rest;
        });
      }
      return { before };
    },
    onError: (_error, _args, context) => {
      for (const [queryKey, data] of context?.before ?? []) qc.setQueryData(queryKey, data);
    },
    onSettled: () => {
      void invalidate(q.favorites());
    },
  });
};
