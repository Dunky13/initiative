/**
 * What people changed lately in the community, one entry per item: what it is
 * and where it lives, who did what to it, and when. It fills the tray under the
 * front page's rail, one view per circle.
 *
 * The endpoint returns only what the reader can open and orders it for them, so
 * nothing is filtered or sorted here. An entry the reader has not seen since
 * their last visit is marked as new.
 */

import { Link } from "@tanstack/react-router";
import { Activity } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { ActivityEntry, FeedView } from "@/api/generated/initiativeAPI.schemas";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { RelativeTime } from "@/components/ui/relative-time";
import { Skeleton } from "@/components/ui/skeleton";
import { MentionText } from "@/components/user/MentionText";
import { useActivityFeed } from "@/hooks/useActivity";
import { useCommunityPath } from "@/lib/communityUrl";
import { listFormat } from "@/lib/intl";
import { FROM_FEED, hitIcon, searchHitPath } from "@/lib/searchResults";
import { resolveUploadUrl } from "@/lib/uploadUrl";
import { getInitialsForUser, getUserDisplayName } from "@/lib/userDisplay";

/** "Ada and 2 others commented and edited", in the reader's language. */
const useSentence = () => {
  const { t, i18n } = useTranslation("communityHome");
  const locale = i18n.resolvedLanguage ?? i18n.language;
  const and = listFormat(locale, { type: "conjunction" });
  return (entry: ActivityEntry) => {
    const count = entry.actor_count;
    const names = entry.actors.map((person) => getUserDisplayName(person));
    const rest = count - names.length;
    const people = and.format(rest > 0 ? [...names, t("feed.others", { count: rest })] : names);
    const actions = and.format(entry.verbs.map((verb) => t(`feed.verbs.${verb}`, { count })));
    return t("feed.sentence", { people, actions, count });
  };
};

const FeedRow = ({ entry, isNew }: { entry: ActivityEntry; isNew: boolean }) => {
  const { t } = useTranslation(["communityHome", "search"]);
  const gp = useCommunityPath();
  const sentence = useSentence();
  const Icon = hitIcon(entry);
  const path = searchHitPath(entry);
  const where = [entry.tool_title, entry.initiative_name].filter(Boolean).join(" · ");
  const kind = t(`search:types.${entry.entity_type}` as never, { defaultValue: entry.entity_type });

  const body = (
    <div className="flex gap-3">
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex items-baseline gap-2">
          <span className="truncate font-medium">
            <MentionText text={entry.title} disableLink />
          </span>
          <span className="shrink-0 text-muted-foreground text-xs">{kind}</span>
          {isNew ? <Badge variant="secondary">{t("feed.new")}</Badge> : null}
        </div>
        {where ? <p className="truncate text-muted-foreground text-xs">{where}</p> : null}
        <div className="flex items-center gap-2">
          <div className="flex -space-x-2">
            {entry.actors.map((person) => {
              const src = resolveUploadUrl(person.avatar_url) || undefined;
              return (
                <Avatar key={person.id} className="h-6 w-6 border-2 border-card">
                  {src ? <AvatarImage src={src} /> : null}
                  <AvatarFallback userId={person.id} className="text-xs">
                    {getInitialsForUser(person)}
                  </AvatarFallback>
                </Avatar>
              );
            })}
          </div>
          <p className="min-w-0 flex-1 truncate text-sm">{sentence(entry)}</p>
          <RelativeTime date={entry.latest} className="shrink-0 text-muted-foreground text-xs" />
        </div>
      </div>
    </div>
  );

  return (
    <li className="rounded-md p-2 transition-colors hover:bg-accent">
      {path ? (
        <Link to={gp(path)} state={FROM_FEED} className="block">
          {body}
        </Link>
      ) : (
        body
      )}
    </li>
  );
};

interface CommunityActivityFeedProps {
  view: FeedView;
  /** When the reader was last here, as an ISO time; nothing is new without one. */
  lastVisit: string | null;
}

export const CommunityActivityFeed = ({ view, lastVisit }: CommunityActivityFeedProps) => {
  const { t } = useTranslation("communityHome");
  const feed = useActivityFeed({ view });
  const entries = feed.data?.pages.flatMap((page) => page.items) ?? [];
  const since = lastVisit ? Date.parse(lastVisit) : null;

  return (
    <Card>
      <CardContent className="p-2 sm:p-3">
        {feed.isLoading ? (
          <div className="space-y-4 p-2">
            {Array.from({ length: 4 }).map((_, i) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list of skeletons has no id to key from
              <div key={i} className="flex gap-3">
                <Skeleton className="h-4 w-4" />
                <div className="flex-1 space-y-1">
                  <Skeleton className="h-4 w-1/2" />
                  <Skeleton className="h-3 w-1/3" />
                </div>
              </div>
            ))}
          </div>
        ) : feed.isError ? (
          <p className="p-2 text-destructive text-sm">{t("feed.loadError")}</p>
        ) : entries.length === 0 ? (
          <div className="flex h-50 flex-col items-center justify-center gap-2 text-muted-foreground text-sm">
            <Activity className="h-8 w-8 opacity-50" aria-hidden="true" />
            <span>{t(`feed.empty.${view}`)}</span>
          </div>
        ) : (
          <>
            <ul className="space-y-1">
              {entries.map((entry) => (
                <FeedRow
                  key={`${entry.entity_type}:${entry.entity_id}`}
                  entry={entry}
                  isNew={since != null && Date.parse(entry.latest) > since}
                />
              ))}
            </ul>
            {feed.hasNextPage ? (
              <Button
                type="button"
                variant="secondary"
                className="mt-2 w-full"
                onClick={() => void feed.fetchNextPage()}
                disabled={feed.isFetchingNextPage}
              >
                {feed.isFetchingNextPage ? t("loading") : t("feed.loadMore")}
              </Button>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
};
