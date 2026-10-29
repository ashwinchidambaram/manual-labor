// One serial write queue for actions, cursor PUTs and figure ops (design 09 V5, section 3.3).
import { useCallback, useRef, useState } from "react";
import { ApiError } from "../api/client";

export class CancelledError extends Error {
  constructor() {
    super("cancelled after an earlier write failed");
    this.name = "CancelledError";
  }
}

export interface EnqueueOpts {
  /** the caller shows this rejection inline (edit 409 conflict, 422 validation); it is not a failed save */
  inlineStatuses?: readonly number[];
}

export interface Writes {
  /** Runs after every earlier write has settled. Network errors retry twice (callers reuse their request id). */
  enqueue: <T>(run: () => Promise<T>, opts?: EnqueueOpts) => Promise<T>;
  /** number of writes queued or running */
  pending: number;
  /** the last write failed and nothing succeeded since */
  failed: boolean;
  /** drop every queued (not yet started) write; they reject with CancelledError */
  cancelQueued: () => void;
}

export function useVerifyWrites(): Writes {
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const gen = useRef(0);
  const count = useRef(0);
  const [pending, setPending] = useState(0);
  const [failed, setFailed] = useState(false);

  const enqueue = useCallback(<T,>(run: () => Promise<T>, opts: EnqueueOpts = {}): Promise<T> => {
    const myGen = gen.current;
    count.current += 1;
    setPending(count.current);
    const task = chain.current.then(async (): Promise<T> => {
      if (myGen !== gen.current) throw new CancelledError();
      let attempt = 0;
      for (;;) {
        try {
          const r = await run();
          setFailed(false);
          return r;
        } catch (e) {
          if (e instanceof ApiError || attempt >= 2) {
            const inline = e instanceof ApiError && (e.status === 409 || (opts.inlineStatuses ?? []).includes(e.status));
            if (!inline) setFailed(true);
            throw e;
          }
          attempt += 1;
        }
      }
    });
    const settled = task.catch(() => undefined).finally(() => {
      count.current -= 1;
      setPending(count.current);
    });
    chain.current = settled;
    return task;
  }, []);

  const cancelQueued = useCallback(() => {
    gen.current += 1;
  }, []);

  return { enqueue, pending, failed, cancelQueued };
}
