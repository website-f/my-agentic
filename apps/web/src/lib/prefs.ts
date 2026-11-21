/** The person's small saved settings (users.prefs): the app language and how their AI speaks. */
import { queryOptions } from "@tanstack/react-query";

import { api } from "./api";

/** P37: how a person's AI speaks to them (api i18n/dialects STYLES); "standard" = as written. */
export type SpeechStyle =
  | "standard" | "pasar" | "kelantan" | "terengganu" | "kedah" | "perak" | "pahang"
  | "negeri_sembilan" | "melaka" | "johor" | "sabah" | "sarawak";

/** The whitelisted prefs keys; each holds a small object. Others may add keys server-side. */
export interface Prefs {
  /** P22: the app language this person chose. */
  locale?: { language?: "en" | "ms" | null; speech?: SpeechStyle | null };
}

export const prefsKeys = {
  prefs: ["me", "prefs"] as const,
};

export const prefsQuery = queryOptions({
  queryKey: prefsKeys.prefs,
  queryFn: () => api<Prefs>("/api/me/prefs"),
  staleTime: 5 * 60_000, // P104: changed here only, and saved over the cached copy at once
});

/** Merge a few settings into users.prefs: sub-keys you send replace, null removes one. */
export function savePrefs(patch: { [K in keyof Prefs]?: { [S in keyof NonNullable<Prefs[K]>]?: NonNullable<Prefs[K]>[S] | null } }) {
  return api<Prefs>("/api/me/prefs", "PUT", patch);
}
