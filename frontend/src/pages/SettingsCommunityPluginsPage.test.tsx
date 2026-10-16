/**
 * Removing a plug-in whose charges somebody else manages.
 *
 * The confirmation says what removing any plug-in does, and for one the
 * community's provider has a say about, what that provider says too: its own
 * sentence when it answered, a neutral one when it did not. Nothing extra for
 * any other plug-in.
 */
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { communityCan } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";
import type { CommunityPluginUninstallNotice } from "@/api/generated/initiativeAPI.schemas";

import { SettingsCommunityPluginsPage } from "./SettingsCommunityPluginsPage";

let notice: CommunityPluginUninstallNotice | undefined;
const openAddress = vi.fn();

vi.mock("@/hooks/useCommunities", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useCommunities")>()),
  useCommunities: () => ({
    activeCommunityId: 1,
    activeCommunity: { id: 1, role: "superadmin", can: communityCan("superadmin") },
  }),
}));
vi.mock("@/hooks/useBillingPortal", () => ({
  useBillingPortal: () => ({ canSell: true, openAddress }),
}));
vi.mock("@/hooks/useCommunityPlugins", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useCommunityPlugins")>()),
  useCommunityPlugins: () => ({
    data: {
      items: [{ id: 4, name: "PaidCo", enabled: true, created_at: "2026-10-01T00:00:00Z" }],
    },
    isLoading: false,
  }),
  useUninstallNotice: () => ({ data: notice }),
}));

beforeEach(() => {
  notice = undefined;
  openAddress.mockReset();
});

async function openRemoval() {
  renderPage(SettingsCommunityPluginsPage);
  await userEvent.click(await screen.findByRole("button", { name: "Remove" }));
  return screen.findByRole("alertdialog");
}

describe("the removal dialog", () => {
  it("shows the provider's own words, and where to go about it", async () => {
    notice = {
      managed: true,
      message: "PaidCo keeps working until 30 November.",
      action_url: "https://portal.test/apps/x",
    };
    await openRemoval();

    expect(screen.getByText(/PaidCo keeps working until 30 November\./)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Manage" }));
    expect(openAddress).toHaveBeenCalledWith(1, "https://portal.test/apps/x");
  });

  it("says something neutral when the provider did not answer", async () => {
    notice = { managed: true, message: null, action_url: null };
    await openRemoval();

    expect(
      screen.getByText(/Charges for this plug-in are managed by your provider\./)
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Manage" })).toBeNull();
  });

  it("adds nothing for a plug-in nobody else manages", async () => {
    notice = { managed: false, message: null, action_url: null };
    await openRemoval();

    expect(screen.queryByText(/managed by your provider/)).toBeNull();
  });
});
