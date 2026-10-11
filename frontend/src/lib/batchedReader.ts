interface Waiter<T> {
  resolve: (value: T | null) => void;
  reject: (error: unknown) => void;
}

/**
 * One request for everything asked in the same moment.
 *
 * Each chip, link and mention asks for its own thing, and a page of thirty
 * still makes one call: the asks made while a render commits are held for a
 * tick, then sent together per community, split at `limit` — the server's own
 * ceiling, which it enforces by refusing a request rather than answering part
 * of it. Each ask is answered with its own item, or `null` where the server
 * left it out: gone, or not this reader's to see.
 */
export const batchedReader = <K extends string | number, T>(
  read: (communityId: number, keys: K[]) => Promise<T[]>,
  keyOf: (item: T) => K,
  limit: number
) => {
  const pending = new Map<number, Map<K, Waiter<T>[]>>();

  const send = (communityId: number, waiting: Map<K, Waiter<T>[]>) => {
    const keys = [...waiting.keys()];
    for (let index = 0; index < keys.length; index += limit) {
      const chunk = keys.slice(index, index + limit);
      const settle = (answer: (waiter: Waiter<T>, key: K) => void) => {
        for (const key of chunk) for (const waiter of waiting.get(key) ?? []) answer(waiter, key);
      };
      read(communityId, chunk).then(
        (items) => {
          const byKey = new Map(items.map((item) => [keyOf(item), item]));
          settle((waiter, key) => waiter.resolve(byKey.get(key) ?? null));
        },
        (error) => settle((waiter) => waiter.reject(error))
      );
    }
  };

  return (communityId: number, key: K): Promise<T | null> =>
    new Promise((resolve, reject) => {
      let waiting = pending.get(communityId);
      if (!waiting) {
        const held = new Map<K, Waiter<T>[]>();
        waiting = held;
        pending.set(communityId, held);
        setTimeout(() => {
          pending.delete(communityId);
          send(communityId, held);
        }, 0);
      }
      waiting.set(key, [...(waiting.get(key) ?? []), { resolve, reject }]);
    });
};
