import type { ButtonHTMLAttributes } from "react";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "outline" | "danger";
};

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors duration-150 active:scale-[0.98] focus:outline-none focus:ring-2 focus:ring-[rgba(var(--dls-accent-rgb),0.2)] disabled:opacity-50 disabled:cursor-not-allowed";

const VARIANTS: Record<NonNullable<ButtonProps["variant"]>, string> = {
  primary:
    "bg-[var(--dls-accent)] text-white hover:bg-[var(--dls-accent-hover)] border border-transparent shadow-[var(--dls-card-shadow)]",
  secondary:
    "bg-[var(--dls-active)] text-[var(--dls-text-primary)] hover:bg-[var(--dls-hover)] border border-transparent font-semibold",
  ghost:
    "bg-transparent text-[var(--dls-text-secondary)] hover:text-[var(--dls-text-primary)] hover:bg-[var(--dls-hover)]",
  outline:
    "border border-[var(--dls-border)] text-[var(--dls-text-primary)] hover:bg-[var(--dls-hover)] bg-transparent",
  danger:
    "bg-red-50 text-red-700 hover:bg-red-100 border border-red-200",
};

export function Button({
  variant = "primary",
  className,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={`${BASE} ${VARIANTS[variant]} ${className ?? ""}`.trim()}
      {...rest}
    />
  );
}
