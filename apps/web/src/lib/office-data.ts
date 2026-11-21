/** P9 data: reports agents publish, and saved website logins. */
import { queryOptions } from "@tanstack/react-query";

import { api } from "./api";

export interface Summary {
  text: string;
  model: string | null;
  cached: boolean;
  generated_at: string;
}

export interface ReportTable {
  title: string;
  columns: string[];
  rows: (string | number)[][];
}

export interface Report {
  id: string;
  title: string;
  summary: string;
  body: string | null;
  tables: ReportTable[] | null;
  table_count: number;
  row_count: number;
  labels: string[];
  agent_id: string | null;
  agent_name: string | null;
  agent_color: string | null;
  branch_id: string | null;
  branch_name: string | null;
  task_id: string | null;
  task_title: string | null;
  created_at: string;
}

export interface SavedLogin {
  id: string;
  name: string;
  hosts: string[];
  username_hint: string;
  branch_id: string | null;
  branch_name: string | null;
  owner_user_id: string | null;
  agent_ids: string[];
  created_by: string;
  created_at: string;
  last_used_at: string | null;
  can_manage: boolean;
  /** When agents last kept this login's signed-in browser session (they stay signed in). */
  session_saved_at?: string | null;
  session_expires_at?: string | null;
}

export const officeKeys = {
  reports: ["reports"] as const,
  report: (id: string) => ["reports", id] as const,
  logins: ["vault", "logins"] as const,
};

export const reportsQuery = queryOptions({ queryKey: officeKeys.reports, queryFn: () => api<Report[]>("/api/reports") });
export const reportQuery = (id: string) =>
  queryOptions({ queryKey: officeKeys.report(id), queryFn: () => api<Report>(`/api/reports/${id}`) });
export const loginsQuery = queryOptions({ queryKey: officeKeys.logins, queryFn: () => api<SavedLogin[]>("/api/vault/logins") });

export function usdShort(n: number): string {
  if (!n) return "$0";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}
