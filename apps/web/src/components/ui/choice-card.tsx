/** A big tappable card that reads as a radio or checkbox. */
import { CheckIcon, LockSimpleIcon } from "@phosphor-icons/react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function ChoiceCard({
  on,
  onToggle,
  title,
  hint,
  leading,
  trailing,
  kind = "radio",
  locked,
  disabled,
}: {
  on: boolean;
  onToggle?: () => void;
  title: ReactNode;
  hint?: ReactNode;
  leading?: ReactNode;
  trailing?: ReactNode;
  kind?: "radio" | "checkbox";
  locked?: boolean;
  disabled?: boolean;
}) {
  const inert = locked || disabled || !onToggle;
  return (
    <button
      type="button"
      role={kind}
      aria-checked={on}
      aria-disabled={inert || undefined}
      onClick={inert ? undefined : onToggle}
      className={cn(
        "flex min-h-14 w-full min-w-0 items-center gap-3 rounded-[var(--radius-md)] border px-3.5 py-3 text-left transition-[border-color,background-color,box-shadow]",
        on ? "border-accent/60 bg-accent-soft/50 shadow-[var(--shadow-soft)]" : "border-border bg-surface hover:border-accent/30 hover:bg-surface-2/50",
        inert && "cursor-default hover:border-border",
        disabled && !on && "opacity-60",
      )}
    >
      {leading}
      <span className="grid min-w-0 flex-1 gap-0.5">
        <span className="text-[14px] leading-snug font-medium break-words">{title}</span>
        {hint ? <span className="text-[12.5px] break-words text-muted">{hint}</span> : null}
      </span>
      {trailing}
      <span
        aria-hidden
        className={cn(
          "grid size-5 shrink-0 place-items-center border transition-colors",
          kind === "radio" ? "rounded-full" : "rounded-[6px]",
          on ? "border-accent bg-accent text-accent-fg" : "border-border bg-surface",
        )}
      >
        {locked ? <LockSimpleIcon size={11} weight="bold" /> : on ? <CheckIcon size={12} weight="bold" /> : null}
      </span>
    </button>
  );
}
