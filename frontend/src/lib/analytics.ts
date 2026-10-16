/**
 * Frontend measurement: page views, uncaught errors and Web Vitals, sent to
 * the collector this deployment names (`AppConfig.faro_collector_url`).
 *
 * Nothing here runs until {@link startAnalytics} is called, which only
 * happens once the deployment names a collector and this browser granted the
 * `analytics` category. The SDK is imported then and not before, so a browser
 * that never agreed never downloads it.
 *
 * A page is named by its route template (`/c/$communityId/projects/$projectId`),
 * never by its address, and no person is attached to anything sent.
 */

import type { ExceptionEvent, Faro, MeasurementEvent, TransportItem } from "@grafana/faro-web-sdk";

let faro: Faro | null = null;
let loading: Promise<void> | null = null;
/** Whether sending is wanted right now, which can change while the SDK loads. */
let wanted = false;
/** The collector the SDK was loaded for, and the one most recently named. The
 *  SDK sends to one collector for its lifetime, so a tab told of another one
 *  stops sending until it is reloaded. */
let loadedFor: string | null = null;
let named: string | null = null;
/** The route template of the page on screen. */
let route = "unknown";

/** The Web Vitals context values that name an element by its CSS selector. */
const SELECTOR_CONTEXT = ["element", "largest_shift_target", "interaction_target"];

/** Writes each id segment of a selector (`#intro>p.lead`) as `#id`, keeping
 *  its tags and classes. */
const withoutIds = (selector: string): string =>
  selector
    .split(">")
    .map((part) => (part.startsWith("#") ? "#id" : part))
    .join(">");

const outgoingPayload = (item: TransportItem): TransportItem["payload"] => {
  const kind: string = item.type;
  if (kind === "measurement") {
    const measurement = item.payload as MeasurementEvent;
    if (!measurement.context) return measurement;
    const context = { ...measurement.context };
    for (const key of SELECTOR_CONTEXT) {
      if (context[key]) context[key] = withoutIds(context[key]);
    }
    return { ...measurement, context };
  }
  if (kind === "exception") {
    // An error is sent as its type and stack frames, without its message or
    // context.
    const { context: _context, ...exception } = item.payload as ExceptionEvent;
    return { ...exception, value: "" };
  }
  return item.payload;
};

/**
 * Prepare an outgoing signal: label it with the route template in place of
 * the address the SDK read from the location bar, write element ids in Web
 * Vitals selectors as `#id`, and send errors without their message or context.
 */
export const beforeSend = (item: TransportItem): TransportItem => ({
  ...item,
  payload: outgoingPayload(item),
  meta: { ...item.meta, page: { id: route, url: route } },
});

const pageView = () => faro?.api.pushEvent("page_view", undefined, undefined, { skipDedupe: true });

const sending = () => wanted && named === loadedFor;

/** Start sending, or resume where measurement was paused. */
export const startAnalytics = (collectorUrl: string): Promise<void> => {
  wanted = true;
  named = collectorUrl;
  if (faro) {
    if (sending()) faro.unpause();
    else faro.pause();
    return Promise.resolve();
  }
  if (!loading) {
    loadedFor = collectorUrl;
    loading = import("@grafana/faro-web-sdk")
      .then(
        ({
          initializeFaro,
          ErrorsInstrumentation,
          SessionInstrumentation,
          WebVitalsInstrumentation,
        }) => {
          faro = initializeFaro({
            url: collectorUrl,
            app: { name: "initiative", version: __APP_VERSION__ },
            // Errors, Web Vitals and the session they belong to. The console
            // and request timings are left out: both carry addresses and text.
            instrumentations: [
              new ErrorsInstrumentation(),
              new WebVitalsInstrumentation(),
              new SessionInstrumentation(),
            ],
            beforeSend,
            preventGlobalExposure: true,
            paused: !sending(),
          });
          if (sending()) pageView();
        }
      )
      .catch(() => {
        // Nothing was measured; the next call tries again.
        loading = null;
        loadedFor = null;
      });
  }
  return loading;
};

/** Stop sending. A loaded SDK cannot be unloaded, so it is paused, and
 *  whatever it records while paused is dropped rather than held. */
export const pauseAnalytics = (): void => {
  wanted = false;
  faro?.pause();
};

/** Record that a page is on screen, under its route template. */
export const recordPageView = (template: string): void => {
  route = template;
  pageView();
};
