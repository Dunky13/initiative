import { Copy, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { CommunityInviteRead } from "@/api/generated/initiativeAPI.schemas";
import { ListSkeleton, SkeletonRegion } from "@/components/skeletons/PageSkeletons";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { InviteLinkLimits } from "@/hooks/useCommunityInvites";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import { toast } from "@/lib/mascotToast";

const inviteLinkForCode = (code: string) => {
  const base = import.meta.env.VITE_APP_URL?.trim() || window.location.origin;
  const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;
  return `${normalizedBase}/invite/${encodeURIComponent(code)}`;
};

/** The two limits every invite link takes: how many may use it, and for how long. */
export const InviteLimitFields = ({
  idPrefix,
  value,
  onChange,
}: {
  idPrefix: string;
  value: InviteLinkLimits;
  onChange: (value: InviteLinkLimits) => void;
}) => {
  const { t } = useTranslation("communities");
  return (
    <>
      <div className="space-y-2">
        <Label htmlFor={`${idPrefix}-uses`}>{t("users.maxUsesLabel")}</Label>
        <Input
          id={`${idPrefix}-uses`}
          type="number"
          min={1}
          value={value.maxUses}
          onChange={(event) => onChange({ ...value, maxUses: Number(event.target.value) })}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor={`${idPrefix}-days`}>{t("users.expiresDaysLabel")}</Label>
        <Input
          id={`${idPrefix}-days`}
          type="number"
          min={0}
          value={value.expiresDays}
          onChange={(event) => onChange({ ...value, expiresDays: Number(event.target.value) })}
        />
      </div>
    </>
  );
};

/** The link of an invite just made, with a copy button. Its code is shown this once. */
export const NewInviteLink = ({ code }: { code: string }) => {
  const { t } = useTranslation("communities");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(inviteLinkForCode(code));
      toast.success(t("users.inviteLinkCopied"));
    } catch (error) {
      console.error(error);
    }
  };
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded border border-primary/40 bg-primary/5 p-4 text-sm">
      <div>
        <p className="break-all font-medium">{inviteLinkForCode(code)}</p>
        <p className="text-muted-foreground text-xs">{t("users.newInviteLinkOnce")}</p>
      </div>
      <Button variant="outline" size="icon" onClick={() => void copy()}>
        <Copy className="h-4 w-4" />
        <span className="sr-only">{t("users.copyInviteLink")}</span>
      </Button>
    </div>
  );
};

/**
 * Live "N uses · expires M" line for one invite. A component (not an inline
 * hook) so `useRelativeTime` can run per invite inside the invites map.
 */
const InviteUsesLine = ({ invite }: { invite: CommunityInviteRead }) => {
  const { t } = useTranslation("communities");
  const relativeExpiry = useRelativeTime(invite.expires_at);
  const expires = invite.expires_at != null ? relativeExpiry : t("users.neverExpires");
  return (
    <p className="text-muted-foreground">
      {t("users.usesFormat", { uses: invite.uses, max: invite.max_uses ?? "∞", expires })}
    </p>
  );
};

/** A community's invites, each with how it has been used and a delete button. */
export const CommunityInviteList = ({
  invites,
  isLoading,
  error,
  emptyText,
  onDelete,
  detail,
}: {
  invites: CommunityInviteRead[];
  isLoading: boolean;
  error: string | null;
  emptyText: string;
  onDelete: (inviteId: number) => void;
  /** More about one invite, under its uses. */
  detail?: (invite: CommunityInviteRead) => ReactNode;
}) => {
  const { t } = useTranslation("communities");
  return (
    <>
      {isLoading ? (
        <SkeletonRegion label={t("users.loadingInvites")}>
          <ListSkeleton rows={2} avatar={false} />
        </SkeletonRegion>
      ) : null}
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
      {!isLoading && !invites.length ? (
        <p className="text-muted-foreground text-sm">{emptyText}</p>
      ) : null}
      <div className="space-y-3">
        {invites.map((invite) => (
          <div
            key={invite.id}
            className="flex flex-wrap items-center justify-between gap-3 rounded border bg-muted/30 p-4 text-sm"
          >
            <div>
              <p className="font-medium">{invite.invitee_email ?? t("users.inviteLinkTitle")}</p>
              <InviteUsesLine invite={invite} />
              {detail?.(invite)}
            </div>
            <Button variant="outline" size="icon" onClick={() => onDelete(invite.id)}>
              <Trash2 className="h-4 w-4" />
              <span className="sr-only">{t("users.deleteInviteLink")}</span>
            </Button>
          </div>
        ))}
      </div>
    </>
  );
};
