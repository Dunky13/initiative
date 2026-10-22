import { fileURLToPath } from "node:url";

/** Where the sign-in step leaves its session for the shots to start from. */
export const SIGNED_IN = fileURLToPath(new URL("../.auth/shots.json", import.meta.url));
