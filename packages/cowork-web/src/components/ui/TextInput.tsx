import type { InputHTMLAttributes } from "react";

type TextInputProps = InputHTMLAttributes<HTMLInputElement>;

const BASE =
  "px-3 py-2 text-sm rounded-lg border border-[var(--dls-border)] bg-[var(--dls-app-bg)] text-[var(--dls-text-primary)] placeholder:text-[var(--dls-text-secondary)] focus:outline-none focus:ring-2 focus:ring-[rgba(var(--dls-accent-rgb),0.3)] disabled:opacity-50";

export function TextInput({ className, ...rest }: TextInputProps) {
  return (
    <input className={`${BASE} ${className ?? ""}`.trim()} {...rest} />
  );
}
