import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  createCommunityInvite,
  deleteCommunityInvite,
  useListCommunityInvites,
} from "@/api/generated/communities/communities";
import type { CommunityInviteCreate } from "@/api/generated/initiativeAPI.schemas";
import { getErrorMessage } from "@/lib/errorMessage";

/** A link's own limits, as the invite forms ask for them. 0 means none. */
export interface InviteLinkLimits {
  maxUses: number;
  expiresDays: number;
}

/**
 * A community's invites, and making and deleting them — the member invites on
 * Settings › Users and the guest invites on Settings › Guests.
 *
 * The code of an invite just made is kept to show once, as only its hash is
 * stored, and only in the community it was made for; deleting that invite
 * drops it.
 */
export const useCommunityInvites = (communityId: number | null, enabled: boolean) => {
  const { t } = useTranslation("communities");
  const query = useListCommunityInvites(communityId ?? 0, {
    query: { enabled: enabled && communityId !== null },
  });
  // What the last create or delete reported; a failed load is the query's own.
  const [actionError, setActionError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [newInvite, setNewInvite] = useState<{
    communityId: number;
    inviteId: number;
    code: string;
  } | null>(null);

  const create = async (
    { maxUses, expiresDays }: InviteLinkLimits,
    extra?: Pick<CommunityInviteCreate, "guest_days" | "grants">
  ) => {
    if (!communityId) return;
    setSubmitting(true);
    setActionError(null);
    try {
      const created = await createCommunityInvite(communityId, {
        max_uses: maxUses > 0 ? maxUses : null,
        expires_at:
          expiresDays > 0
            ? new Date(Date.now() + expiresDays * 24 * 60 * 60 * 1000).toISOString()
            : null,
        ...extra,
      });
      setNewInvite({ communityId, inviteId: created.id, code: created.code });
      await query.refetch();
    } catch (error) {
      console.error(error);
      setActionError(getErrorMessage(error, "communities:users.unableToCreateInvite"));
    } finally {
      setSubmitting(false);
    }
  };

  const remove = async (inviteId: number) => {
    if (!communityId) return;
    setActionError(null);
    try {
      await deleteCommunityInvite(communityId, inviteId);
      if (newInvite?.inviteId === inviteId) setNewInvite(null);
      await query.refetch();
    } catch (error) {
      console.error(error);
      setActionError(t("users.unableToDeleteInvite"));
    }
  };

  return {
    invites: query.data ?? [],
    isLoading: query.isLoading,
    error: actionError ?? (query.isError ? t("users.unableToLoadInvites") : null),
    submitting,
    newInviteCode: newInvite && newInvite.communityId === communityId ? newInvite.code : null,
    create,
    remove,
    refresh: () => {
      setActionError(null);
      void query.refetch();
    },
  };
};
