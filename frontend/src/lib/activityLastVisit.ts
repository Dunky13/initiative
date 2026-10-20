/**
 * When the reader last opened a community's front page. Kept on the device, per
 * account: it orders nothing and nobody else needs it, and it is what marks an
 * activity entry as new.
 */
export const activityLastVisitKey = (userId: number, communityId: number) =>
  `activity-last-visit:${userId}:${communityId}`;
