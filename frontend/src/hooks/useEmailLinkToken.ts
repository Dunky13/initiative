import { useNavigate, useSearch } from "@tanstack/react-router";
import { useEffect, useState } from "react";

/**
 * The `?token=` an emailed link arrived with, read once.
 *
 * The page keeps the token for as long as it is mounted and replaces its
 * address with one without it, so the history entry holds the page alone. A
 * reload of that address finds no token, which each page reports as a link
 * that does not work.
 */
export const useEmailLinkToken = (): string => {
  const search = useSearch({ strict: false }) as { token?: string };
  const navigate = useNavigate();
  const [token] = useState(() => search.token ?? "");

  useEffect(() => {
    const { token: linkToken, ...rest } = search;
    if (linkToken === undefined) return;
    void navigate({ to: ".", search: rest, replace: true });
  }, [search, navigate]);

  return token;
};
