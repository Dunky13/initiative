import type { TransportItem } from "@grafana/faro-web-sdk";
import { beforeEach, describe, expect, it, vi } from "vitest";

const sdk = vi.hoisted(() => {
  const faro = { api: { pushEvent: vi.fn() }, pause: vi.fn(), unpause: vi.fn() };
  return {
    faro,
    initializeFaro: vi.fn(
      (_config: { url: string; paused: boolean; instrumentations: object[] }) => faro
    ),
    ErrorsInstrumentation: class ErrorsInstrumentation {},
    SessionInstrumentation: class SessionInstrumentation {},
    WebVitalsInstrumentation: class WebVitalsInstrumentation {},
  };
});

vi.mock("@grafana/faro-web-sdk", () => sdk);

// Module state is the point under test, so each case starts from a fresh copy.
const load = () => import("@/lib/analytics");

beforeEach(() => {
  vi.resetModules();
  vi.clearAllMocks();
});

describe("frontend measurement", () => {
  it("sends nothing until started", async () => {
    const { recordPageView } = await load();

    recordPageView("/c/$communityId/projects/$projectId");

    expect(sdk.initializeFaro).not.toHaveBeenCalled();
  });

  it("starts with errors, Web Vitals and sessions only, and records the page", async () => {
    const { startAnalytics } = await load();

    await startAnalytics("/collect");

    expect(sdk.initializeFaro).toHaveBeenCalledOnce();
    const [config] = sdk.initializeFaro.mock.calls[0];
    expect(config.url).toBe("/collect");
    expect(config.paused).toBe(false);
    expect(config.instrumentations.map((i) => i.constructor.name)).toEqual([
      "ErrorsInstrumentation",
      "WebVitalsInstrumentation",
      "SessionInstrumentation",
    ]);
    expect(sdk.faro.api.pushEvent).toHaveBeenCalledWith("page_view", undefined, undefined, {
      skipDedupe: true,
    });
  });

  it("names the page by its route template, never its address", async () => {
    const { beforeSend, recordPageView } = await load();
    recordPageView("/c/$communityId/projects/$projectId");

    const item = {
      type: "event",
      payload: {},
      meta: { page: { url: "https://app.example.com/c/4/projects/9?tab=board" }, app: {} },
    } as unknown as TransportItem;

    expect(beforeSend(item).meta).toEqual({
      page: {
        id: "/c/$communityId/projects/$projectId",
        url: "/c/$communityId/projects/$projectId",
      },
      app: {},
    });
  });

  it("names Web Vitals elements by selectors without element ids", async () => {
    const { beforeSend } = await load();
    const context = {
      id: "v5-1760000000000-1234",
      rating: "good",
      navigation_type: "navigate",
      navigation_entry_id: "unknown",
    };
    const lcp = {
      type: "measurement",
      payload: {
        type: "web-vitals",
        values: { lcp: 1200, delta: 1200 },
        timestamp: "2026-10-16T00:00:00.000Z",
        context: { ...context, element: "#launch-plan-for-q3>span.font-bold" },
      },
      meta: {},
    } as unknown as TransportItem;
    const inp = {
      ...lcp,
      payload: {
        ...lcp.payload,
        context: { ...context, interaction_target: "div.editor>p", interaction_type: "keyboard" },
      },
    } as TransportItem;

    expect(beforeSend(lcp).payload).toEqual({
      ...lcp.payload,
      context: { ...context, element: "#id>span.font-bold" },
    });
    expect(beforeSend(inp).payload).toEqual(inp.payload);
  });

  it("sends an error's type and stack frames, without its message or context", async () => {
    const { beforeSend } = await load();
    const stacktrace = {
      frames: [{ filename: "/assets/index.js", function: "submit", lineno: 1, colno: 42 }],
    };
    const item = {
      type: "exception",
      payload: {
        type: "AxiosError",
        value: "Request failed with status code 400",
        timestamp: "2026-10-16T00:00:00.000Z",
        context: { cause: '{"detail":"INVALID_OR_EXPIRED_TOKEN"}' },
        stacktrace,
      },
      meta: {},
    } as unknown as TransportItem;

    expect(beforeSend(item).payload).toEqual({
      type: "AxiosError",
      value: "",
      timestamp: "2026-10-16T00:00:00.000Z",
      stacktrace,
    });
  });

  it("starts paused when consent is withdrawn while the SDK loads", async () => {
    const { pauseAnalytics, startAnalytics } = await load();

    const started = startAnalytics("/collect");
    pauseAnalytics();
    await started;

    expect(sdk.initializeFaro.mock.calls[0][0].paused).toBe(true);
    expect(sdk.faro.api.pushEvent).not.toHaveBeenCalled();
  });

  it("pauses and resumes the one loaded SDK", async () => {
    const { pauseAnalytics, startAnalytics } = await load();
    await startAnalytics("/collect");

    pauseAnalytics();
    await startAnalytics("/collect");

    expect(sdk.faro.pause).toHaveBeenCalledOnce();
    expect(sdk.faro.unpause).toHaveBeenCalledOnce();
    expect(sdk.initializeFaro).toHaveBeenCalledOnce();
  });

  it("stops sending when the deployment names another collector", async () => {
    const { startAnalytics } = await load();
    await startAnalytics("/collect");

    await startAnalytics("https://faro.example.com/collect");

    expect(sdk.faro.pause).toHaveBeenCalledOnce();
    expect(sdk.faro.unpause).not.toHaveBeenCalled();
    expect(sdk.initializeFaro).toHaveBeenCalledOnce();
  });

  it("tries again after the SDK fails to start", async () => {
    const { startAnalytics } = await load();
    sdk.initializeFaro.mockImplementationOnce(() => {
      throw new Error("blocked");
    });

    await startAnalytics("/collect");
    await startAnalytics("/collect");

    expect(sdk.initializeFaro).toHaveBeenCalledTimes(2);
    expect(sdk.faro.api.pushEvent).toHaveBeenCalledOnce();
  });
});
