/** Who has private assistants, kept free of React so the router and tests can import it
 * cheaply. One owner: they have every permission, so these are true/false checks only. */

export const ASSIST = "assistants.use";

/** May have private assistants. */
export const canAssist = (perms: readonly string[]) => perms.includes(ASSIST);

/** People whose role has a personal AI but who may not add agents (none in a one-owner office;
 * kept so pages written for both read the same). */
export const staffOnly = (perms: readonly string[]) => perms.includes("agents.own") && !perms.includes("agents.manage");
