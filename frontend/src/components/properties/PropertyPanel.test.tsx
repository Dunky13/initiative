import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { buildPropertySummary } from "@/__tests__/factories/properties";
import { communityHttp } from "@/__tests__/helpers/communityHttp";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import {
  type PropertySummary,
  PropertyTarget,
  PropertyType,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";

import { PropertyPanel } from "./PropertyPanel";

const status = buildPropertySummary({
  property_id: 1,
  name: "Status",
  type: PropertyType.text,
  value: "open",
});
const owner = buildPropertySummary({
  property_id: 2,
  name: "Owner",
  type: PropertyType.text,
  value: "Ada",
});

/** Each write to the row's properties, as sent; answered with what the row
 *  then holds. */
const writes = (answer: PropertySummary[] = []) => {
  const sent: Record<string, unknown>[] = [];
  server.use(
    communityHttp.put("/properties/:target/:entityId", async ({ request, params }) => {
      const body = (await request.json()) as Record<string, unknown>;
      sent.push({ ...body, at: `${params.target}/${params.entityId}` });
      return HttpResponse.json(answer);
    })
  );
  return sent;
};

const panel = (saved: PropertySummary[], disabled = false) =>
  renderWithProviders(
    <PropertyPanel
      target={PropertyTarget.file}
      entityId={10}
      initiativeId={1}
      saved={saved}
      canOpen={{ tool: Tool.file, id: 10 }}
      disabled={disabled}
    />
  );

describe("PropertyPanel", () => {
  it("saves the one value changed, leaving the others as they are", async () => {
    const sent = writes([{ ...status, value: "closed" }, owner]);
    panel([status, owner]);
    const user = userEvent.setup();

    const input = screen.getByDisplayValue("open");
    await user.clear(input);
    await user.type(input, "closed{Enter}");

    await waitFor(() =>
      expect(sent).toEqual([
        { at: "file/10", merge: true, values: [{ property_id: 1, value: "closed" }] },
      ])
    );
    expect(await screen.findByDisplayValue("closed")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Ada")).toBeInTheDocument();
  });

  it("takes a property off the row by itself", async () => {
    const sent = writes();
    panel([status, owner]);

    await userEvent.click(
      within(screen.getByRole("group", { name: "Owner" })).getByRole("button", { name: /remove/i })
    );

    await waitFor(() =>
      expect(sent).toEqual([{ at: "file/10", merge: true, values: [], removed: [2] }])
    );
  });

  it("shows a reader the values, with nothing to change them with", () => {
    panel([status, owner], true);

    expect(screen.getByText("open")).toBeInTheDocument();
    expect(screen.getByText("Ada")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /remove/i })).not.toBeInTheDocument();
  });
});
