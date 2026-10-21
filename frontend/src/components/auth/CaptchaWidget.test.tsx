import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/__tests__/helpers/render";

import { CaptchaWidget } from "./CaptchaWidget";

const config = { provider: "turnstile", site_key: "site" };
const app = {
  isNativePlatform: true,
  serverUrl: "https://tasks.example.com/api/v1",
  getServerOrigin: () => "https://tasks.example.com",
};

describe("CaptchaWidget in the apps", () => {
  it("frames the server's captcha page and takes the token it sends", () => {
    const onToken = vi.fn();
    renderWithProviders(<CaptchaWidget config={config} onToken={onToken} />, { server: app });

    const frame = screen.getByTitle("Spam check") as HTMLIFrameElement;
    expect(frame.src).toBe("https://tasks.example.com/api/v1/config/captcha");

    const send = (origin: string) =>
      fireEvent(
        window,
        new MessageEvent("message", {
          origin,
          source: frame.contentWindow,
          data: { type: "initiative-captcha", token: "solved" },
        })
      );
    send("https://elsewhere.example.com");
    expect(onToken).not.toHaveBeenCalled();
    send("https://tasks.example.com");
    expect(onToken).toHaveBeenCalledWith("solved");
  });
});
