import { screen, waitFor } from "@testing-library/react";
import { expect } from "vitest";
import { renderApp } from "../test/render";
import { installFake } from "../test/server";
import { installVerifyFake, makeBlockDetail, seedQueue, vid, type VerifyFake } from "../test/verifyFake";

export interface Setup {
  f: VerifyFake;
  scope: ReturnType<typeof installFake>;
  r: ReturnType<typeof renderApp>;
}

/** Mount /verify over a queue of `n` items; resolves once the first card is current. */
export async function mountVerify(n = 5, tweak?: (f: VerifyFake) => void, scopeOver: Parameters<typeof installFake>[0] = {}): Promise<Setup> {
  const scope = installFake(scopeOver);
  const f = installVerifyFake();
  seedQueue(f, n);
  tweak?.(f);
  const r = renderApp("/verify");
  await screen.findByTestId(`card-${f.cursor.current_block_id ?? f.items[0]?.block_id ?? vid(1)}`);
  return { f, scope, r };
}

export const card = (id: string) => screen.getByTestId(`card-${id}`);
export const cardFocused = (id: string) => waitFor(() => expect(card(id)).toHaveFocus());
export const detailOf = makeBlockDetail;
