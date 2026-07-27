import { useEffect, useRef } from "react";

/** Tiny focus helper so screens reload when shown without react-navigation. */
export function useFocusEffect(fn: () => void | Promise<void>) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    void ref.current();
  }, []);
}
