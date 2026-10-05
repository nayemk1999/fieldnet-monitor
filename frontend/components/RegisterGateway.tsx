"use client";

import { useState } from "react";
import { ApiError, registerGateway } from "@/lib/api";

export function RegisterGateway({ onDone, onError }: { onDone: () => void; onError: (msg: string) => void }) {
  const [open, setOpen] = useState(false);
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [token, setToken] = useState<{ id: string; token: string } | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const gatewayId = id.trim();
    if (!gatewayId) return onError("Gateway id is required.");
    try {
      const res = await registerGateway(gatewayId, name.trim() || gatewayId);
      setToken({ id: gatewayId, token: res.token });
      setId("");
      setName("");
      setOpen(false);
      onDone();
    } catch (err) {
      onError(`Register ${gatewayId} failed: ${(err as ApiError).message}`);
    }
  }

  return (
    <>
      {!open && <button onClick={() => setOpen(true)}>Register gateway</button>}
      {open && (
        <form className="form-row" onSubmit={submit}>
          <input placeholder="gateway id" value={id} onChange={(e) => setId(e.target.value)} autoFocus />
          <input placeholder="name" value={name} onChange={(e) => setName(e.target.value)} />
          <button type="submit">Register</button>
          <button type="button" onClick={() => setOpen(false)}>
            Cancel
          </button>
        </form>
      )}
      {token && (
        <div className="token-box">
          Token for <strong>{token.id}</strong>, shown once. The device sends it as <code>Authorization: Bearer …</code>
          <div className="mono token">{token.token}</div>
          <button onClick={() => setToken(null)}>Dismiss</button>
        </div>
      )}
    </>
  );
}
