"use client";

import { useState } from "react";

const API_BASE_URL = (process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000/api").replace(/\/$/, "");

function initials(name?: string | null, email?: string | null) {
  return (name?.trim().split(/\s+/).map((part) => part[0]).join("").slice(0, 2) || email?.[0] || "R").toUpperCase();
}

export function Avatar({ name, email, className = "h-8 w-8" }: { name?: string | null; email?: string | null; className?: string }) {
  const [failed, setFailed] = useState(false);
  return (
    <span className={`relative grid shrink-0 place-items-center overflow-hidden rounded-full bg-indigo-tint text-xs font-semibold text-indigo ${className}`}>
      {email && !failed ? (
        <img
          src={`${API_BASE_URL}/avatar`}
          alt=""
          referrerPolicy="no-referrer"
          className="absolute inset-0 h-full w-full object-cover"
          onError={() => setFailed(true)}
        />
      ) : null}
      <span aria-hidden="true">{initials(name, email)}</span>
    </span>
  );
}
