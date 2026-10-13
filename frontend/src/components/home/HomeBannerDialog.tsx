/**
 * The banner a home view wears, picked from the reader's own decoration
 * library — the same banners their profile picker offers — so each view can
 * look its own way. The choice is saved as it is made.
 */

import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { SlotPicker } from "@/components/user/DecorationPicker";
import { useAuth } from "@/hooks/useAuth";
import { useMyDecorations } from "@/hooks/useUsers";
import { resolveDecoration } from "@/lib/profileDecorations";

export interface HomeBannerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  value: string | null;
  onChange: (banner: string | null) => void;
}

export function HomeBannerDialog({ open, onOpenChange, value, onChange }: HomeBannerDialogProps) {
  const { t } = useTranslation(["home", "common"]);
  const { user } = useAuth();
  const library = useMyDecorations({ enabled: open });
  const owned = library.data?.items;
  // The shortcut is offered only while the profile's banner is one this build
  // draws and the reader still has it.
  const profileBanner = user?.profile_decorations?.banner ?? null;
  const canUseProfile =
    !!resolveDecoration(profileBanner, "banner") &&
    !!owned?.some((item) => item.kind === "banner" && item.id === profileBanner);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("banner.title")}</DialogTitle>
          <DialogDescription>{t("banner.description")}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-wrap gap-2">
          {canUseProfile ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onChange(profileBanner)}
              disabled={value === profileBanner}
            >
              {t("banner.useProfile")}
            </Button>
          ) : null}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onChange(null)}
            disabled={value === null}
          >
            {t("banner.none")}
          </Button>
        </div>
        <div>
          <SlotPicker kind="banner" value={value} onChange={onChange} owned={owned} />
        </div>
        <DialogFooter className="items-center gap-2 sm:justify-between">
          <Button asChild variant="link" className="h-auto p-0">
            <Link to="/marketplace" onClick={() => onOpenChange(false)}>
              {t("banner.more")}
            </Link>
          </Button>
          <Button type="button" onClick={() => onOpenChange(false)}>
            {t("common:done")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
