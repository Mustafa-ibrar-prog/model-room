"use client";

import Link from "next/link";
import { useActionState } from "react";
import type { AuthState } from "@/server/actions/auth";

type Field = { name: string; label: string; type: string; autoComplete: string };

export function AuthForm({
  action,
  fields,
  submit,
  next,
  footer,
}: {
  action: (state: AuthState, form: FormData) => Promise<AuthState>;
  fields: Field[];
  submit: string;
  next?: string;
  footer?: { text: string; href: string; link: string }[];
}) {
  const [state, formAction, pending] = useActionState(action, undefined);
  return (
    <form action={formAction} className="space-y-4" noValidate>
      {next ? <input type="hidden" name="next" value={next} /> : null}
      {fields.map((f) => (
        <label key={f.name} className="block">
          <span className="text-sm text-mute">{f.label}</span>
          <input
            name={f.name}
            type={f.type}
            autoComplete={f.autoComplete}
            required
            className="mt-1 block w-full rounded-md border border-navy-600 bg-navy-950 px-3 py-2.5 text-ink outline-none focus:border-model"
          />
        </label>
      ))}
      {state?.error ? <p role="alert" className="text-sm text-edge">{state.error}</p> : null}
      {state?.message ? <p role="status" className="text-sm text-model">{state.message}</p> : null}
      <button
        type="submit"
        disabled={pending}
        className="w-full rounded-full bg-model px-4 py-2.5 font-600 text-navy-950 hover:bg-model/90 disabled:opacity-60"
      >
        {pending ? "One moment…" : submit}
      </button>
      {footer?.map((f) => (
        <p key={f.href} className="text-center text-sm text-mute">
          {f.text}{" "}
          <Link href={f.href} className="text-model hover:underline">
            {f.link}
          </Link>
        </p>
      ))}
    </form>
  );
}
